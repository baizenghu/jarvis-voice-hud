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
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse

from tui_gateway.ws import handle_ws

HERE = Path(__file__).parent
app = FastAPI(title="voice-harness dev server")


@app.websocket("/api/ws")
async def ws(ws: WebSocket) -> None:
    await handle_ws(ws)


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
