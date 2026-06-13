"""WakeHub gating: wakes are suppressed while a dialog turn runs and during
the post-turn cooldown (TTS echo tail)."""
import importlib.util
import sys
from pathlib import Path

# dev_server pulls in the full gateway at import; load only what we need by
# importing the module file with its heavy deps stubbed out is overkill —
# instead re-import the module normally (deps are in the project venv).
sys.path.insert(0, str(Path(__file__).parent.parent / "hud-app"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "dev_server", Path(__file__).parent.parent / "hud-app" / "dev_server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_broadcast_emits_to_clients():
    ds = _load()
    hub = ds.WakeHub()
    sent = []

    class FakeWS:
        async def send_json(self, m):
            sent.append(m)

    hub.clients.add(FakeWS())
    import asyncio

    n = asyncio.run(hub.broadcast({"type": "play_music", "query": "晴天"}))
    assert sent[-1] == {"type": "play_music", "query": "晴天"}
    assert n == 1


def test_broadcast_drops_dead_clients():
    ds = _load()
    hub = ds.WakeHub()

    class GoodWS:
        async def send_json(self, m):
            pass

    class DeadWS:
        async def send_json(self, m):
            raise RuntimeError("closed")

    good = GoodWS()
    hub.clients.add(good)
    hub.clients.add(DeadWS())
    import asyncio

    n = asyncio.run(hub.broadcast({"type": "stop_music"}))
    assert n == 1
    assert hub.clients == {good}


def test_wake_gating():
    ds = _load()
    hub = ds.WakeHub()
    # fresh hub: idle_since=0, monotonic now is far past cooldown
    assert hub.accepts_wake(now=100.0)
    hub.set_busy(True, now=100.0)
    assert not hub.accepts_wake(now=100.5)
    hub.set_busy(False, now=101.0)
    # inside cooldown window
    assert not hub.accepts_wake(now=101.5)
    # past cooldown
    assert hub.accepts_wake(now=101.0 + ds.WAKE_COOLDOWN_S)
