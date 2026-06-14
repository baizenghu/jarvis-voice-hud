"""Shared TTS text sanitizer — strip markdown/URLs so they aren't read aloud.

Single source of truth (decisions/0007 phase 2). The regex sequence was lifted
verbatim from hermes_cli.voice.speak_text's inline block (which already shipped),
so reusing it here is behavior-preserving for that path. Callers handle their own
length truncation and empty-result policy; this only strips speakable noise.
"""
import re


def sanitize_for_speech(text: str) -> str:
    """Strip markdown emphasis/code/headers/lists and URLs; collapse blank runs.

    Returns the cleaned, stripped string (may be empty if the input was nothing
    but markup, e.g. a lone fenced code block).
    """
    t = re.sub(r'```[\s\S]*?```', ' ', text)              # fenced code blocks
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)        # [text](url) → text
    t = re.sub(r'https?://\S+', '', t)                    # bare URLs
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', t)                # bold
    t = re.sub(r'\*(.+?)\*', r'\1', t)                    # italic
    t = re.sub(r'`(.+?)`', r'\1', t)                      # inline code
    t = re.sub(r'^#+\s*', '', t, flags=re.MULTILINE)      # headers
    t = re.sub(r'^\s*[-*]\s+', '', t, flags=re.MULTILINE)  # list bullets
    t = re.sub(r'---+', '', t)                            # horizontal rules
    t = re.sub(r'\n{3,}', '\n\n', t)                      # excess newlines
    return t.strip()
