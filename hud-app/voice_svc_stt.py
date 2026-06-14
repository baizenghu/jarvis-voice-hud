#!/usr/bin/env python3
"""Standalone STT engine for the voice service (phase 5).

Zero hermes import: a self-contained faster-whisper transcriber that carries
over every STT quality gate the hermes path had — VAD + hallucination
suppression (incl. the Chinese subtitle-artifact list) + Jarvis name
normalization — but reads its config from env instead of hermes' config.yaml.

Migrated from (kept byte-faithful where it matters for anti-noise behaviour):
  - faster-whisper load + CUDA→CPU fallback: tools/transcription_tools.py
  - hallucination filter:                    tools/voice_mode.py
  - name normalization:                      hud-app/whisper_api.py

Config (env, no hermes config.yaml):
  STT_MODEL          faster-whisper model name or local path (default large-v3;
                     the start script points this at the local turbo dir).
  STT_LANGUAGE       forced decode language (default "zh"; "" = auto-detect).
  STT_INITIAL_PROMPT optional decode bias (code-switch hint for forced-zh so
                     "Jarvis" survives instead of becoming a phonetic Chinese).
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("voice_svc_stt")

# ---------------------------------------------------------------------------
# Hallucination filter (from tools/voice_mode.py:824-893)
# ---------------------------------------------------------------------------
# Whisper commonly hallucinates these phrases on silent/near-silent audio.
WHISPER_HALLUCINATIONS = {
    "thank you.",
    "thank you",
    "thanks for watching.",
    "thanks for watching",
    "subscribe to my channel.",
    "subscribe to my channel",
    "like and subscribe.",
    "like and subscribe",
    "please subscribe.",
    "please subscribe",
    "thank you for watching.",
    "thank you for watching",
    "bye.",
    "bye",
    "you",
    "the end.",
    "the end",
    # Non-English hallucinations (common on silence)
    "продолжение следует",
    "продолжение следует...",
    "sous-titres",
    "sous-titres réalisés par la communauté d'amara.org",
    "sottotitoli creati dalla comunità amara.org",
    "untertitel von stephanie geiges",
    "amara.org",
    "www.mooji.org",
    "ご視聴ありがとうございました",
    # Chinese hallucinations (YouTube-subtitle artifacts on silence/unclear audio)
    "请关注",
    "请订阅",
    "谢谢观看",
    "谢谢大家",
    "欢迎关注明镜",
    "明镜需要您的支持,欢迎关注明镜",
    "明镜需要您的支持，欢迎关注明镜",
    "明镜与点点栏目",
    "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
    "中文字幕",
    "中文字幕提供",
    "中文字幕製作",
    "中文字幕制作",
    "字幕製作",
    "字幕制作",
    "字幕由amara.org社区提供",
    "词曲:李宗盛",
    "詞曲:李宗盛",
    "作词:李宗盛",
    "作曲:李宗盛",
}

# Repetitive hallucinations (e.g. "Thank you. Thank you. Thank you.")
_HALLUCINATION_REPEAT_RE = re.compile(
    r'^(?:thank you|thanks|bye|you|ok|okay|the end|\.|\s|,|!)+$',
    flags=re.IGNORECASE,
)


def is_whisper_hallucination(transcript: str) -> bool:
    """Check if a transcript is a known Whisper hallucination on silence."""
    cleaned = transcript.strip().lower()
    if not cleaned:
        return True
    if cleaned.rstrip('.!。!') in WHISPER_HALLUCINATIONS or cleaned in WHISPER_HALLUCINATIONS:
        return True
    if _HALLUCINATION_REPEAT_RE.match(cleaned):
        return True
    return False


# ---------------------------------------------------------------------------
# Name normalization (from hud-app/whisper_api.py:30-33)
# ---------------------------------------------------------------------------
# Forced-zh decoding turns "Jarvis"/「贾维斯」into phonetic typos; fold them all
# back to the canonical name so downstream (LLM prompt, stand-down match) is stable.
_JARVIS_ALIASES = re.compile(r"(?i)jarvis|夏威士|加维斯|甲微事|贾伟斯|佳维斯|家维斯|加伟斯")


def _normalize_names(text: str) -> str:
    return _JARVIS_ALIASES.sub("贾维斯", text)


# ---------------------------------------------------------------------------
# faster-whisper load + transcribe (from tools/transcription_tools.py:1064-1186)
# ---------------------------------------------------------------------------
# Deliberately narrow: match library-name tokens and dlopen phrasing so we DO
# NOT accidentally catch legitimate runtime failures like "CUDA out of memory".
_CUDA_LIB_ERROR_MARKERS = (
    "libcublas",
    "libcudnn",
    "libcudart",
    "cannot be loaded",
    "cannot open shared object",
    "no kernel image is available",
    "no CUDA-capable device",
    "CUDA driver version is insufficient",
)

_local_model = None
_local_model_name: str | None = None


def _looks_like_cuda_lib_error(exc: BaseException) -> bool:
    """Heuristic: is this exception a missing/broken CUDA runtime library?

    ctranslate2 raises plain RuntimeError like
    ``Library libcublas.so.12 is not found or cannot be loaded``. We catch
    missing/unloadable shared libs and driver mismatch, NOT legitimate runtime
    failures ("CUDA out of memory", model bugs, etc.).
    """
    msg = str(exc)
    return any(marker in msg for marker in _CUDA_LIB_ERROR_MARKERS)


def _load_local_whisper_model(model_name: str):
    """Load faster-whisper with graceful CUDA → CPU fallback."""
    from faster_whisper import WhisperModel
    try:
        return WhisperModel(model_name, device="auto", compute_type="auto")
    except Exception as exc:
        if not _looks_like_cuda_lib_error(exc):
            raise
        logger.warning(
            "faster-whisper CUDA load failed (%s) — falling back to CPU (int8). "
            "Install the NVIDIA CUDA runtime (libcublas/libcudnn) to use GPU.",
            exc,
        )
        return WhisperModel(model_name, device="cpu", compute_type="int8")


def _model_name() -> str:
    return os.getenv("STT_MODEL", "large-v3")


def _transcribe_kwargs() -> dict:
    kwargs = {
        "beam_size": 5,
        # Hallucination suppression — short/quiet clips otherwise produce canned
        # "subscribe to my channel" style phrases (e.g. Chinese "欢迎关注明镜").
        # VAD drops non-speech; the rest steer decoding off those artifacts.
        "vad_filter": True,
        "condition_on_previous_text": False,
        "temperature": 0.0,
        "no_speech_threshold": 0.6,
        "compression_ratio_threshold": 2.4,
    }
    # Language: STT_LANGUAGE env (default zh; "" = auto-detect).
    lang = os.getenv("STT_LANGUAGE", "zh")
    if lang:
        kwargs["language"] = lang
    # Optional decode bias (code-switch hint so forced-zh still emits "Jarvis").
    initial_prompt = os.getenv("STT_INITIAL_PROMPT")
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    return kwargs


def _transcribe_local(audio_path: str) -> str:
    """Run faster-whisper on the file and return the raw joined transcript.

    Lazy-loads + caches the model. On a CUDA runtime failure that only surfaces
    mid-transcribe (dlopen-on-first-use after a successful load), evict the
    poisoned cached model, reload on CPU, retry once.
    """
    global _local_model, _local_model_name

    model_name = _model_name()
    if _local_model is None or _local_model_name != model_name:
        logger.info("Loading faster-whisper model '%s'...", model_name)
        _local_model = _load_local_whisper_model(model_name)
        _local_model_name = model_name

    kwargs = _transcribe_kwargs()
    try:
        segments, info = _local_model.transcribe(audio_path, **kwargs)
        transcript = " ".join(segment.text.strip() for segment in segments)
    except Exception as exc:
        if not _looks_like_cuda_lib_error(exc):
            raise
        logger.warning(
            "faster-whisper CUDA runtime failed mid-transcribe (%s) — "
            "evicting cached model and retrying on CPU (int8).",
            exc,
        )
        _local_model = None
        _local_model_name = None
        from faster_whisper import WhisperModel
        _local_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        _local_model_name = model_name
        segments, info = _local_model.transcribe(audio_path, **kwargs)
        transcript = " ".join(segment.text.strip() for segment in segments)

    logger.info(
        "Transcribed %s (%s, lang=%s, %.1fs audio)",
        os.path.basename(audio_path), model_name, info.language, info.duration,
    )
    return transcript


def transcribe(audio_path: str, backend: str = "local") -> str:
    """Transcribe an audio file to text. Empty string = silence/hallucination.

    backend "local" → faster-whisper; "baidu" → NotImplementedError (501 at the
    HTTP layer; interface-only this phase).
    """
    backend = (backend or "local").lower()
    if backend == "baidu":
        raise NotImplementedError("baidu STT backend not implemented")
    if backend != "local":
        raise NotImplementedError(f"unknown STT backend: {backend!r}")

    raw = (_transcribe_local(audio_path) or "").strip()
    # Filter hallucinations BEFORE normalization (current order; the alias set
    # and hallucination set don't overlap, so order is safe either way).
    if is_whisper_hallucination(raw):
        logger.info("Filtered Whisper hallucination: %r", raw)
        return ""
    return _normalize_names(raw)
