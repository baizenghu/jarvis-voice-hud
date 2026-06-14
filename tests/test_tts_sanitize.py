"""Phase 2 (decisions/0007): shared TTS text sanitizer.

Single source of truth extracted from hermes_cli.voice.speak_text's inline regex
block (which already shipped). Both speak_text and tui_gateway.voice_bytes
.synthesize_bytes (the HUD's voice.synthesize path — the only previously
UN-sanitized TTS entry) use it, so a chatty agent's markdown/URLs are not read
aloud as "star star", "backtick", "h-t-t-p-colon-slash-slash".
"""
from tools.tts_sanitize import sanitize_for_speech


def test_strips_bold():
    assert sanitize_for_speech("这是**重点**内容") == "这是重点内容"


def test_strips_italic():
    assert sanitize_for_speech("这是*斜体*字") == "这是斜体字"


def test_strips_inline_code():
    assert sanitize_for_speech("运行 `ls -la` 命令") == "运行 ls -la 命令"


def test_strips_heading():
    assert sanitize_for_speech("## 标题") == "标题"


def test_strips_multiple_headings_multiline():
    assert sanitize_for_speech("# 甲\n# 乙") == "甲\n乙"


def test_strips_list_bullets():
    assert sanitize_for_speech("- 第一\n- 第二") == "第一\n第二"


def test_link_keeps_text_drops_url():
    assert sanitize_for_speech("见[文档](https://x.com)这里") == "见文档这里"


def test_removes_bare_url():
    out = sanitize_for_speech("详见 https://example.com/a?b=c 完成")
    assert "http" not in out and "example.com" not in out
    assert "详见" in out and "完成" in out


def test_removes_fenced_code_block():
    out = sanitize_for_speech("好的:\n```py\nprint(1)\n```\n完成")
    assert "print(1)" not in out and "```" not in out
    assert "好的" in out and "完成" in out


def test_plain_chinese_unchanged():
    s = "今天天气不错,我们去散步吧。"
    assert sanitize_for_speech(s) == s


def test_plain_english_unchanged():
    s = "The meeting is at three pm."
    assert sanitize_for_speech(s) == s


def test_snake_case_unchanged():
    # underscores are not markdown emphasis here — must not be touched
    s = "调用 my_func 完成"
    assert sanitize_for_speech(s) == s


def test_empty_and_whitespace_become_empty():
    assert sanitize_for_speech("") == ""
    assert sanitize_for_speech("   \n  ") == ""


def test_pure_code_block_becomes_empty():
    assert sanitize_for_speech("```\ncode\n```") == ""
