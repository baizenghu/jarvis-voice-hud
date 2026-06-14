#!/usr/bin/env python3
"""Standalone voice service (phase 5): STT + TTS over HTTP, zero hermes import.

decisions/0007: Jarvis is mouth+ears (STT/TTS); this service is that mouth/ears,
parallel to the agent black box and independent of it. The HUD talks to it via
plain HTTP fetch instead of routing voice through the gateway/agent process.

Endpoints (see specs/phase5-voice-service.md §3):
  GET  /health      → readiness + backend report (token-exempt)
  POST /transcribe  multipart file=<audio> [backend] → {"text": ...}
  POST /synthesize  JSON {"text", "backend"?} → audio/wav bytes

  backend ∈ {local, baidu}; baidu → 501 (interface-only this phase).

STT runs in-process (voice_svc_stt, faster-whisper). TTS forwards to the
already-independent cosyvoice_server (:8003) — its _infer_lock + single-char
poison compensation stay there; this service only validates + forwards (never
duplicates the poison compensation).

Auth mirrors the phase 1 gateway gate (JARVIS_GATEWAY_TOKEN / HOST, fail-closed
on non-loopback) but guards this service's BARE paths, not /api/*.

Run:  HOST=0.0.0.0 PORT=8011 JARVIS_GATEWAY_TOKEN=... \\
          STT_MODEL=<turbo dir> .venv/bin/python hud-app/voice_svc.py
"""
from __future__ import annotations

import hmac
import os
import sys
import tempfile
import urllib.request

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import voice_svc_stt

# --- TTS upstream (already-independent cosyvoice_server) ------------------
COSYVOICE_API = os.environ.get("COSYVOICE_API", "http://127.0.0.1:8003").rstrip("/")
# LAN-direct: a local proxy would hijack center-bound requests — ignore proxy env.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _tts_forward(text: str) -> bytes:
    """POST text to cosyvoice_server /tts, return the WAV bytes (decision B: no
    mp3 transcode — the HUD plays audio/wav natively). Raises on non-200/empty;
    the poison compensation + _infer_lock live in cosyvoice_server, not here."""
    import json
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{COSYVOICE_API}/tts", data=body, headers={"Content-Type": "application/json"}
    )
    with _OPENER.open(req, timeout=180) as resp:
        wav = resp.read()
    if not wav:
        raise RuntimeError("cosyvoice returned empty audio")
    return wav


def _tts_ready() -> bool:
    """Best-effort upstream reachability for /health (never raises)."""
    try:
        req = urllib.request.Request(f"{COSYVOICE_API}/health")
        with _OPENER.open(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


# --- auth (copied pure predicates from dev_server.py:64-95) ----------------
# NOTE: we copy only the path-agnostic predicates; the dev_server middleware
# guards /api/* and would silently let this service's bare paths through, so the
# middleware below is rewritten to guard /transcribe + /synthesize.
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _auth_required(host: str) -> bool:
    return host not in _LOOPBACK


def _token_ok(provided: str | None) -> bool:
    expected = os.environ.get("JARVIS_GATEWAY_TOKEN") or ""
    if not expected or not provided:
        return False
    try:
        return hmac.compare_digest(provided, expected)
    except TypeError:
        return False


def _auth_enabled() -> bool:
    return _auth_required(os.environ.get("HOST", "127.0.0.1"))


def _authorized(token: str | None) -> bool:
    return True if not _auth_enabled() else _token_ok(token)


def _enforce_fail_closed(host: str) -> None:
    if _auth_required(host) and not (os.environ.get("JARVIS_GATEWAY_TOKEN") or ""):
        print(f"[voice_svc] FATAL: HOST={host} is non-loopback but "
              f"JARVIS_GATEWAY_TOKEN is unset — refusing to start (fail closed). "
              f"Set a token, or bind 127.0.0.1.", file=sys.stderr)
        raise SystemExit(2)


def _stt_backend(requested: str | None) -> str:
    return (requested or os.getenv("STT_BACKEND") or "local").lower()


def _tts_backend(requested: str | None) -> str:
    return (requested or os.getenv("TTS_BACKEND") or "local").lower()


app = FastAPI(title="jarvis voice service (STT+TTS)")

# Token is exempt for /health (readiness probe) and OPTIONS (CORS preflight);
# everything else under a non-loopback bind requires ?token=.
_TOKEN_EXEMPT = {"/health"}


@app.middleware("http")
async def _auth_mw(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in _TOKEN_EXEMPT:
        return await call_next(request)
    if not _authorized(request.query_params.get("token")):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


# CORSMiddleware added AFTER the auth middleware so it wraps it (outermost):
# preflight is answered and CORS headers are attached even to 401 responses.
# token rides ?token= (not a cookie) → allow_credentials stays False; port
# wildcards need a regex (CORSMiddleware allow_origins has no glob).
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"tauri://localhost|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


class SynthesizeRequest(BaseModel):
    text: str = ""
    backend: str | None = None


@app.on_event("startup")
async def _on_startup() -> None:
    _enforce_fail_closed(os.environ.get("HOST", "127.0.0.1"))


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "stt_backend": _stt_backend(None),
        "tts_backend": _tts_backend(None),
        "stt_ready": voice_svc_stt._local_model is not None,
        "tts_ready": _tts_ready(),
    }


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    backend: str = Form(""),
):
    bk = _stt_backend(backend)
    if bk == "baidu":
        return JSONResponse({"error": "baidu STT backend not implemented"}, status_code=501)

    suffix = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="voice_svc_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(await file.read())
        text = voice_svc_stt.transcribe(path, backend=bk)
    finally:
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except OSError:
            pass
    return {"text": text}


@app.post("/synthesize")
def synthesize(req: SynthesizeRequest):
    bk = _tts_backend(req.backend)
    if bk == "baidu":
        return JSONResponse({"error": "baidu TTS backend not implemented"}, status_code=501)
    text = (req.text or "").strip()
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    try:
        wav = _tts_forward(text)
    except Exception as e:  # upstream non-200/empty/unreachable → 502, HUD degrades
        return JSONResponse({"error": f"tts upstream failed: {e}"}, status_code=502)
    return Response(content=wav, media_type="audio/wav")


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8011"))
    _enforce_fail_closed(host)
    uvicorn.run(app, host=host, port=port, log_level="warning")
