"""Unit tests for tui_gateway.voice_bytes — the STT/TTS byte adapters."""
import json
from pathlib import Path

import tui_gateway.voice_bytes as vb


def test_synthesize_bytes_reads_engine_output(monkeypatch, tmp_path):
    # Fake the TTS engine: write known bytes to the requested output_path,
    # return the JSON envelope the real text_to_speech_tool returns.
    def fake_tts(text, output_path=None):
        Path(output_path).write_bytes(b"ID3fake-mp3-bytes")
        return json.dumps({"success": True, "file_path": output_path})

    monkeypatch.setattr(vb, "text_to_speech_tool", fake_tts)

    audio, mime = vb.synthesize_bytes("hello world")

    assert audio == b"ID3fake-mp3-bytes"
    assert mime == "audio/mpeg"


def test_synthesize_bytes_empty_text_returns_empty(monkeypatch):
    # Empty text must not call the engine and must return no audio.
    called = False

    def fake_tts(text, output_path=None):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(vb, "text_to_speech_tool", fake_tts)

    audio, mime = vb.synthesize_bytes("   ")

    assert audio == b""
    assert called is False
