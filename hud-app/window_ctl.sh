#!/usr/bin/env bash
# 窗口控制(X11 · wmctrl+xdotool)—— 确定性、秒级,不靠看屏点击。
# 供 agent 的 window-control skill 调用。标题关键词做子串匹配。
#   list                   列出当前窗口标题(供选择)
#   minimize <标题关键词>   最小化匹配窗口
#   close    <标题关键词>   关闭匹配窗口
#   activate <标题关键词>   置前/聚焦匹配窗口
export DISPLAY="${DISPLAY:-:0}"
act="${1:-}"; shift 2>/dev/null || true
q="$*"
case "$act" in
  list)
    wmctrl -l | awk '{$1=$2=$3="";sub(/^ +/,"");print}'
    ;;
  minimize)
    ids=$(xdotool search --name "$q" 2>/dev/null)
    [ -z "$ids" ] && { echo "FAILED: 没找到标题含「$q」的窗口"; exit 0; }
    for id in $ids; do xdotool windowminimize "$id" 2>/dev/null; done
    echo "MINIMIZED: $q"
    ;;
  close)
    if wmctrl -c "$q" 2>/dev/null; then echo "CLOSED: $q"; else echo "FAILED: 关不掉「$q」"; fi
    ;;
  activate)
    if wmctrl -a "$q" 2>/dev/null; then echo "ACTIVATED: $q"; else echo "FAILED: 找不到「$q」"; fi
    ;;
  *)
    echo "用法: window_ctl.sh list|minimize|close|activate [标题关键词]"
    ;;
esac
