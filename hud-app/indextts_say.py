#!/usr/bin/env python3
"""hermes command-type TTS provider bridge to the local IndexTTS-2 server.

hermes runs this as: ``indextts_say.py <input_path> <output_path>`` where
``input_path`` holds the text to speak and ``output_path`` is where the audio
must be written (we write MP3 so the HUD's audio/mpeg labelling is correct).

The heavy IndexTTS-2 model is held by a persistent server (indextts_server.py);
this bridge is stdlib-only and just POSTs the text, receives WAV, and transcodes
to MP3 via ffmpeg at output_path.

Env:
    INDEXTTS_API   default http://127.0.0.1:8004
"""
import json
import os
import subprocess
import sys
import urllib.request

API = os.environ.get("INDEXTTS_API", "http://127.0.0.1:8004").rstrip("/")


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: indextts_say.py <input_text_path> <output_audio_path>", file=sys.stderr)
        return 2
    in_path, out_path = sys.argv[1], sys.argv[2]
    with open(in_path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return 0

    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/tts",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        wav = resp.read()
    if not wav:
        print("IndexTTS returned empty audio", file=sys.stderr)
        return 1

    # IndexTTS returns WAV; transcode to MP3 at output_path so the HUD plays it
    # as audio/mpeg. ffmpeg reads WAV from stdin, writes MP3 to the exact path.
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-q:a", "4", out_path],
        input=wav,
    )
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
