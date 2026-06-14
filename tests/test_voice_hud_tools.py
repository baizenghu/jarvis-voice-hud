"""voice_hud toolset: only end_session remains (decisions/0007). It marks a
turn-scoped end flag (via an injected callback) and returns a confirmation
string for the agent. play_music / stop_music were retired with the {text,end}
migration. The flag→message.complete wiring lives in dev_server and is covered
by tests/test_voice_hud_end_flag.py."""
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


def test_end_session_marks_flag_and_returns_confirmation():
    m = _load()
    marked = []
    m.set_end_flag(lambda: marked.append(True))
    out = m.end_session_handler({})
    assert marked == [True]
    assert "会话结束" in out


def test_end_session_does_not_broadcast_anymore():
    """The retired out-of-band broadcast is gone — voice_hud_tools no longer has
    a broadcast injection point at all."""
    m = _load()
    assert not hasattr(m, "set_broadcast")
    assert not hasattr(m, "play_music_handler")
    assert not hasattr(m, "stop_music_handler")


def test_handler_accepts_dispatch_kwargs():
    """registry.dispatch calls handler(args, **kwargs) with extra kw (task_id,
    etc.). The handler must accept them without TypeError."""
    m = _load()
    m.set_end_flag(lambda: None)
    m.end_session_handler({}, task_id="t1")
