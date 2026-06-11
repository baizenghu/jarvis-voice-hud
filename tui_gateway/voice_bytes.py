"""Byte-oriented STT/TTS adapters for the voice HUD.

The HUD captures and plays audio in the browser (see
docs/plantree/plans/jarvis-voice-hud/decisions/0001-audio-capture-location.md),
so the server never touches a microphone. These two functions take/return raw
audio bytes and delegate to hermes' existing engines via a temp file, leaving
tools/transcription_tools.py and tools/tts_tool.py untouched.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Tuple

from tools.tts_tool import text_to_speech_tool
from tools.voice_mode import transcribe_recording

logger = logging.getLogger(__name__)


def synthesize_bytes(text: str) -> Tuple[bytes, str]:
    """Synthesize ``text`` with the configured TTS provider; return (bytes, mime).

    Returns ``(b"", "")`` for empty text or on synthesis failure — the caller
    falls back to showing the reply as text only.
    """
    if not text or not text.strip():
        return b"", ""

    tmp_dir = os.path.join(tempfile.gettempdir(), "hermes_voice")
    os.makedirs(tmp_dir, exist_ok=True)
    mp3_path = os.path.join(tmp_dir, f"synth_{os.getpid()}_{id(text)}.mp3")

    try:
        text_to_speech_tool(text=text, output_path=mp3_path)
    except Exception as e:
        logger.warning("synthesize_bytes: TTS failed: %s", e)
        return b"", ""

    # text_to_speech_tool may emit .ogg for messaging platforms; prefer the
    # explicit .mp3 we asked for, fall back to a sibling .ogg.
    ogg_path = mp3_path[:-4] + ".ogg"
    audio = b""
    mime = ""
    try:
        if os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0:
            with open(mp3_path, "rb") as f:
                audio = f.read()
            mime = "audio/mpeg"
        elif os.path.isfile(ogg_path) and os.path.getsize(ogg_path) > 0:
            with open(ogg_path, "rb") as f:
                audio = f.read()
            mime = "audio/ogg"
    finally:
        for p in (mp3_path, ogg_path):
            try:
                if os.path.isfile(p):
                    os.unlink(p)
            except OSError:
                pass

    return audio, mime
