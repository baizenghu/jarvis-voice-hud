---
name: window-control
description: 用户想最小化、关闭、切换/置前桌面上某个窗口或文件夹时(如"最小化知识库""关掉那个文件夹""切到浏览器"),用 wmctrl/xdotool 确定性地操作——不要用截屏看屏点击(那又慢又不稳,会超时)。
metadata:
  hermes:
    tags: [desktop, window, gui, wmctrl]
---
# 窗口控制(X11 · 确定性)

用户要最小化/关闭/置前某个窗口或文件夹时,用 `terminal` 跑脚本即可,**按窗口标题关键词**操作,秒级完成。**不要**用 clawtouch/vision 截屏找按钮点击。

## 先看有哪些窗口(需要时)
```
~/hermes-agent/hud-app/window_ctl.sh list
```
输出每行一个窗口标题。据此挑出用户说的那个(子串匹配即可,如"知识库")。

## 操作
- 最小化:`~/hermes-agent/hud-app/window_ctl.sh minimize "知识库"`
- 关闭:  `~/hermes-agent/hud-app/window_ctl.sh close "知识库"`
- 置前/聚焦:`~/hermes-agent/hud-app/window_ctl.sh activate "知识库"`

把 `知识库` 换成用户指的窗口的标题关键词。**看最后一行输出**:
- `MINIMIZED/CLOSED/ACTIVATED: <名>` → 成功,简短回复用户(如"好,已最小化知识库")。
- `FAILED: ...` → 没找到/没成,如实告诉用户,可先 `list` 看准确标题再试。

## 注意
- 打开文件夹/应用不归这里(用 nautilus/xdg-open)。本 skill 只管已开窗口的最小化/关闭/置前。
- 别动标题里含 "Jarvis HUD" 的窗口(那是助手自己的光圈)。
