"""voice_hud toolset: the gateway agent calls end_session to end the voice
session. Per decisions/0007 the boundary is "agent → {text, end}": end_session
marks a turn-scoped flag (injected by dev_server) so the turn's message.complete
carries payload.end=True. The agent still narrates its own reply (the text);
this tool only signals "end".

play_music / stop_music были retired (music plays in a real external browser via
the play-music skill, not in-webview) and removed with the {text,end} migration.

registry.dispatch calls ``handler(args, **kwargs)`` (it may pass task_id etc.),
so the handler accepts ``(args, **kw)``.
"""
from typing import Callable

_end_flag: Callable[[], None] = lambda: None  # injected by dev_server (mark turn ended)


def set_end_flag(fn: Callable[[], None]) -> None:
    global _end_flag
    _end_flag = fn


def end_session_handler(args: dict, **kw) -> str:
    _end_flag()  # mark this turn's session ended → message.complete gets end=True
    return "会话结束"
