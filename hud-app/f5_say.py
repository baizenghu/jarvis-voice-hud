#!/usr/bin/env python3
"""hermes command-type TTS provider bridge to a local F5-TTS API server.

hermes runs this as: ``f5_say.py <input_path> <output_path>`` where
``input_path`` holds the text to speak and ``output_path`` is where the audio
must be written (we write MP3 so the HUD's audio/mpeg labelling is correct).

F5-TTS is zero-shot voice cloning: it needs a reference clip + its transcript.
Both are configurable via env so the "Jarvis voice" can be swapped without
editing this file:

    F5_API        default http://127.0.0.1:8002
    F5_REF_AUDIO  default the bundled Chinese sample (basic_ref_zh.wav)
    F5_REF_TEXT   transcript of F5_REF_AUDIO
    F5_NFE_STEP   diffusion steps (lower = faster, default 32)
"""
import base64
import os
import subprocess
import sys
import urllib.request
import uuid

F5_API = os.environ.get("F5_API", "http://127.0.0.1:8002").rstrip("/")
REF_AUDIO = os.environ.get(
    "F5_REF_AUDIO",
    "/home/baizh/F5-TTS/src/f5_tts/infer/examples/basic/basic_ref_zh.wav",
)
REF_TEXT = os.environ.get("F5_REF_TEXT", "对，这就是我，万人敬仰的太乙真人。")
NFE_STEP = os.environ.get("F5_NFE_STEP", "32")


def _multipart(fields: dict, file_field: str, file_path: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    nl = b"\r\n"
    body = b""
    for k, v in fields.items():
        body += b"--" + boundary.encode() + nl
        body += f'Content-Disposition: form-data; name="{k}"'.encode() + nl + nl
        body += str(v).encode() + nl
    with open(file_path, "rb") as f:
        data = f.read()
    body += b"--" + boundary.encode() + nl
    body += (
        f'Content-Disposition: form-data; name="{file_field}"; '
        f'filename="ref.wav"'.encode() + nl
    )
    body += b"Content-Type: audio/wav" + nl + nl + data + nl
    body += b"--" + boundary.encode() + b"--" + nl
    return body, boundary


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: f5_say.py <input_text_path> <output_audio_path>", file=sys.stderr)
        return 2
    in_path, out_path = sys.argv[1], sys.argv[2]
    with open(in_path, "r", encoding="utf-8") as f:
        gen_text = f.read().strip()
    if not gen_text:
        return 0

    body, boundary = _multipart(
        {"ref_text": REF_TEXT, "gen_text": gen_text, "nfe_step": NFE_STEP},
        "ref_audio",
        REF_AUDIO,
    )
    req = urllib.request.Request(
        f"{F5_API}/api/v1/tts",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        import json

        result = json.load(resp)
    if not result.get("success") or not result.get("audio_base64"):
        print(f"F5 TTS failed: {result.get('message')}", file=sys.stderr)
        return 1
    wav = base64.b64decode(result["audio_base64"])

    # F5 returns WAV; transcode to MP3 at output_path so the HUD plays it as
    # audio/mpeg. ffmpeg reads WAV from stdin, writes MP3 to the exact path.
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-q:a", "4", out_path],
        input=wav,
    )
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
