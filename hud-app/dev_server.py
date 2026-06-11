"""Dev-only server for the Phase 0 voice harness (Linux/browser smoke test).

Serves `hud-app/voice-harness.html` and mounts the JSON-RPC WebSocket at
`/api/ws`, WITHOUT the built `web_dist` that `hermes web` requires. This exists
only to validate the voice round-trip during development; it is not part of the
shipped product (the real client is the Tauri HUD in later phases).

Run (after `pip install -e ".[voice]" edge-tts` in the project venv):

    .venv/bin/python hud-app/dev_server.py
    # then open http://localhost:8080/ in a browser (localhost = mic allowed)
"""
from __future__ import annotations

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
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning")
