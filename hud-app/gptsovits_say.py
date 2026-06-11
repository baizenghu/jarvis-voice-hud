#!/usr/bin/env python3
"""hermes command-type TTS provider bridge to a local GPT-SoVITS api_v2 server.

hermes runs this as: ``gptsovits_say.py <input_path> <output_path>`` where
``input_path`` holds the text to speak and ``output_path`` is where the audio
must be written (we write MP3 so the HUD's audio/mpeg labelling is correct).

GPT-SoVITS is zero-shot voice cloning: it needs a reference clip + its
transcript (prompt_text) + their languages. All are configurable via env so
the voice can be swapped without editing this file:

    GPTSOVITS_API          default http://127.0.0.1:9880
    GPTSOVITS_REF_AUDIO    reference wav path (server-side absolute path)
    GPTSOVITS_PROMPT_TEXT  transcript of GPTSOVITS_REF_AUDIO
    GPTSOVITS_PROMPT_LANG  language of the prompt text (default "zh")
    GPTSOVITS_TEXT_LANG    language of the text to speak (default "zh")

The api_v2 POST /tts endpoint returns raw WAV audio bytes on success (HTTP
200) or a JSON error body (HTTP 400). We transcode the WAV to MP3 at
output_path via ffmpeg so the HUD plays it as audio/mpeg.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = os.environ.get("GPTSOVITS_API", "http://127.0.0.1:9880").rstrip("/")
REF_AUDIO = os.environ.get(
    "GPTSOVITS_REF_AUDIO",
    "/home/baizh/GPT-SoVITS/output/slicer_opt_yh/"
    "袁华.WAV_0000019200_0000244800.wav",
)
PROMPT_TEXT = os.environ.get(
    "GPTSOVITS_PROMPT_TEXT",
    "外露,外露，我作诗都是有批判性的，我试试吧啊。",
)
PROMPT_LANG = os.environ.get("GPTSOVITS_PROMPT_LANG", "zh")
TEXT_LANG = os.environ.get("GPTSOVITS_TEXT_LANG", "zh")


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: gptsovits_say.py <input_text_path> <output_audio_path>",
            file=sys.stderr,
        )
        return 2
    in_path, out_path = sys.argv[1], sys.argv[2]
    with open(in_path, "r", encoding="utf-8") as f:
        gen_text = f.read().strip()
    if not gen_text:
        return 0

    payload = {
        "text": gen_text,
        "text_lang": TEXT_LANG,
        "ref_audio_path": REF_AUDIO,
        "prompt_text": PROMPT_TEXT,
        "prompt_lang": PROMPT_LANG,
        "text_split_method": "cut5",
        "batch_size": 1,
        "media_type": "wav",
        "streaming_mode": False,
    }
    req = urllib.request.Request(
        f"{API}/tts",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            wav = resp.read()
    except urllib.error.HTTPError as e:
        # api_v2 returns a JSON error body on failure (HTTP 400).
        body = e.read().decode("utf-8", "replace")
        print(f"GPT-SoVITS TTS failed (HTTP {e.code}): {body}", file=sys.stderr)
        return 1

    if not wav:
        print("GPT-SoVITS TTS returned empty audio", file=sys.stderr)
        return 1

    # api_v2 returns WAV; transcode to MP3 at output_path so the HUD plays it
    # as audio/mpeg. ffmpeg reads WAV from stdin, writes MP3 to the exact path.
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-q:a", "4", out_path],
        input=wav,
    )
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
