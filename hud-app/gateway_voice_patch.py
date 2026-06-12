"""Register voice.transcribe / voice.synthesize on an upstream hermes gateway.

This fork ships them inside tui_gateway/server.py; the upstream source deployed
on Windows (D:\\hermes-agent-main) does not. dev_server.py calls register() at
startup — a no-op when the methods already exist (i.e. running on the fork).
"""
from __future__ import annotations

import base64

from tui_gateway import server as _srv


def register() -> None:
    if "voice.transcribe" in _srv._methods:
        return
    try:
        from tui_gateway.voice_bytes import synthesize_bytes, transcribe_bytes
    except ImportError:
        # Upstream install: use the copy shipped next to dev_server.py.
        from voice_bytes_vendored import synthesize_bytes, transcribe_bytes

    @_srv.method("voice.transcribe")
    def _(rid, params: dict) -> dict:
        b64 = params.get("audio") or ""
        mime = params.get("mime") or "audio/webm"
        if not b64:
            return _srv._err(rid, 4024, "audio required")
        try:
            audio = base64.b64decode(b64)
        except Exception:
            return _srv._err(rid, 4025, "audio is not valid base64")
        try:
            return _srv._ok(rid, {"text": transcribe_bytes(audio, mime)})
        except Exception as e:
            return _srv._err(rid, 5029, str(e))

    @_srv.method("voice.synthesize")
    def _(rid, params: dict) -> dict:
        text = (params.get("text") or "").strip()
        if not text:
            return _srv._err(rid, 4026, "text required")
        try:
            audio, mime = synthesize_bytes(text)
            if not audio:
                return _srv._err(rid, 5028, "synthesis produced no audio")
            return _srv._ok(rid, {"audio": base64.b64encode(audio).decode(), "mime": mime})
        except Exception as e:
            return _srv._err(rid, 5028, str(e))
