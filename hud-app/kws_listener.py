"""Phase 3 wake-word listener: sherpa-onnx Chinese KWS ("贾维斯") → POST /api/wake.

Runs next to the home gateway (dev_server :8765). On a hotword hit it POSTs
the gateway's /api/wake, which broadcasts {"type":"wake"} to the HUD over
/api/events (suppressed while a dialog turn is running — see dev_server.py).

Model: sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01 (CPU, zero training;
custom hotword is just pinyin tokens in the keywords file).

Run:
    .venv/bin/python hud-app/kws_listener.py                  # live mic
    .venv/bin/python hud-app/kws_listener.py path/to.wav ...  # offline file test

Env: KWS_MODEL_DIR (default ~/kws-model), WAKE_URL (default
http://127.0.0.1:8765/api/wake), KWS_KEYWORD (default "j iǎ w éi s ī @贾维斯").
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import sherpa_onnx

MODEL_DIR = Path(os.environ.get("KWS_MODEL_DIR", os.path.expanduser("~/kws-model")))
# 英文唤醒("Jarvis")用 gigaspeech 英文模型并行检测;目录不存在则只跑中文
EN_MODEL_DIR = Path(os.environ.get("KWS_EN_MODEL_DIR", os.path.expanduser("~/kws-model-en")))
WAKE_URL = os.environ.get("WAKE_URL", "http://127.0.0.1:8765/api/wake")
KEYWORD = os.environ.get("KWS_KEYWORD", "j iǎ w éi s ī @贾维斯")
EN_KEYWORD = os.environ.get("KWS_EN_KEYWORD", "▁JA R VI S @Jarvis")
SAMPLE_RATE = 16000


def _spotter(model_dir: Path, keyword: str) -> sherpa_onnx.KeywordSpotter:
    kw_file = model_dir / "keywords_jarvis.txt"
    kw_file.write_text("\n".join(k.strip() for k in keyword.split(";") if k.strip()) + "\n", encoding="utf-8")
    return sherpa_onnx.KeywordSpotter(
        tokens=str(model_dir / "tokens.txt"),
        encoder=str(model_dir / "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
        decoder=str(model_dir / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
        joiner=str(model_dir / "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"),
        keywords_file=str(kw_file),
        num_threads=2,
    )


def make_spotters() -> list[sherpa_onnx.KeywordSpotter]:
    spotters = [_spotter(MODEL_DIR, KEYWORD)]
    if EN_MODEL_DIR.is_dir():
        spotters.append(_spotter(EN_MODEL_DIR, EN_KEYWORD))
    else:
        print(f"[kws] {EN_MODEL_DIR} 不存在,只跑中文唤醒", flush=True)
    return spotters


def notify_wake() -> None:
    req = urllib.request.Request(WAKE_URL, data=b"", method="POST")
    # local gateway — never go through a proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=3) as resp:
            print(f"[kws] wake → {resp.read().decode()}", flush=True)
    except Exception as e:
        print(f"[kws] wake POST failed: {e}", flush=True)


def run_files(spotters: list[sherpa_onnx.KeywordSpotter], paths: list[str]) -> int:
    """Offline self-test: decode wav files, print hits. Returns #hits."""
    import wave

    import numpy as np

    hits = 0
    for p in paths:
        with wave.open(p) as w:
            assert w.getframerate() == SAMPLE_RATE, f"{p}: need 16kHz, got {w.getframerate()}"
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        samples = pcm.astype("float32") / 32768.0
        got = ""
        for spotter in spotters:
            s = spotter.create_stream()
            s.accept_waveform(SAMPLE_RATE, samples)
            # streaming model needs right-context — pad 0.5s silence after the audio
            s.accept_waveform(SAMPLE_RATE, np.zeros(SAMPLE_RATE // 2, dtype="float32"))
            s.input_finished()
            while spotter.is_ready(s):
                spotter.decode_stream(s)
                r = spotter.get_result(s)
                if r:
                    got = r
                    spotter.reset_stream(s)
        print(f"[kws] {p}: {'HIT ' + got if got else 'no hit'}", flush=True)
        hits += bool(got)
    return hits


def run_mic(spotters: list[sherpa_onnx.KeywordSpotter]) -> None:
    import sounddevice as sd

    streams = [sp.create_stream() for sp in spotters]
    print(f"[kws] listening for 「贾维斯」/「Jarvis」({len(spotters)} models) → {WAKE_URL}", flush=True)
    with sd.InputStream(channels=1, dtype="float32", samplerate=SAMPLE_RATE) as mic:
        while True:
            samples, _ = mic.read(int(0.1 * SAMPLE_RATE))
            flat = samples.reshape(-1)
            for spotter, stream in zip(spotters, streams):
                stream.accept_waveform(SAMPLE_RATE, flat)
                while spotter.is_ready(stream):
                    spotter.decode_stream(stream)
                    if spotter.get_result(stream):
                        notify_wake()
                        spotter.reset_stream(stream)


if __name__ == "__main__":
    spotters = make_spotters()
    if len(sys.argv) > 1:
        sys.exit(0 if run_files(spotters, sys.argv[1:]) > 0 else 1)
    run_mic(spotters)
