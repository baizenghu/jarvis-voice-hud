"""Baidu Cloud STT backend (decisions/0007: STT is a swappable central service).

Opt-in via STT_BACKEND=baidu. Needs BAIDU_STT_API_KEY + BAIDU_STT_SECRET_KEY.
Transcodes any MediaRecorder audio → 16k mono 16-bit PCM (ffmpeg), then calls
Baidu short-speech ASR. Tests mock ffmpeg + HTTP (no real network/binary).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import baidu_stt


def _mock_io(monkeypatch, *, pcm=b"PCMDATA", token_resp=None, asr_resp=None):
    monkeypatch.setattr(baidu_stt, "_run_ffmpeg", lambda audio: pcm)
    monkeypatch.setattr(
        baidu_stt, "_http_post_form",
        lambda url, data: token_resp if token_resp is not None
        else {"access_token": "tok", "expires_in": 2592000},
    )
    monkeypatch.setattr(baidu_stt, "_http_post_json", lambda url, payload: asr_resp)
    monkeypatch.setenv("BAIDU_STT_API_KEY", "ak")
    monkeypatch.setenv("BAIDU_STT_SECRET_KEY", "sk")
    baidu_stt._token_cache.update(token="", exp=0.0)  # reset cache between tests


def test_transcribe_returns_text(monkeypatch):
    _mock_io(monkeypatch, asr_resp={"err_no": 0, "result": ["你好世界"]})
    assert baidu_stt.transcribe_baidu(b"webm-bytes", "audio/webm") == "你好世界"


def test_empty_audio_returns_empty(monkeypatch):
    _mock_io(monkeypatch, asr_resp={"err_no": 0, "result": ["x"]})
    assert baidu_stt.transcribe_baidu(b"", "audio/webm") == ""


def test_asr_error_returns_empty(monkeypatch):
    # err_no != 0 (e.g. 3301 audio quality / no speech) → empty, not an exception
    _mock_io(monkeypatch, asr_resp={"err_no": 3301, "err_msg": "audio quality"})
    assert baidu_stt.transcribe_baidu(b"webm", "audio/webm") == ""


def test_result_stripped(monkeypatch):
    _mock_io(monkeypatch, asr_resp={"err_no": 0, "result": ["  带空格  "]})
    assert baidu_stt.transcribe_baidu(b"webm", "audio/webm") == "带空格"


def test_token_cached_across_calls(monkeypatch):
    calls = []
    _mock_io(monkeypatch, asr_resp={"err_no": 0, "result": ["a"]})
    monkeypatch.setattr(
        baidu_stt, "_http_post_form",
        lambda url, data: calls.append(1) or {"access_token": "tok", "expires_in": 2592000},
    )
    baidu_stt.transcribe_baidu(b"x", "audio/webm")
    baidu_stt.transcribe_baidu(b"y", "audio/webm")
    assert len(calls) == 1  # token fetched once, then cached


def test_transport_error_returns_empty(monkeypatch):
    # A network blip mid-conversation → graceful "" (not a hard error), like whisper.
    import urllib.error
    _mock_io(monkeypatch, asr_resp={"err_no": 0, "result": ["x"]})

    def boom(url, payload):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(baidu_stt, "_http_post_json", boom)
    assert baidu_stt.transcribe_baidu(b"webm", "audio/webm") == ""


def test_ffmpeg_decode_failure_returns_empty(monkeypatch):
    # Undecodable chunk (ffmpeg returns b"") → "" (no speech), not an exception.
    _mock_io(monkeypatch, pcm=b"", asr_resp={"err_no": 0, "result": ["x"]})
    assert baidu_stt.transcribe_baidu(b"garbage", "audio/webm") == ""


def test_missing_creds_raises(monkeypatch):
    monkeypatch.setattr(baidu_stt, "_run_ffmpeg", lambda audio: b"PCM")
    monkeypatch.delenv("BAIDU_STT_API_KEY", raising=False)
    monkeypatch.delenv("BAIDU_STT_SECRET_KEY", raising=False)
    baidu_stt._token_cache.update(token="", exp=0.0)
    with pytest.raises(RuntimeError, match="BAIDU_STT"):
        baidu_stt.transcribe_baidu(b"x", "audio/webm")
