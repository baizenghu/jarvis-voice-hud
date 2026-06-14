#!/usr/bin/env bash
# Launch the standalone voice service (phase 5): STT (faster-whisper turbo) +
# TTS forward to cosyvoice_server. Zero hermes import — runs from the project
# .venv (needs faster_whisper), NOT anaconda base (starlette clash, see HANDOFF).
#
# STT_MODEL points at the LOCAL turbo dir (same path the hermes config.yaml uses)
# so faster-whisper loads it directly without touching HuggingFace. Default
# large-v3 would silently downgrade quality+speed — keep this explicit (spec R6).
#
# Non-loopback HOST requires JARVIS_GATEWAY_TOKEN (fail-closed); pass it in env.
exec env \
  HOST="${HOST:-0.0.0.0}" \
  PORT="${PORT:-8011}" \
  STT_MODEL="${STT_MODEL:-/home/baizh/.cache/whisper-models/faster-whisper-large-v3-turbo}" \
  STT_LANGUAGE="${STT_LANGUAGE:-zh}" \
  COSYVOICE_API="${COSYVOICE_API:-http://127.0.0.1:8003}" \
  /home/baizh/hermes-agent/.venv/bin/python -u /home/baizh/hermes-agent/hud-app/voice_svc.py
