#!/usr/bin/env python3
"""Persistent IndexTTS-2 inference server for the hermes voice HUD.

Loads IndexTTS2 once and exposes ``POST /tts`` taking JSON ``{"text": str}`` and
returning WAV bytes (audio/wav). A ``GET /health`` endpoint reports readiness.

Synthesis clones the timbre of a fixed speaker reference audio
(``INDEXTTS_REF_AUDIO``). IndexTTS-2 needs ONLY the speaker reference audio --
no reference transcript -- which avoids the prompt-text leak other engines had.
It segments long text internally, so we pass the full text in one call.

Run (from the index-tts venv)::

    /home/baizh/PycharmProjects/index-tts/.venv/bin/python -u \
        /home/baizh/hermes-agent/hud-app/indextts_server.py \
        > /tmp/indextts_server.log 2>&1 &

Env overrides:
    INDEXTTS_PORT        listen port (default 8004)
    INDEXTTS_REF_AUDIO   speaker reference wav (default voices/haoran_ref.wav)
"""
import logging
import os
import sys
import tempfile
import time

# Make the indextts package importable and let it find ./checkpoints relative
# to its own repo (infer_v2 sets HF_HUB_CACHE='./checkpoints/hf_cache').
INDEX_TTS_REPO = "/home/baizh/PycharmProjects/index-tts"
sys.path.insert(0, INDEX_TTS_REPO)
os.chdir(INDEX_TTS_REPO)

from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("indextts_server")

PORT = int(os.environ.get("INDEXTTS_PORT", "8004"))
MODEL_DIR = os.path.join(INDEX_TTS_REPO, "checkpoints")
CFG_PATH = os.path.join(MODEL_DIR, "config.yaml")
REF_AUDIO = os.environ.get(
    "INDEXTTS_REF_AUDIO",
    "/home/baizh/hermes-agent/hud-app/voices/haoran_ref.wav",
)

from indextts.infer_v2 import IndexTTS2  # noqa: E402

app = FastAPI()
_model = None


class TTSRequest(BaseModel):
    text: str


@app.on_event("startup")
def _load() -> None:
    global _model
    t0 = time.time()
    log.info("loading IndexTTS2 from %s ...", MODEL_DIR)
    _model = IndexTTS2(
        model_dir=MODEL_DIR,
        cfg_path=CFG_PATH,
        use_fp16=True,
        use_deepspeed=False,
        use_cuda_kernel=False,
    )
    log.info("model ready in %.1fs (ref=%s)", time.time() - t0, REF_AUDIO)


@app.get("/health")
def health() -> dict:
    return {"ok": _model is not None}


@app.post("/tts")
def tts(req: TTSRequest) -> Response:
    text = (req.text or "").strip()
    if not text:
        return Response(content=b"", status_code=400)
    t0 = time.time()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        out_path = tf.name
    try:
        _model.infer(
            spk_audio_prompt=REF_AUDIO,
            text=text,
            output_path=out_path,
            verbose=False,
        )
        with open(out_path, "rb") as f:
            wav = f.read()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass
    log.info("synth %d chars in %.2fs (%d wav bytes)", len(text), time.time() - t0, len(wav))
    return Response(content=wav, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
