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


import base64
import tui_gateway.server as server


def test_rpc_voice_synthesize_returns_base64(monkeypatch):
    # Handlers import from tui_gateway.voice_bytes at call time, so patch the
    # name on the voice_bytes module (NOT on server).
    monkeypatch.setattr(vb, "synthesize_bytes", lambda text: (b"AUDIO", "audio/mpeg"))
    resp = server.dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "voice.synthesize", "params": {"text": "hi"}},
        None,
    )
    assert resp["result"]["mime"] == "audio/mpeg"
    assert base64.b64decode(resp["result"]["audio"]) == b"AUDIO"


def test_rpc_voice_synthesize_requires_text():
    resp = server.dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": "voice.synthesize", "params": {"text": ""}},
        None,
    )
    assert "error" in resp


def test_rpc_voice_transcribe_returns_text(monkeypatch):
    monkeypatch.setattr(vb, "transcribe_bytes", lambda audio, mime: "hello")
    resp = server.dispatch(
        {
            "jsonrpc": "2.0", "id": 3, "method": "voice.transcribe",
            "params": {"audio": base64.b64encode(b"x").decode(), "mime": "audio/webm"},
        },
        None,
    )
    assert resp["result"]["text"] == "hello"
