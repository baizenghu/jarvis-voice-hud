# 决策 0001 —— 音频在前端采集与播放,而非 Python 主机

日期:2026-06-11。状态:已采纳(待用户复核计划)。

## 背景
hermes 已有一条主机侧音频管线(`tools/voice_mode.py` + `hermes_cli/voice.py`,暴露为
`voice.record` / `voice.tts` RPC),用 `sounddevice` 在**运行 Python 的机器上**采集麦克风、
播放 TTS。贾维斯 HUD 的最终目标是 Windows,而 hermes 不原生支持 Windows,跑在 WSL2 里。
WSL2 主机音频设备穿透不可靠,而用户真正的麦克风/扬声器在 Windows 原生侧 —— 正是
Tauri/WebView HUD 运行的地方。

## 决策
HUD 前端自己采集麦克风、播放 TTS 音频(Web Audio / MediaRecorder)。服务端只通过两个新 RPC
(`voice.transcribe`、`voice.synthesize`)在原始字节上复用 STT/TTS **引擎**。现有基于
`sounddevice` 的 `voice.record` / `voice.tts` RPC 原样保留给 CLI/经典 TUI 路径,HUD **不使用**它们。

## 后果
- ✅ 音频留在 Windows 原生侧,设备就在那里;无论 hermes 是本地 WSL2 还是远程都能用。
- ✅ STT/TTS provider 栈(10+ 家)原样复用。
- ✅ 做音频反应视觉所需的 AnalyserNode 在前端天然可得。
- ➖ 需新增两个服务端 RPC + 一个围绕现有引擎读写临时文件的小字节适配层。
- ➖ 音频字节要过 WS 链路(传输编码见 open-question 1)。

## 被否决的备选
- **原样复用 `voice.record`/`voice.tts`。** 更简单,但依赖 Python 主机拥有麦克风/扬声器 ——
  在 WSL2 的 Windows 目标上脆弱乃至不可用,若 hermes 远程则根本不可行。
