#!/usr/bin/env python3
"""hermes command-type TTS provider bridge to the local VoxCPM2 server.

hermes runs this as: ``voxcpm_say.py <input_path> <output_path>`` where
``input_path`` holds the text to speak and ``output_path`` is where the audio
must be written (we write MP3 so the HUD's audio/mpeg labelling is correct).

The heavy VoxCPM2 model is held by a persistent server (voxcpm_server.py);
this bridge is stdlib-only and just POSTs the text, receives WAV, and
transcodes to MP3 via ffmpeg at output_path.

Env:
    VOXCPM_API   default http://127.0.0.1:8005
"""
import json
import os
import subprocess
import sys
import urllib.request

API = os.environ.get("VOXCPM_API", "http://127.0.0.1:8005").rstrip("/")


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: voxcpm_say.py <input_text_path> <output_audio_path>", file=sys.stderr)
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
        print("VoxCPM returned empty audio", file=sys.stderr)
        return 1

    # VoxCPM returns WAV; transcode to MP3 at output_path so the HUD plays it
    # as audio/mpeg. ffmpeg reads WAV from stdin, writes MP3 to the exact path.
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-q:a", "4", out_path],
        input=wav,
    )
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
