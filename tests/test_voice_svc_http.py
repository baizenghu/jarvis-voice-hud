"""Phase 5 voice service HTTP layer (voice_svc) — contract + auth + CORS.

STT engine and TTS forward are monkeypatched to stubs (no GPU / no network).
Auth mirrors the phase 1 dev_server gate, but the service exposes BARE paths
(/transcribe /synthesize) not /api/* — so the middleware must guard those.
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "hud-app"))


def _client():
    import voice_svc
    # un-entered client: requests work without firing lifespan/startup events
    return voice_svc, TestClient(voice_svc.app)


@pytest.fixture(autouse=True)
def _loopback(monkeypatch):
    # default to loopback (auth off) unless a test overrides HOST
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.delenv("STT_BACKEND", raising=False)
    monkeypatch.delenv("TTS_BACKEND", raising=False)


# --- /health --------------------------------------------------------------

def test_health_shape(monkeypatch):
    voice_svc, client = _client()
    monkeypatch.setattr(voice_svc, "_tts_ready", lambda: False)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    for key in ("stt_backend", "tts_backend", "stt_ready", "tts_ready"):
        assert key in body


# --- /transcribe ----------------------------------------------------------

def test_transcribe_returns_text(monkeypatch):
    import voice_svc_stt
    voice_svc, client = _client()
    monkeypatch.setattr(voice_svc_stt, "transcribe", lambda path, backend="local": "你好")
    r = client.post("/transcribe", files={"file": ("a.webm", b"AUDIO", "audio/webm")})
    assert r.status_code == 200
    assert r.json() == {"text": "你好"}


def test_transcribe_baidu_501(monkeypatch):
    voice_svc, client = _client()
    r = client.post(
        "/transcribe",
        files={"file": ("a.webm", b"AUDIO", "audio/webm")},
        data={"backend": "baidu"},
    )
    assert r.status_code == 501
    assert "baidu" in r.json().get("error", "").lower()


# --- /synthesize ----------------------------------------------------------

def test_synthesize_returns_wav(monkeypatch):
    voice_svc, client = _client()
    monkeypatch.setattr(voice_svc, "_tts_forward", lambda text: b"WAVBYTES")
    r = client.post("/synthesize", json={"text": "好的"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert r.content == b"WAVBYTES"


def test_synthesize_empty_text_400(monkeypatch):
    voice_svc, client = _client()
    r = client.post("/synthesize", json={"text": ""})
    assert r.status_code == 400
    assert "text" in r.json().get("error", "").lower()


def test_synthesize_baidu_501(monkeypatch):
    voice_svc, client = _client()
    r = client.post("/synthesize", json={"text": "好的", "backend": "baidu"})
    assert r.status_code == 501
    assert "baidu" in r.json().get("error", "").lower()


# --- auth (bare paths, not /api/*) ----------------------------------------

def test_fail_closed_non_loopback_without_token(monkeypatch):
    voice_svc, _ = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.delenv("JARVIS_GATEWAY_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        voice_svc._enforce_fail_closed("10.8.0.2")
    with pytest.raises(SystemExit):
        asyncio.run(voice_svc._on_startup())


def test_transcribe_requires_token_on_non_loopback(monkeypatch):
    import voice_svc_stt
    voice_svc, client = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    monkeypatch.setattr(voice_svc_stt, "transcribe", lambda path, backend="local": "ok")
    files = {"file": ("a.webm", b"AUDIO", "audio/webm")}
    assert client.post("/transcribe", files=files).status_code == 401
    assert client.post("/transcribe?token=s3cret", files=files).status_code == 200


def test_loopback_no_token_allows(monkeypatch):
    import voice_svc_stt
    voice_svc, client = _client()
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.delenv("JARVIS_GATEWAY_TOKEN", raising=False)
    monkeypatch.setattr(voice_svc_stt, "transcribe", lambda path, backend="local": "ok")
    r = client.post("/transcribe", files={"file": ("a.webm", b"AUDIO", "audio/webm")})
    assert r.status_code == 200


def test_health_exempt_from_token(monkeypatch):
    voice_svc, client = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    monkeypatch.setattr(voice_svc, "_tts_ready", lambda: False)
    # health is a readiness probe — no token required even when exposed
    assert client.get("/health").status_code == 200


# --- CORS (Tauri origin, preflight not token-gated) -----------------------

def test_cors_preflight_allowed_without_token(monkeypatch):
    voice_svc, client = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    r = client.options(
        "/transcribe",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "tauri://localhost"
