"""Contract guardrail: assert the verified tool-integration contract so the
migration stays honest. If any of these break, the registration shape, the
toolset-enablement path, or the OpenAI function-schema layering changed.

Reflects current reality (see decisions/0007): the only live voice_hud tool is
``end_session``. play_music / stop_music were removed entirely — music plays in a
real browser via the agent's play-music skill (gequbao), not in-webview, so the
HUD/gateway no longer exposes music tools at all.

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
    """registry.dispatch must reach the handler with (args, **kw); the handler
    marks the turn-scoped end flag (the {text,end} boundary, decisions/0007)."""
    import dev_server  # noqa: F401  (import installs registration + end-flag wiring)
    import voice_hud_tools
    from tools.registry import registry

    marked = []
    real = voice_hud_tools._end_flag
    voice_hud_tools.set_end_flag(lambda: marked.append(True))
    try:
        out = registry.dispatch("end_session", {}, task_id="t1")
        assert marked == [True]
        assert "会话结束" in out
    finally:
        voice_hud_tools.set_end_flag(real)
