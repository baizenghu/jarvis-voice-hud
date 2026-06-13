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

class WakeHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.busy = False
        self.idle_since = 0.0

    def accepts_wake(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return not self.busy and (now - self.idle_since) >= WAKE_COOLDOWN_S

    def set_busy(self, busy: bool, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
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
