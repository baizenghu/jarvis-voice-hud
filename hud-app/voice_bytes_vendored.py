"""Byte-oriented STT/TTS adapters for the voice HUD.

The HUD captures and plays audio in the browser (see
docs/plantree/plans/jarvis-voice-hud/decisions/0001-audio-capture-location.md),
so the server never touches a microphone. These two functions take/return raw
audio bytes and delegate to hermes' existing engines via a temp file, leaving
tools/transcription_tools.py and tools/tts_tool.py untouched.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Tuple

from tools.tts_tool import text_to_speech_tool
from tools.tts_sanitize import sanitize_for_speech
from tools.voice_mode import transcribe_recording

logger = logging.getLogger(__name__)

# Browser MediaRecorder MIME types → file extension the STT pipeline accepts.
# Extensions must be in tools.transcription_tools.SUPPORTED_FORMATS.
_MIME_TO_SUFFIX = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
}


def transcribe_bytes(audio: bytes, mime: str) -> str:
    """Transcribe raw audio bytes via the existing STT pipeline; return text.

    Returns ``""`` when there is no audio, when STT failed, or when the turn
    was empty / a filtered Whisper hallucination.
    """
    if not audio:
        return ""

    suffix = _MIME_TO_SUFFIX.get((mime or "").split(";")[0].strip(), ".webm")

    fd, path = tempfile.mkstemp(suffix=suffix, prefix="hermes_stt_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        try:
            result = transcribe_recording(path)
        except Exception as e:
            logger.warning("transcribe_bytes: STT failed: %s", e)
            return ""
    finally:
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except OSError:
            pass

    if not result.get("success"):
        return ""
    return (result.get("transcript") or "").strip()


def synthesize_bytes(text: str) -> Tuple[bytes, str]:
    """Synthesize ``text`` with the configured TTS provider; return (bytes, mime).

    Returns ``(b"", "")`` for empty text or on synthesis failure — the caller
    falls back to showing the reply as text only.
    """
    if not text or not text.strip():
        return b"", ""

    # Strip markdown/URLs before TTS (decisions/0007 phase 2): the agent's raw
    # reply must not be read aloud with markup. Re-check empty — a reply that is
    # nothing but markup sanitizes away → skip synthesis (caller shows text).
    text = sanitize_for_speech(text)
    if not text:
        return b"", ""

    fd, mp3_path = tempfile.mkstemp(suffix=".mp3", prefix="synth_")
    os.close(fd)  # the TTS engine writes to this path itself

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
