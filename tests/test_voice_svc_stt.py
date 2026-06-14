"""Phase 5 STT engine (voice_svc_stt) — migrated off hermes, faster-whisper local.

Pure-function tests (no GPU): hallucination filter + name normalization +
backend dispatch + the filter/normalize wiring around a stubbed model.
The faster-whisper call is the monkeypatch seam ``_transcribe_local``.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "hud-app"))

import voice_svc_stt


def test_hallucination_chinese_phrase_filtered():
    assert voice_svc_stt.is_whisper_hallucination("谢谢观看") is True
    assert voice_svc_stt.is_whisper_hallucination("贾维斯你好") is False


def test_hallucination_repeat_regex():
    assert voice_svc_stt.is_whisper_hallucination("Thank you. Thank you.") is True


def test_normalize_names_real_aliases():
    assert voice_svc_stt._normalize_names("Jarvis 你好") == "贾维斯 你好"
    assert voice_svc_stt._normalize_names("夏威士在吗") == "贾维斯在吗"
    # the rest of the real alias set (whisper_api.py:30) also normalizes
    assert voice_svc_stt._normalize_names("佳维斯") == "贾维斯"
    assert voice_svc_stt._normalize_names("加维斯") == "贾维斯"


def test_transcribe_baidu_backend_not_implemented():
    with pytest.raises(NotImplementedError):
        voice_svc_stt.transcribe("/tmp/whatever.webm", backend="baidu")


def test_transcribe_filters_hallucination(monkeypatch):
    monkeypatch.setattr(voice_svc_stt, "_transcribe_local", lambda path: "谢谢观看")
    assert voice_svc_stt.transcribe("/tmp/x.webm") == ""


def test_transcribe_normalizes_real_text(monkeypatch):
    monkeypatch.setattr(voice_svc_stt, "_transcribe_local", lambda path: "夏威士 帮我开灯")
    assert voice_svc_stt.transcribe("/tmp/x.webm") == "贾维斯 帮我开灯"
