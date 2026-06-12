#!/usr/bin/env bash
# Launch the CosyVoice3-0.5B TTS server with the haoran reference voice.
# CosyVoice3 REQUIRES the "<system>...<|endofprompt|><ref transcript>" prompt
# format — without it the LLM emits empty output and the vocoder crashes.
exec env \
  COSYVOICE_MODEL_DIR=/home/baizh/CosyVoice/pretrained_models/CosyVoice3-0.5B \
  COSYVOICE_REF_AUDIO=/home/baizh/hermes-agent/hud-app/voices/haoran_ref.wav \
  COSYVOICE_REF_TEXT="You are a helpful assistant.<|endofprompt|>你好,我是昊然,我的声音沉稳自然,语调平和,语速平稳,温润醇厚,兼具温柔与力量,听起来亲切而有信任感。" \
  /home/baizh/anaconda3/envs/cosyvoice/bin/python -u /home/baizh/hermes-agent/hud-app/cosyvoice_server.py
