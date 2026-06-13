#!/usr/bin/env bash
# 贾维斯音频运行态配置 —— 机器重启 / PipeWire 重启后会全部丢失,需重跑一次。
# 幂等:可反复执行。务必在「启动 KWS / HUD 壳之前」跑,它们启动时才会绑到正确的源。
#
#   1) 麦克风增益:关掉 +30dB 内置 boost(过载削波会毁掉 whisper STT),Capture 70%
#   2) 回声消除:加载 module-echo-cancel(webrtc),放歌时也能唤醒/对话
#   3) 默认源=消回声麦、默认汇=参考汇(音乐/TTS 经它走,给 AEC 提供参考信号)
set -e
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
MIC=alsa_input.pci-0000_00_1f.3.analog-stereo
SPK=alsa_output.pci-0000_00_1f.3.analog-stereo

# 1) 增益(去削波)
amixer -c 0 set 'Internal Mic Boost' 0 >/dev/null 2>&1 || true
amixer -c 0 set 'Mic Boost' 0          >/dev/null 2>&1 || true
amixer -c 0 set 'Capture' 70%          >/dev/null 2>&1 || true

# 2) echo-cancel(已加载则跳过)
if ! pactl list sources short | grep -q echocancel_source; then
  pactl load-module module-echo-cancel aec_method=webrtc \
    source_master="$MIC" sink_master="$SPK" \
    source_name=echocancel_source sink_name=echocancel_sink >/dev/null
fi

# 3) 默认源/汇
pactl set-default-sink   echocancel_sink
pactl set-default-source echocancel_source

echo "[jarvis-audio] OK:麦增益已去削波 + echo-cancel 已加载 + 默认源/汇=echocancel"
