"""Phase 3 (decisions/0007): hermes adapter — end flag on message.complete.

The agent ends a voice session by calling its end_session tool, which marks a
turn-scoped flag keyed by the current session key (hermes' existing
tools.approval session-key contextvar — the same one terminal_tool reads).
dev_server wraps server._emit so that message.complete for a session whose turn
was marked carries payload.end=True, then clears the mark. Keyed by session key
→ turn-scoped, no cross-session bleed. The old out-of-band {type:end_session}
broadcast was removed in the contract step — end_session now marks only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hud-app"))

import tui_gateway.server as server  # noqa: E402
import dev_server  # noqa: E402  (import installs the _emit wrapper + injects set_end_flag)
from tools.approval import set_current_session_key, reset_current_session_key  # noqa: E402


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(server, "write_json", lambda m: sent.append(m))
    return sent


def test_end_flag_adds_end_to_message_complete(monkeypatch):
    sent = _capture(monkeypatch)
    tok = set_current_session_key("sk1")
    try:
        dev_server._mark_end()  # simulate the end_session tool firing this turn
        server._emit("message.complete", "sid1", {"text": "好,再见"})
    finally:
        reset_current_session_key(tok)
    payload = sent[-1]["params"]["payload"]
    assert payload["end"] is True
    assert payload["text"] == "好,再见"  # other fields untouched


def test_no_mark_means_no_end(monkeypatch):
    sent = _capture(monkeypatch)
    tok = set_current_session_key("sk1")
    try:
        server._emit("message.complete", "sid1", {"text": "在的"})
    finally:
        reset_current_session_key(tok)
    assert not sent[-1]["params"]["payload"].get("end")


def test_flag_cleared_after_emit(monkeypatch):
    sent = _capture(monkeypatch)
    tok = set_current_session_key("sk1")
    try:
        dev_server._mark_end()
        server._emit("message.complete", "sid1", {"text": "再见"})
        server._emit("message.complete", "sid1", {"text": "下一轮"})
    finally:
        reset_current_session_key(tok)
    assert sent[-2]["params"]["payload"]["end"] is True
    assert not sent[-1]["params"]["payload"].get("end")  # not residual


def test_flag_keyed_by_session_no_crosstalk(monkeypatch):
    sent = _capture(monkeypatch)
    tok1 = set_current_session_key("skA")
    try:
        dev_server._mark_end()  # mark session A
    finally:
        reset_current_session_key(tok1)
    tok2 = set_current_session_key("skB")
    try:
        server._emit("message.complete", "sidB", {"text": "B 的回复"})  # session B
    finally:
        reset_current_session_key(tok2)
    assert not sent[-1]["params"]["payload"].get("end")  # B must not inherit A's end


def test_other_events_pass_through_untouched(monkeypatch):
    sent = _capture(monkeypatch)
    tok = set_current_session_key("sk1")
    try:
        dev_server._mark_end()
        server._emit("message.delta", "sid1", {"text": "片段"})  # not message.complete
    finally:
        reset_current_session_key(tok)
    assert "end" not in sent[-1]["params"]["payload"]


def test_end_session_handler_marks_flag_only(monkeypatch):
    """After the contract step (decisions/0007 step D): end_session_handler ONLY
    marks the flag — the old out-of-band broadcast is gone."""
    import voice_hud_tools

    marked = []
    monkeypatch.setattr(voice_hud_tools, "_end_flag", lambda: marked.append(True))

    out = voice_hud_tools.end_session_handler({})

    assert marked == [True]
    assert "会话结束" in out
    assert not hasattr(voice_hud_tools, "_broadcast")  # broadcast path removed
