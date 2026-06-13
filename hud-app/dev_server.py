"""Dev-only server for the Phase 0 voice harness (Linux/browser smoke test).

Serves `hud-app/voice-harness.html` and mounts the JSON-RPC WebSocket at
`/api/ws`, WITHOUT the built `web_dist` that `hermes web` requires. This exists
only to validate the voice round-trip during development; it is not part of the
shipped product (the real client is the Tauri HUD in later phases).

Run (after `pip install -e ".[voice]" edge-tts` in the project venv):

    # local only (mic via localhost):
    .venv/bin/python hud-app/dev_server.py
    # then open http://localhost:8765/

    # remote over WireGuard/LAN (mic needs https — bind the WG IP + a self-signed cert):
    HOST=10.8.0.2 PORT=40445 \
      SSL_CERTFILE=hud-app/.certs/cert.pem SSL_KEYFILE=hud-app/.certs/key.pem \
      .venv/bin/python hud-app/dev_server.py
    # then open https://10.8.0.2:40445/ on the remote machine (accept the cert warning once)

Env overrides: HOST (default 127.0.0.1), PORT (default 8765), SSL_CERTFILE + SSL_KEYFILE
(both set → serve https). Binding a non-localhost HOST exposes the JSON-RPC gateway on that
interface — only do this on a trusted network (e.g. the WireGuard interface).
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from urllib.parse import quote

import httpx
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from tui_gateway.ws import handle_ws

HERE = Path(__file__).parent

# Upstream hermes installs lack the voice byte RPCs this fork adds — register
# them at startup (no-op on the fork). Vendored deps live next to this file.
import sys as _sys

_sys.path.insert(0, str(HERE))
import gateway_voice_patch

gateway_voice_patch.register()
DIST = HERE / "hud" / "dist"
app = FastAPI(title="voice-harness dev server")


@app.websocket("/api/ws")
async def ws(ws: WebSocket) -> None:
    await handle_ws(ws)


# --- Phase 3 wake-word plumbing -------------------------------------------
# The KWS listener (kws_listener.py) POSTs /api/wake on a hotword hit; the HUD
# subscribes to /api/events to receive {"type":"wake"} and reports its own
# {"type":"busy"}/{"type":"idle"} on the same socket so wakes are suppressed
# while a dialog turn is running (TTS playback would otherwise re-trigger KWS).
WAKE_COOLDOWN_S = 1.0  # ignore wakes right after a turn ends (TTS echo tail)
BUSY_MAX_S = 45.0  # busy 超此时长视为僵死会话,自动复位放行唤醒(防永久锁死)

class WakeHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.busy = False
        self.idle_since = 0.0
        self.busy_since = 0.0

    def accepts_wake(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        # busy 自愈:一次卡死会话(TTS 卡/HUD 中途断)会把 busy 永久置真、之后全唤不醒。
        # 超过 BUSY_MAX_S 仍 busy 视为僵死,强制复位放行。
        if self.busy and (now - self.busy_since) > BUSY_MAX_S:
            self.busy = False
            self.idle_since = now
        return not self.busy and (now - self.idle_since) >= WAKE_COOLDOWN_S

    def set_busy(self, busy: bool, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if busy and not self.busy:
            self.busy_since = now
        if self.busy and not busy:
            self.idle_since = now
        self.busy = busy

    async def broadcast(self, event: dict) -> int:
        """Push an action event to all HUD /api/events clients. Returns live count."""
        dead = []
        for c in self.clients:
            try:
                await c.send_json(dict(event))
            except Exception:
                dead.append(c)
        for c in dead:
            self.clients.discard(c)
        return len(self.clients)

hub = WakeHub()


# --- voice_hud agent tools -------------------------------------------------
# The in-process gateway agent (tui_gateway/server.py) drives the thin HUD by
# calling voice_hud tools (play_music / stop_music / end_session). Their
# handlers broadcast action events to /api/events via _safe_emit, which bounces
# hub.broadcast() onto the uvicorn event loop from whatever thread the tool
# dispatch runs on (handlers may run in a thread pool).
import voice_hud_tools
from agent.async_utils import safe_schedule_threadsafe
from tools.registry import registry

_main_loop: asyncio.AbstractEventLoop | None = None


@app.on_event("startup")
async def _capture_loop() -> None:
    global _main_loop
    _main_loop = asyncio.get_running_loop()


def _safe_emit(event: dict) -> None:
    """Schedule hub.broadcast(event) on the uvicorn loop, thread-safe."""
    safe_schedule_threadsafe(hub.broadcast(event), _main_loop)


def _register_voice_hud_tools() -> None:
    # schema MUST be {"description":..., "parameters":{...}} — registry.get_definitions
    # merges {**schema, "name": name} into the OpenAI `function` object. A bare
    # JSON Schema would push type/properties to the function top level and drop
    # the required `parameters` wrapper.
    voice_hud_tools.set_broadcast(_safe_emit)
    # play_music / stop_music (webview playback) RETIRED — music now plays in a
    # real browser via the play-music skill (clawtouch + 歌曲宝), not in-webview.
    # Only end_session remains for the agent-orchestrated session lifecycle.
    registry.register(
        name="end_session",
        toolset="voice_hud",
        schema={
            "description": "结束本次语音对话、HUD 隐身(用户说退下/再见时调用)",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=voice_hud_tools.end_session_handler,
        description="结束本次语音对话、HUD 隐身(用户说退下/再见时调用)",
    )


def _merge_voice_hud(base: list[str] | None) -> list[str] | None:
    """Add voice_hud to an enabled-toolsets list. None means 'all' (already
    covers it). NOTE: MCP servers are NOT handled here — hermes resolves them
    natively from config (`_load_enabled_toolsets` already includes the server
    name once `mcp_servers.<name>` is configured). Only voice_hud, our custom
    runtime-registered toolset, is invisible to that config path and needs this."""
    if base is None:
        return None
    return base if "voice_hud" in base else [*base, "voice_hud"]


def _patch_enabled_toolsets() -> None:
    """Make the gateway agent actually SEE voice_hud.

    The gateway builds its agent with enabled_toolsets=_load_enabled_toolsets()
    (its own module-level fn). That returns a concrete CLI/config list that does
    NOT include voice_hud, so merely registering the tools leaves them invisible
    to the agent (confirmed: 0.3 smoke — agent chatted instead of calling
    play_music). Wrap that module fn so every agent build merges voice_hud in.
    """
    import tui_gateway.server as _gw

    _orig = _gw._load_enabled_toolsets

    def _patched() -> list[str] | None:
        return _merge_voice_hud(_orig())

    _gw._load_enabled_toolsets = _patched


def _enabled_toolsets_for_session() -> list[str] | None:
    """Contract-test view: enabled toolsets with voice_hud merged in."""
    from tui_gateway.server import _load_enabled_toolsets

    return _merge_voice_hud(_load_enabled_toolsets())


def _start_mcp_discovery() -> None:
    """Run hermes's standard MCP tool discovery in the background.

    dev_server is a minimal harness and does NOT run tui_gateway.entry.main(),
    which is where the real gateway kicks off MCP discovery. Without this,
    configured `mcp_servers` are never spawned/registered. This calls hermes's
    own `discover_mcp_tools()` (the same entry.py uses) — not a reimplementation.
    Gated on config so the MCP SDK import cost stays off the path when unused.
    """
    try:
        from hermes_cli.config import read_raw_config

        servers = (read_raw_config() or {}).get("mcp_servers")
        if not (isinstance(servers, dict) and servers):
            return
    except Exception:
        pass

    import threading

    def _run() -> None:
        try:
            from tools.mcp_tool import discover_mcp_tools

            discover_mcp_tools()
        except Exception:
            import logging

            logging.getLogger(__name__).warning("MCP discovery failed", exc_info=True)

    threading.Thread(target=_run, name="dev-mcp-discovery", daemon=True).start()


_register_voice_hud_tools()
_patch_enabled_toolsets()
_start_mcp_discovery()


@app.websocket("/api/events")
async def events(ws: WebSocket) -> None:
    await ws.accept()
    hub.clients.add(ws)
    try:
        while True:
            msg = await ws.receive_json()
            t = msg.get("type")
            if t in ("busy", "idle"):
                hub.set_busy(t == "busy")
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)
        if not hub.clients:
            hub.set_busy(False)


@app.post("/api/wake")
async def wake() -> JSONResponse:
    if not hub.accepts_wake():
        return JSONResponse({"ok": False, "reason": "busy"})
    dead = []
    for c in hub.clients:
        try:
            await c.send_json({"type": "wake"})
        except Exception:
            dead.append(c)
    for c in dead:
        hub.clients.discard(c)
    return JSONResponse({"ok": True, "clients": len(hub.clients)})


@app.post("/api/audio_level")
async def audio_level(request: Request) -> JSONResponse:
    """系统输出声级(由 audio_levels.py 从 sink monitor 算出后 POST 进来),
    广播给 HUD 让光圈+背景跟独立播放器的音乐跳动(webview analyser 看不到那段音频)。"""
    d = await request.json()
    n = await hub.broadcast({
        "type": "audio",
        "bass": float(d.get("bass", 0.0)),
        "mid": float(d.get("mid", 0.0)),
        "treble": float(d.get("treble", 0.0)),
    })
    return JSONResponse({"ok": True, "clients": n})


@app.post("/api/music_state")
async def music_state(request: Request) -> JSONResponse:
    """播放器真实放歌状态(gequbao_play.py 放上/停时 POST)。HUD 据此进/出粉色
    音乐态,避免 TTS、系统杂音按音量误触发。"""
    d = await request.json()
    n = await hub.broadcast({"type": "music_state", "on": bool(d.get("on"))})
    return JSONResponse({"ok": True, "clients": n})


_GEQUBAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gequbao_play.py")


@app.post("/api/music_duck")
async def music_duck(request: Request) -> JSONResponse:
    """对话期间把歌曲音量压低(CDP),会话结束恢复。不压的话音乐灌进 STT 录音,
    系统 AEC 在 double-talk 下压不净 near-end 语音,whisper 判 no speech。"""
    d = await request.json()
    vol = "0.12" if bool(d.get("on")) else "1.0"
    subprocess.Popen([sys.executable, _GEQUBAO, "--volume", vol],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return JSONResponse({"ok": True, "vol": vol})


# --- Phase 4 music proxy (M1) ---------------------------------------------
# "Play a song" plays IN the HUD webview via <audio src="/api/music?q=...">, so
# the existing Web Audio analyser sees it and the voiceprint core dances (see
# decisions/0006). The stream MUST be same-origin: a cross-origin <audio> fed
# into createMediaElementSource is tainted and the analyser reads all-zeros.
# So this endpoint resolves an online stream with yt-dlp and proxies the bytes.
#
# MUSIC_UPSTREAM (optional): when set, this gateway does NOT resolve locally —
# it relays /api/music to another gateway's /api/music (e.g. the GPU center,
# whose IP isn't bot-blocked by YouTube). Home reaches YouTube through the
# center over WireGuard, with no cookies. The relayed stream stays same-origin
# to the HUD page (the analyser requirement) because home re-proxies the bytes.
MUSIC_FORMAT = "bestaudio[ext=m4a]/bestaudio"  # m4a/AAC: WebKitGTK decodes it (no webm/ogg)
MUSIC_RESOLVE_TIMEOUT_S = 20.0
MUSIC_UPSTREAM = os.environ.get("MUSIC_UPSTREAM", "").rstrip("/")


async def _resolve_stream_url(query: str) -> str | None:
    """Resolve a search query to a direct audio stream URL via ``yt-dlp -g``.

    Runs yt-dlp under the current interpreter (``python -m yt_dlp``) so it works
    without PATH setup and identically on Windows.
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "yt_dlp", "-f", MUSIC_FORMAT, "-g", f"ytsearch1:{query}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=MUSIC_RESOLVE_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        return None
    lines = [ln for ln in out.decode().splitlines() if ln.strip()]
    return lines[0] if lines else None


async def _proxy_stream(url: str, fwd_headers: dict) -> StreamingResponse:
    """Stream-proxy an upstream audio URL back to the caller (same-origin to the
    HUD page), forwarding Range and passing through the content headers."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(MUSIC_RESOLVE_TIMEOUT_S, read=None))
    req = client.build_request("GET", url, headers=fwd_headers)
    resp = await client.send(req, stream=True)

    async def body():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    passthrough = ("content-type", "content-length", "content-range", "accept-ranges")
    headers = {k: resp.headers[k] for k in passthrough if k in resp.headers}
    headers.setdefault("content-type", "audio/mp4")
    # CORS so the Tauri HUD (tauri://localhost) can stream this cross-origin with
    # crossOrigin="anonymous" WITHOUT tainting the Web Audio analyser (the core/
    # background dance needs untainted FFT). Local WG-only gateway → * is fine.
    headers["access-control-allow-origin"] = "*"
    return StreamingResponse(body(), status_code=resp.status_code, headers=headers)


@app.get("/api/music", response_model=None)
async def music(request: Request, q: str = "") -> StreamingResponse | JSONResponse:
    q = q.strip()
    if not q:
        return JSONResponse({"ok": False, "error": "missing q"}, status_code=400)

    fwd_headers = {}
    rng = request.headers.get("range")  # forward Range so <audio> can seek
    if rng:
        fwd_headers["Range"] = rng

    # Relay mode: hand off to the upstream gateway (it resolves + proxies).
    if MUSIC_UPSTREAM:
        return await _proxy_stream(f"{MUSIC_UPSTREAM}/api/music?q={quote(q)}", fwd_headers)

    url = await _resolve_stream_url(q)
    if not url:
        return JSONResponse({"ok": False, "error": "resolve failed"}, status_code=502)
    return await _proxy_stream(url, fwd_headers)


# The old Phase 0 harness stays available at /harness as a fallback.
@app.get("/harness")
def harness() -> FileResponse:
    return FileResponse(HERE / "voice-harness.html")


# Serve the built Jarvis HUD at / when dist/ exists; otherwise fall back to the
# harness and hint to build. The /api/ws + /harness routes above are registered
# first, so they win over the StaticFiles mount.
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="hud")
else:
    print(f"[dev_server] {DIST} not found — serving harness at /. "
          f"Build the HUD: cd hud-app/hud && npm install && npm run build")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(HERE / "voice-harness.html")


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    cert = os.environ.get("SSL_CERTFILE")
    key = os.environ.get("SSL_KEYFILE")
    kwargs = {"host": host, "port": port, "log_level": os.environ.get("LOG_LEVEL", "info")}
    if cert and key:
        kwargs["ssl_certfile"] = cert
        kwargs["ssl_keyfile"] = key
        scheme = "https"
    else:
        scheme = "http"
    print(f"voice harness dev server: {scheme}://{host}:{port}/")
    uvicorn.run(app, **kwargs)
