"""Baidu Cloud STT backend (decisions/0007: STT is a swappable central voice
service). Opt-in via STT_BACKEND=baidu; selected in tui_gateway.voice_bytes.

Flow: any MediaRecorder audio → ffmpeg → 16kHz mono 16-bit PCM → Baidu
short-speech ASR (cloud, no GPU; bypasses the center whisper). Returns the
transcript, or "" on recognition failure / no speech (same contract as the
whisper path). Raises on config/transport errors so they surface in logs.

Env:
  BAIDU_STT_API_KEY / BAIDU_STT_SECRET_KEY  — 百度智能云 应用的 API Key/Secret Key
  BAIDU_STT_DEV_PID (default 1537 = 普通话含标点;1737=英语;1637=粤语;80001=极速版)
"""
import base64
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
_ASR_URL = "https://vop.baidu.com/server_api"
_token_cache: dict = {"token": "", "exp": 0.0}


def _run_ffmpeg(audio: bytes) -> bytes:
    """Decode any container/codec → raw 16kHz mono signed-16-bit-LE PCM.

    Missing binary raises (loud config/ops error); an undecodable chunk returns
    b"" (treated as no speech — one bad chunk shouldn't hard-fail a turn)."""
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"],
            input=audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise RuntimeError("ffmpeg not found on PATH — required for Baidu STT") from e
    if p.returncode != 0:
        logger.warning("baidu STT: ffmpeg decode failed: %r", p.stderr[-200:])
        return b""
    return p.stdout


def _http_post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _http_post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _get_token(now: float | None = None) -> str:
    now = time.time() if now is None else now
    if _token_cache["token"] and now < _token_cache["exp"]:
        return _token_cache["token"]
    ak = os.environ.get("BAIDU_STT_API_KEY") or ""
    sk = os.environ.get("BAIDU_STT_SECRET_KEY") or ""
    if not ak or not sk:
        raise RuntimeError("BAIDU_STT_API_KEY / BAIDU_STT_SECRET_KEY not set")
    resp = _http_post_form(_TOKEN_URL, {
        "grant_type": "client_credentials", "client_id": ak, "client_secret": sk,
    })
    tok = resp.get("access_token") or ""
    if not tok:
        # Don't dump the full response (could carry a token); just the error.
        raise RuntimeError(
            f"baidu token request failed: {resp.get('error_description') or resp.get('error') or 'no access_token'}"
        )
    _token_cache["token"] = tok
    _token_cache["exp"] = now + float(resp.get("expires_in", 2592000)) - 60
    return tok


def transcribe_baidu(audio: bytes, mime: str) -> str:
    """Transcribe audio bytes via Baidu cloud ASR. "" on empty/failed recognition."""
    if not audio:
        return ""
    # Missing creds = config error → raise loud (so setup is obvious). Recognition
    # failure / no speech / transient transport blips → "" (graceful, like whisper).
    if not (os.environ.get("BAIDU_STT_API_KEY") and os.environ.get("BAIDU_STT_SECRET_KEY")):
        raise RuntimeError("BAIDU_STT_API_KEY / BAIDU_STT_SECRET_KEY not set")
    pcm = _run_ffmpeg(audio)
    if not pcm:
        return ""
    try:
        token = _get_token()
        payload = {
            "format": "pcm", "rate": 16000, "channel": 1,
            "cuid": "jarvis-hud", "token": token,
            "dev_pid": int(os.environ.get("BAIDU_STT_DEV_PID", "1537")),
            "speech": base64.b64encode(pcm).decode(), "len": len(pcm),
        }
        resp = _http_post_json(_ASR_URL, payload)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("baidu STT transport error: %s", type(e).__name__)
        return ""  # network blip mid-conversation → no-speech turn, not a hard error
    if resp.get("err_no"):  # non-zero/non-None → failed or no speech
        return ""
    result = resp.get("result") or []
    return result[0].strip() if result else ""
