#!/usr/bin/env python3
"""OpenAI-compatible Whisper STT API for the Linux GPU center.

Exposes ``POST /v1/audio/transcriptions`` (multipart: file=<audio>) returning
``{"text": ...}`` so a remote hermes (Windows, native) can use it as its STT by
setting ``stt.provider: openai`` + ``stt.openai.base_url: http://<center>:PORT/v1``.

Reuses hermes' own tuned STT path (`tools.voice_mode.transcribe_recording` →
large-v3 + VAD + hallucination suppression + Chinese filter list), so the
remote API inherits every STT fix made for the local HUD.

Run (hermes venv, bind LAN so the Windows laptop can reach it):

    HOST=0.0.0.0 PORT=8010 .venv/bin/python hud-app/whisper_api.py
"""
from __future__ import annotations

import os
import tempfile

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile

from tools.voice_mode import transcribe_recording

app = FastAPI(title="whisper STT API (OpenAI-compatible)")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form("large-v3"),
    language: str = Form(""),
) -> dict:
    # Persist the uploaded audio to a temp file with its original suffix so the
    # STT pipeline (which sniffs by extension) accepts it.
    suffix = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="whisper_api_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(await file.read())
        result = transcribe_recording(path)
    finally:
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except OSError:
            pass
    # OpenAI transcription response shape.
    return {"text": (result.get("transcript") or "").strip()}


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8010"))
    uvicorn.run(app, host=host, port=port, log_level="warning")
