#!/usr/bin/env python3
"""hermes command-type TTS provider bridge to the local CosyVoice2 server.

hermes runs this as: ``cosyvoice_say.py <input_path> <output_path>`` where
``input_path`` holds the text to speak and ``output_path`` is where the audio
must be written (we write MP3 so the HUD's audio/mpeg labelling is correct).

The heavy CosyVoice2-0.5B model is held by a persistent server
(cosyvoice_server.py); this bridge is stdlib-only and just POSTs the text,
receives WAV, and transcodes to MP3 via ffmpeg at output_path.

Usage: ``cosyvoice_say.py <input_path> <output_path> [api_base]`` — the optional
third arg overrides COSYVOICE_API, so Windows cmd (hermes tts_tool runs command
providers via cmd, no bash/env syntax) can point at the LAN center directly.

Env:
    COSYVOICE_API   default http://127.0.0.1:8003
"""
import json
import os
import subprocess
import sys
import urllib.request

API = os.environ.get("COSYVOICE_API", "http://127.0.0.1:8003").rstrip("/")

# LAN-direct: a local proxy (e.g. 127.0.0.1:10808) would hijack center-bound
# requests — ignore proxy env entirely.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: cosyvoice_say.py <input_text_path> <output_audio_path> [api_base]", file=sys.stderr)
        return 2
    in_path, out_path = sys.argv[1], sys.argv[2]
    api = (sys.argv[3].rstrip("/") if len(sys.argv) > 3 else API)
    with open(in_path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return 0
    # CosyVoice3 vocoder needs a minimum input length — very short text ("好的。")
    # crashes token2wav with "Kernel size can't be greater than actual input size".
    # Pad with a trailing clause; the extra period only adds a brief pause.
    if len(text) < 6:
        text = text + "。。"

    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{api}/tts",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with _OPENER.open(req, timeout=180) as resp:
        wav = resp.read()
    if not wav:
        print("CosyVoice returned empty audio", file=sys.stderr)
        return 1

    # CosyVoice returns WAV; transcode to MP3 at output_path so the HUD plays it
    # as audio/mpeg. ffmpeg reads WAV from stdin, writes MP3 to the exact path.
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-q:a", "4", out_path],
        input=wav,
    )
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
