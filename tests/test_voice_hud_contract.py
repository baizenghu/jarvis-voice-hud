"""Task 0.2 contract guardrail: assert the verified tool-integration contract
so Phase 1 stays honest. If any of these break, the registration shape, the
toolset-enablement path, or the OpenAI function-schema layering changed.

Proves:
- importing dev_server registers the voice_hud tools,
- dev_server._enabled_toolsets_for_session() includes "voice_hud",
- play_music reaches get_tool_definitions output (i.e. the agent would see it),
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
    assert "play_music" in names
    assert "stop_music" in names
    assert "end_session" in names

    fn = next(d["function"] for d in defs if d["function"]["name"] == "play_music")
    # OpenAI function-call shape: {"type":"function","function":{name,description,parameters}}
    assert "parameters" in fn
    assert fn["parameters"]["type"] == "object"
    assert fn["parameters"]["properties"]["query"]["type"] == "string"
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
        out = registry.dispatch("play_music", {"query": "七里香"}, task_id="t1")
        assert events == [{"type": "play_music", "query": "七里香"}]
        assert "七里香" in out
    finally:
        # restore the real broadcast (dev_server injected _safe_emit at import)
        voice_hud_tools.set_broadcast(dev_server._safe_emit)
