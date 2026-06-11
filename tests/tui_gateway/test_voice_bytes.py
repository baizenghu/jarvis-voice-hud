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


def test_transcribe_bytes_returns_text_and_uses_mime_suffix(monkeypatch):
    seen = {}

    def fake_transcribe(path, model=None):
        # Capture the suffix so we can assert mime→extension mapping, and the
        # bytes so we know they were written to disk before transcription.
        seen["suffix"] = Path(path).suffix
        seen["bytes"] = Path(path).read_bytes()
        return {"success": True, "transcript": "  hello there  "}

    monkeypatch.setattr(vb, "transcribe_recording", fake_transcribe)

    text = vb.transcribe_bytes(b"fake-webm-bytes", "audio/webm")

    assert text == "hello there"          # stripped
    assert seen["suffix"] == ".webm"      # mime mapped to extension
    assert seen["bytes"] == b"fake-webm-bytes"


def test_transcribe_bytes_empty_transcript_returns_empty(monkeypatch):
    # A filtered/hallucinated turn comes back as success+empty transcript.
    monkeypatch.setattr(
        vb, "transcribe_recording",
        lambda path, model=None: {"success": True, "transcript": "", "filtered": True},
    )
    assert vb.transcribe_bytes(b"x", "audio/ogg") == ""


def test_transcribe_bytes_unknown_mime_defaults_to_webm(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        vb, "transcribe_recording",
        lambda path, model=None: seen.update(suffix=Path(path).suffix) or {"success": True, "transcript": "ok"},
    )
    vb.transcribe_bytes(b"x", "application/octet-stream")
    assert seen["suffix"] == ".webm"
