"""voice_hud toolset handlers: each handler broadcasts the right action event
to the HUD (via an injected broadcast callback) and returns a confirmation
string for the agent."""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hud-app"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "voice_hud_tools", Path(__file__).parent.parent / "hud-app" / "voice_hud_tools.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_play_music_handler_broadcasts():
    m = _load()
    events = []
    m.set_broadcast(lambda e: events.append(e))
    out = m.play_music_handler({"query": "晴天"})
    assert events == [{"type": "play_music", "query": "晴天"}]
    assert "晴天" in out


def test_play_music_empty_query_means_popular():
    m = _load()
    events = []
    m.set_broadcast(lambda e: events.append(e))
    m.play_music_handler({})
    assert events == [{"type": "play_music", "query": ""}]


def test_stop_and_end_handlers_broadcast():
    m = _load()
    events = []
    m.set_broadcast(lambda e: events.append(e))
    m.stop_music_handler({})
    m.end_session_handler({})
    assert events == [{"type": "stop_music"}, {"type": "end_session"}]


def test_handlers_accept_dispatch_kwargs():
    """registry.dispatch calls handler(args, **kwargs) with extra kw (task_id,
    etc.). Handlers must accept them without TypeError."""
    m = _load()
    m.set_broadcast(lambda e: None)
    m.play_music_handler({"query": "x"}, task_id="t1")
    m.stop_music_handler({}, task_id="t1")
    m.end_session_handler({}, task_id="t1")
