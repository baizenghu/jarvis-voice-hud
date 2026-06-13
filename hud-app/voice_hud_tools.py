"""voice_hud toolset: the gateway agent calls these tools to drive the thin
HUD client (play / stop music, end the voice session).

Each handler is fire-and-forget: it pushes an action event to the HUD via an
injected broadcast callback, then returns a short confirmation string for the
agent (the agent still narrates its own reply, which the HUD speaks via TTS).
The broadcast callback is injected by dev_server at startup (set_broadcast);
in tests a synchronous stub is injected.

registry.dispatch calls ``handler(args, **kwargs)`` (it may pass task_id etc.),
so every handler accepts ``(args, **kw)``.
"""
from typing import Callable

_broadcast: Callable[[dict], None] = lambda e: None  # injected by dev_server


def set_broadcast(fn: Callable[[dict], None]) -> None:
    global _broadcast
    _broadcast = fn


def play_music_handler(args: dict, **kw) -> str:
    query = (args.get("query") or "").strip()
    _broadcast({"type": "play_music", "query": query})
    return f"已开始播放: {query or '热门音乐'}"


def stop_music_handler(args: dict, **kw) -> str:
    _broadcast({"type": "stop_music"})
    return "已停止"


def end_session_handler(args: dict, **kw) -> str:
    _broadcast({"type": "end_session"})
    return "会话结束"
