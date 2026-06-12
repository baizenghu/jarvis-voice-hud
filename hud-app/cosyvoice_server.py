#!/usr/bin/env python3
"""Persistent CosyVoice2-0.5B inference server for the hermes voice HUD.

Loads CosyVoice2-0.5B once and exposes ``POST /tts`` taking JSON ``{"text": str}``
and returning 24 kHz mono WAV bytes (audio/wav). A ``GET /health`` endpoint
reports model readiness.

Synthesis uses zero-shot with a cached reference speaker (the repo's bundled
``asset/zero_shot_prompt.wav`` whose transcript is fixed below). The speaker is
pre-registered via ``add_zero_shot_spk`` at startup so per-utterance requests do
not re-extract the prompt embedding.

Run (from the cosyvoice conda env)::

    /home/baizh/anaconda3/envs/cosyvoice/bin/python \
        /home/baizh/hermes-agent/hud-app/cosyvoice_server.py \
        > /tmp/cosyvoice_server.log 2>&1 &

Env overrides:
    COSYVOICE_PORT        listen port (default 8003)
    COSYVOICE_MODEL_DIR   model dir (default <repo>/pretrained_models/CosyVoice2-0.5B)
    COSYVOICE_REF_AUDIO   zero-shot reference wav (default asset/zero_shot_prompt.wav)
    COSYVOICE_REF_TEXT    transcript of the reference wav
"""
import io
import logging
import os
import re
import sys
import time

REPO = "/home/baizh/CosyVoice"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "third_party/Matcha-TTS"))

import torch
import torchaudio
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("cosyvoice_server")

PORT = int(os.environ.get("COSYVOICE_PORT", "8003"))
MODEL_DIR = os.environ.get(
    "COSYVOICE_MODEL_DIR",
    os.path.join(REPO, "pretrained_models/CosyVoice2-0.5B"),
)
REF_AUDIO = os.environ.get(
    "COSYVOICE_REF_AUDIO",
    os.path.join(REPO, "asset/zero_shot_prompt.wav"),
)
REF_TEXT = os.environ.get(
    "COSYVOICE_REF_TEXT",
    "希望你以后能够做的比我还好呦。",
)
SPK_ID = "hermes_ref"

from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402

app = FastAPI()
_model = None


class TTSRequest(BaseModel):
    text: str


@app.on_event("startup")
def _load() -> None:
    global _model
    t0 = time.time()
    log.info("loading CosyVoice2 from %s ...", MODEL_DIR)
    _model = AutoModel(model_dir=MODEL_DIR, fp16=True)
    # Pre-register the zero-shot speaker so per-utterance calls skip prompt
    # embedding extraction.
    ok = _model.add_zero_shot_spk(REF_TEXT, REF_AUDIO, SPK_ID)
    assert ok is True, "add_zero_shot_spk failed"
    log.info(
        "model ready in %.1fs (sample_rate=%d, ref=%s)",
        time.time() - t0, _model.sample_rate, REF_AUDIO,
    )


@app.get("/health")
def health() -> dict:
    return {"ok": _model is not None, "sample_rate": getattr(_model, "sample_rate", None)}


@app.post("/tts")
def tts(req: TTSRequest) -> Response:
    text = (req.text or "").strip()
    if not text:
        return Response(content=b"", status_code=400)
    t0 = time.time()
    chunks = []
    # CosyVoice both (a) truncates multi-sentence input in one inference call
    # and (b) repeats/garbles long comma-heavy clauses (esp. with numbers).
    # Fix: split on sentence enders; further break any segment longer than
    # ~18 chars on commas so each synthesized chunk is short and clean. Then
    # concatenate — the whole reply is spoken, without repetition.
    segments = []
    for sent in re.split(r"(?<=[。！？；!?;\n])", text):
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) <= 18:
            segments.append(sent)
        else:
            segments.extend(
                p.strip() for p in re.split(r"(?<=[，,、])", sent) if p.strip()
            )
    if not segments:
        segments = [text]
    # zero_shot with cached spk: prompt_text/prompt_wav empty, use spk id.
    for seg in segments:
        for out in _model.inference_zero_shot(
            seg.strip(), "", "", zero_shot_spk_id=SPK_ID, stream=False
        ):
            chunks.append(out["tts_speech"])
    audio = torch.concat(chunks, dim=1) if chunks else torch.zeros(1, 1)
    buf = io.BytesIO()
    torchaudio.save(buf, audio, _model.sample_rate, format="wav")
    wav = buf.getvalue()
    dur = audio.shape[1] / _model.sample_rate
    log.info(
        "synth %.2fs audio for %d chars in %.2fs (rtf=%.2f)",
        dur, len(text), time.time() - t0, (time.time() - t0) / max(dur, 1e-6),
    )
    return Response(content=wav, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
