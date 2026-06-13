#!/usr/bin/env bash
# 贾维斯音频运行态配置 —— 机器重启 / PipeWire 重启 / 接拔 HDMI 后都需重跑一次。
# 幂等:每次卸旧 echo-cancel 再按「当前真实」的模拟源/汇重建(profile 切换会改设备
# 后缀如 .2/.3,且接拔 HDMI 会让旧 echo-cancel 绑到已消失的汇致播放无声)。
#   1) 麦增益:关 +30dB 内置 boost(削波毁 STT),Capture 70%
#   2) echo-cancel:绑到当前模拟汇(放歌时也能唤醒/对话)
#   3) 默认源=消回声麦、默认汇=参考汇
set -u
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# 1) 增益(去削波)
amixer -c 0 set 'Internal Mic Boost' 0 >/dev/null 2>&1 || true
amixer -c 0 set 'Mic Boost' 0          >/dev/null 2>&1 || true
amixer -c 0 set 'Capture' 70%          >/dev/null 2>&1 || true

# 2) 卸载旧 echo-cancel(可能绑到已拔的 HDMI 或旧设备名)
for m in $(pactl list modules short | grep echo-cancel | cut -f1); do
  pactl unload-module "$m" 2>/dev/null || true
done
sleep 1

# 3) 动态取当前真实的模拟汇/麦(优先 analog,取不到就退回第一个物理设备)
SPK=$(pactl list sinks short   | grep alsa_output | grep -i analog | grep -v monitor | head -1 | cut -f2)
MIC=$(pactl list sources short | grep alsa_input  | grep -i analog | grep -v monitor | head -1 | cut -f2)
[ -z "$SPK" ] && SPK=$(pactl list sinks short   | grep alsa_output | grep -v monitor | head -1 | cut -f2)
[ -z "$MIC" ] && MIC=$(pactl list sources short | grep alsa_input  | grep -v monitor | head -1 | cut -f2)
echo "[jarvis-audio] 模拟汇=$SPK  麦=$MIC"

# 4) 重建 echo-cancel + 默认源汇
pactl load-module module-echo-cancel aec_method=webrtc \
  source_master="$MIC" sink_master="$SPK" \
  source_name=echocancel_source sink_name=echocancel_sink >/dev/null
pactl set-default-sink   echocancel_sink
pactl set-default-source echocancel_source

echo "[jarvis-audio] OK:麦去削波 + echo-cancel 绑到当前模拟汇 + 默认源汇=echocancel"
