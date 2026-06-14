"""Contract guardrail: assert the verified tool-integration contract so the
migration stays honest. If any of these break, the registration shape, the
toolset-enablement path, or the OpenAI function-schema layering changed.

Reflects current reality (see decisions/0007): play_music / stop_music are
RETIRED (music plays in a real browser via the play-music skill, not in-webview;
dev_server.py only registers end_session). The live voice_hud tool is
``end_session``. The play_music/stop_music handlers still exist in
voice_hud_tools.py but are never registered, so the agent does not see them.

Proves:
- importing dev_server registers the voice_hud tools,
- dev_server._enabled_toolsets_for_session() includes "voice_hud",
- end_session reaches get_tool_definitions output (i.e. the agent would see it),
  while the retired play_music / stop_music do NOT,
- the schema lands under function.parameters with the right structure
  (NOT flattened onto function top-level — bare JSON Schema would break this).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hud-app"))


def test_register_and_definition_shape():
    import dev_server  # import triggers _register_voice_hud_tools()
    from model_tools import get_tool_definitions

    enabled = dev_server._enabled_toolsets_for_session()
    # voice_hud must be in the session's enabled toolsets (None == all toolsets,
    # which also includes the registry-registered voice_hud plugin toolset).
    if enabled is not None:
        assert "voice_hud" in enabled

    defs = get_tool_definitions(enabled_toolsets=enabled)
    names = [d["function"]["name"] for d in defs]
    assert "end_session" in names
    # play_music / stop_music are RETIRED — the agent must NOT see them.
    assert "play_music" not in names
    assert "stop_music" not in names

    fn = next(d["function"] for d in defs if d["function"]["name"] == "end_session")
    # OpenAI function-call shape: {"type":"function","function":{name,description,parameters}}
    assert "parameters" in fn
    assert fn["parameters"]["type"] == "object"
    # end_session takes no args: a properties object that is present but empty.
    assert fn["parameters"]["properties"] == {}
    assert fn["description"]


def test_dispatch_routes_to_handler():
    """registry.dispatch must reach the handler with (args, **kw) and the
    handler must broadcast through the injected callback."""
    import dev_server
    import voice_hud_tools
    from tools.registry import registry

    events = []
    voice_hud_tools.set_broadcast(lambda e: events.append(e))
    try:
        out = registry.dispatch("end_session", {}, task_id="t1")
        assert events == [{"type": "end_session"}]
        assert "会话结束" in out
    finally:
        # restore the real broadcast (dev_server injected _safe_emit at import)
        voice_hud_tools.set_broadcast(dev_server._safe_emit)
