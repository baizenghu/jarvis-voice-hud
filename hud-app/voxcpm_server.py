#!/usr/bin/env python3
"""Persistent VoxCPM2 inference server for the hermes voice HUD.

Loads VoxCPM2 (OpenBMB) once and exposes ``POST /tts`` taking JSON
``{"text": str}`` and returning mono WAV bytes (audio/wav) at the model's
native sample rate. A ``GET /health`` endpoint reports model readiness.

Synthesis uses voice cloning with a cached reference voice (the haoran ref
wav + its transcript), passed as ``prompt_wav_path`` + ``prompt_text`` so the
clone is conditioned on a known reference utterance.

Run (from the voxcpm conda env)::

    /home/baizh/anaconda3/envs/voxcpm/bin/python \
        /home/baizh/hermes-agent/hud-app/voxcpm_server.py \
        > /tmp/voxcpm_server.log 2>&1 &

Env overrides:
    VOXCPM_PORT        listen port (default 8005)
    VOXCPM_MODEL_ID    HF model id (default openbmb/VoxCPM2)
    VOXCPM_REF_AUDIO   reference wav (default <hud-app>/voices/haoran_ref.wav)
    VOXCPM_REF_TEXT    transcript of the reference wav
"""
import io
import logging
import os
import time

import soundfile as sf
import torch
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
from voxcpm import VoxCPM

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("voxcpm_server")

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("VOXCPM_PORT", "8005"))
MODEL_ID = os.environ.get("VOXCPM_MODEL_ID", "openbmb/VoxCPM2")
REF_AUDIO = os.environ.get(
    "VOXCPM_REF_AUDIO",
    os.path.join(HERE, "voices/haoran_ref.wav"),
)
REF_TEXT = os.environ.get(
    "VOXCPM_REF_TEXT",
    "你好,我是昊然,我的声音沉稳自然,语调平和,语速平稳,温润醇厚,"
    "兼具温柔与力量,听起来亲切而有信任感。",
)

app = FastAPI()
_model = None
_sr = None


class TTSRequest(BaseModel):
    text: str


@app.on_event("startup")
def _load() -> None:
    global _model, _sr
    t0 = time.time()
    log.info("loading VoxCPM %s (ref=%s) ...", MODEL_ID, REF_AUDIO)
    # load_denoiser=False: we feed a clean studio reference, skip the ~ZipEnhancer
    # denoiser to save VRAM and avoid an extra model download.
    _model = VoxCPM.from_pretrained(MODEL_ID, load_denoiser=False)
    _sr = _model.tts_model.sample_rate
    log.info("model ready in %.1fs (sample_rate=%d)", time.time() - t0, _sr)


@app.get("/health")
def health() -> dict:
    return {"ok": _model is not None, "sample_rate": _sr}


@app.post("/tts")
def tts(req: TTSRequest) -> Response:
    text = (req.text or "").strip()
    if not text:
        return Response(content=b"", status_code=400)
    t0 = time.time()
    # Voice cloning conditioned on the cached reference utterance.
    audio = _model.generate(
        text=text,
        prompt_wav_path=REF_AUDIO,
        prompt_text=REF_TEXT,
        normalize=True,
    )
    buf = io.BytesIO()
    sf.write(buf, audio, _sr, format="WAV")
    wav = buf.getvalue()
    dur = len(audio) / _sr
    elapsed = time.time() - t0
    log.info(
        "synth %.2fs audio for %d chars in %.2fs (rtf=%.2f)",
        dur, len(text), elapsed, elapsed / max(dur, 1e-6),
    )
    return Response(content=wav, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
