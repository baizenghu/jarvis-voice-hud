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

import os
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
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
