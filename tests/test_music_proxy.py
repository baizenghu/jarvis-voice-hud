"""/api/music gateway proxy (Phase 4 M1): query -> yt-dlp stream URL -> same-origin
proxy so the HUD's <audio> stays same-origin and the analyser can read it
(cross-origin would taint the analyser -> silent visualizer). Tests cover the
deterministic error branches; the happy-path byte proxy is verified live by the
M1 acceptance curl (needs network + yt-dlp)."""
import importlib.util
import sys
from pathlib import Path

from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "hud-app"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "dev_server", Path(__file__).parent.parent / "hud-app" / "dev_server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_missing_query_is_400():
    ds = _load()
    with TestClient(ds.app) as client:
        r = client.get("/api/music")
        assert r.status_code == 400
        assert r.json()["ok"] is False


def test_blank_query_is_400():
    ds = _load()
    with TestClient(ds.app) as client:
        r = client.get("/api/music", params={"q": "   "})
        assert r.status_code == 400


def test_resolve_failure_is_502(monkeypatch):
    ds = _load()

    async def _fail(query):
        return None

    monkeypatch.setattr(ds, "_resolve_stream_url", _fail)
    with TestClient(ds.app) as client:
        r = client.get("/api/music", params={"q": "nonexistent song xyz"})
        assert r.status_code == 502
        assert r.json()["ok"] is False
