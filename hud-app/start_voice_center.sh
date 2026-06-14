#!/usr/bin/env bash
# 中心(10.8.0.2,GPU)语音栈一键启动 —— 机器重启后跑这一个。
# 拉起两个常驻服务:
#   ① CosyVoice TTS      :8003  (cosyvoice 模型,加载慢)
#   ② voice_svc STT/TTS  :8011  (phase5 独立语音服务:faster-whisper turbo + 转发 TTS 到 ①)
# 家里 0.3 的 HUD 喊话经 WG 直连 voice_svc:8011;voice_svc 再 loopback 转发 TTS 到 CosyVoice。
#
# 鉴权 token 从 ~/.jarvis-secrets 读(不入库,须与 0.3 HUD 的 JARVIS_TOKEN 一致)。
# 幂等:CosyVoice 已健康则跳过(模型加载慢,不重复杀);voice_svc 轻量,每次按端口重起拾取最新代码。
# 杀进程一律按端口(别 pkill -f,会误杀自己)。
set -u
cd "$HOME/hermes-agent"

[ -f "$HOME/.jarvis-secrets" ] && . "$HOME/.jarvis-secrets"
if [ -z "${JARVIS_GATEWAY_TOKEN:-}" ]; then
  echo "FATAL: JARVIS_GATEWAY_TOKEN 未设。放进 ~/.jarvis-secrets:"
  echo "  echo 'export JARVIS_GATEWAY_TOKEN=<与0.3一致的token>' >> ~/.jarvis-secrets"
  exit 1
fi

echo "== 1) CosyVoice TTS (8003) =="
if curl -sf -o /dev/null http://127.0.0.1:8003/health; then
  echo "  已在跑,跳过(模型加载慢,不重启)"
else
  setsid nohup bash hud-app/start_cosyvoice.sh > /tmp/cosyvoice.log 2>&1 < /dev/null &
  echo "  启动中(模型加载约 10-40s,看 /tmp/cosyvoice.log)"
fi

echo "== 2) voice_svc STT/TTS (8011) =="
fuser -k -9 8011/tcp 2>/dev/null; sleep 1
HOST=0.0.0.0 PORT=8011 \
  setsid nohup bash hud-app/start_voice_svc.sh > /tmp/voice_svc.log 2>&1 < /dev/null &
echo "  启动中(STT turbo 首句加载约 2-3s)"

echo "== 等就绪 =="
for _ in $(seq 1 30); do
  sleep 2
  curl -sf -o /dev/null http://127.0.0.1:8003/health \
    && curl -sf -o /dev/null http://127.0.0.1:8011/health && break
done
echo "== 状态 =="
echo "  CosyVoice 8003: $(curl -sf -o /dev/null http://127.0.0.1:8003/health && echo UP || echo 'DOWN(看 /tmp/cosyvoice.log)')"
echo "  voice_svc 8011: $(curl -s http://127.0.0.1:8011/health 2>/dev/null || echo 'DOWN(看 /tmp/voice_svc.log)')"
echo "完成。0.3 HUD 喊话即走中心 voice_svc。"
