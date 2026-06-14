"""Phase 1 (decisions/0007 migration) inbound auth gate.

The voice gateway (hud-app/dev_server.py) runs the agent in YOLO mode with the
terminal toolset. Binding a non-loopback HOST (WireGuard/LAN) exposes the
JSON-RPC + /api/* command surface to the whole network = an unauthenticated
shell. This guards it: loopback stays open (default behavior unchanged), any
non-loopback bind REQUIRES a shared token (fail closed).

The auth decision is LIVE (re-reads HOST/JARVIS_GATEWAY_TOKEN each call), so it
is not frozen at import and a startup hook enforces it under any ASGI entrypoint
(not just `python dev_server.py`). Residual: the app trusts the HOST env as the
declared bind; it cannot see a uvicorn `--host` CLI flag.
"""
import sys
from pathlib import Path

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "hud-app"))


# --- pure predicates ------------------------------------------------------

def test_auth_not_required_for_loopback():
    import dev_server
    assert dev_server._auth_required("127.0.0.1") is False
    assert dev_server._auth_required("localhost") is False
    assert dev_server._auth_required("::1") is False


def test_auth_required_for_non_loopback():
    import dev_server
    assert dev_server._auth_required("10.8.0.2") is True
    assert dev_server._auth_required("0.0.0.0") is True
    assert dev_server._auth_required("192.168.0.7") is True


def test_token_ok_matches_env(monkeypatch):
    import dev_server
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    assert dev_server._token_ok("s3cret") is True
    assert dev_server._token_ok("nope") is False
    assert dev_server._token_ok(None) is False


def test_token_ok_false_when_env_unset(monkeypatch):
    import dev_server
    monkeypatch.delenv("JARVIS_GATEWAY_TOKEN", raising=False)
    assert dev_server._token_ok("anything") is False


def test_token_ok_non_ascii_is_false_not_error(monkeypatch):
    """A non-ASCII token must fail cleanly (False), not raise TypeError → 500."""
    import dev_server
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    assert dev_server._token_ok("café☕") is False


# --- live auth decision (env-driven, not frozen at import) ----------------

def test_authorized_passes_through_on_loopback(monkeypatch):
    import dev_server
    monkeypatch.setenv("HOST", "127.0.0.1")
    assert dev_server._authorized(None) is True
    assert dev_server._authorized("whatever") is True


def test_authorized_enforces_token_on_non_loopback(monkeypatch):
    import dev_server
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    assert dev_server._authorized("s3cret") is True
    assert dev_server._authorized("bad") is False
    assert dev_server._authorized(None) is False


# --- fail closed ----------------------------------------------------------

def test_fail_closed_non_loopback_without_token(monkeypatch):
    import dev_server
    monkeypatch.delenv("JARVIS_GATEWAY_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        dev_server._enforce_fail_closed("10.8.0.2")


def test_fail_closed_allows_loopback_without_token(monkeypatch):
    import dev_server
    monkeypatch.delenv("JARVIS_GATEWAY_TOKEN", raising=False)
    dev_server._enforce_fail_closed("127.0.0.1")  # must not raise


def test_fail_closed_allows_non_loopback_with_token(monkeypatch):
    import dev_server
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    dev_server._enforce_fail_closed("10.8.0.2")  # must not raise


def test_startup_hook_fails_closed_under_any_entrypoint(monkeypatch):
    """Fail-closed must fire on app startup (the startup hook), not only in
    __main__, so launching via an external ASGI server is also guarded
    (Finding 1). Test the startup coroutine directly: TestClient swallows a
    SystemExit raised during lifespan into async-shutdown logging."""
    import asyncio
    import dev_server
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.delenv("JARVIS_GATEWAY_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        asyncio.run(dev_server._on_startup())


# --- integration: HTTP /api/* surface -------------------------------------

def _client():
    import dev_server
    # un-entered client: requests work without firing lifespan/startup events
    return dev_server, TestClient(dev_server.app)


def test_http_api_open_on_loopback(monkeypatch):
    """Default (loopback) behavior unchanged: no token, /api/* still serves."""
    dev_server, client = _client()
    monkeypatch.setenv("HOST", "127.0.0.1")
    assert client.post("/api/wake").status_code == 200


def test_http_api_rejects_without_token_when_required(monkeypatch):
    dev_server, client = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    assert client.post("/api/wake").status_code == 401


def test_http_api_accepts_correct_token_when_required(monkeypatch):
    dev_server, client = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    assert client.post("/api/wake?token=s3cret").status_code == 200


def test_http_api_rejects_wrong_token_when_required(monkeypatch):
    dev_server, client = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    assert client.post("/api/wake?token=wrong").status_code == 401


# --- integration: WebSocket surface (middleware does NOT cover WS) ---------

def test_ws_rpc_rejects_without_token_when_required(monkeypatch):
    dev_server, client = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws"):
            pass


def test_ws_events_rejects_without_token_when_required(monkeypatch):
    dev_server, client = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/events"):
            pass


def test_ws_events_accepts_with_correct_token(monkeypatch):
    dev_server, client = _client()
    monkeypatch.setenv("HOST", "10.8.0.2")
    monkeypatch.setenv("JARVIS_GATEWAY_TOKEN", "s3cret")
    # entering the context means the guard let it through and the socket accepted
    with client.websocket_connect("/api/events?token=s3cret") as ws:
        ws.close()
