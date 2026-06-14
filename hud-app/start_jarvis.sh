#!/usr/bin/env bash
# 贾维斯家里(0.3 机器)全栈一键启动 —— 重启后跑这一个即可。幂等(先杀旧再拉起)。
# 注意:中心 GPU(10.8.0.2)的 TTS/STT/中继 8766 是另一台,需各自常驻,不在此脚本内。
set -u
cd "$HOME/hermes-agent"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DISPLAY="${DISPLAY:-:0}"
VENV="$HOME/hermes-agent/.venv/bin/python"

echo "== 1) 音频运行态(增益/AEC/默认源汇)=="
bash "$HOME/hermes-agent/hud-app/audio_setup.sh"

echo "== 2) 网关 =="
fuser -k 8765/tcp 2>/dev/null; sleep 2
HERMES_YOLO_MODE=1 HERMES_HOME=/home/baizh/hermes-home HOST=127.0.0.1 PORT=8765 \
  HERMES_TUI_TOOLSETS="skills,terminal,clawtouch,vision,voice_hud,web" \
  setsid nohup "$VENV" hud-app/dev_server.py > /tmp/gw_orch.log 2>&1 < /dev/null &
for i in $(seq 1 25); do sleep 2; curl -sf -o /dev/null http://127.0.0.1:8765/ && { echo "  网关 UP"; break; }; done

echo "== 3) KWS(听默认源=消回声麦)=="
for p in $(pgrep -f kws_listener); do kill "$p" 2>/dev/null; done; sleep 1
KWS_MODEL_DIR=/home/baizh/kws-model \
  setsid nohup "$VENV" -u hud-app/kws_listener.py > /tmp/kws_listener.log 2>&1 < /dev/null &

echo "== 4) audio_levels(系统输出频段→光圈跟跳)=="
for p in $(pgrep -f audio_levels.py); do kill "$p" 2>/dev/null; done
setsid nohup "$VENV" -u hud-app/audio_levels.py > /tmp/audio_levels.log 2>&1 < /dev/null &

echo "== 5) HUD 壳(overlay)=="
for p in $(pgrep -f jarvis-hud); do PG=$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' '); [ -n "$PG" ] && kill -- -"$PG" 2>/dev/null; done; sleep 2
( cd hud-app/shell && JARVIS_OVERLAY=1 PATH="$HOME/.cargo/bin:$PATH" \
    setsid nohup npm run tauri:dev > /tmp/jarvis_shell.log 2>&1 < /dev/null & )

sleep 6
echo "== 状态 =="
echo "  网关:$(curl -sf -o /dev/null http://127.0.0.1:8765/ && echo UP || echo DOWN)"
echo "  KWS:$(pgrep -f kws_listener >/dev/null && echo UP || echo DOWN)"
echo "  audio_levels:$(pgrep -f audio_levels.py >/dev/null && echo UP || echo DOWN)"
echo "  HUD 壳:在构建中(看 /tmp/jarvis_shell.log,约 10-30s 出窗)"
echo "完成。喊「贾维斯」试试。"
