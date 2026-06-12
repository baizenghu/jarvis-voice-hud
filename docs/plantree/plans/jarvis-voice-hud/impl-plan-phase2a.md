# Phase 2a 实施计划 —— Windows 原生 hermes + 远程语音 + 操作本机(文件/命令档)

架构见 [decisions/0005](decisions/0005-windows-native-agent-deployment.md)。本档只做 ①文件/命令档,不含 Pico/GUI(2b)。

## 拓扑
```
Windows 笔记本(192.168.0.3,公司 LAN):
  hermes(原生)──STT/TTS──→ Linux 中心(192.168.0.7)
                            ├─ whisper API  :8010  /v1/audio/transcriptions(OpenAI 兼容)
                            └─ CosyVoice3    :8003  /tts
```

## Linux 中心侧 —— ✅ 已完成并验证
- `hud-app/whisper_api.py`:OpenAI 兼容 `POST /v1/audio/transcriptions`(复用 hermes `transcribe_recording`
  = large-v3 + VAD + 幻觉过滤),`HOST=0.0.0.0 PORT=8010` 起。本机 + 局域网均返回正确文本。
- `hud-app/cosyvoice_server.py`:加 `HOST` 环境变量;`start_cosyvoice.sh` 默认 `HOST=0.0.0.0`,绑局域网。
- 两个 API 从 Windows 实测可达(需绕过 Windows 本地代理,见下)。
- 起服务:
  - `HOST=0.0.0.0 PORT=8010 .venv/bin/python hud-app/whisper_api.py`
  - `bash hud-app/start_cosyvoice.sh`(默认绑 0.0.0.0)

## ⚠️ 关键坑:Windows 本地代理劫持局域网
Windows 设了本地代理 `127.0.0.1:10808`(Clash/V2Ray 类),`curl`/HTTP 客户端会把**连 192.168.0.7 的请求
也走代理** → 代理对 LAN 失败。实测 `--noproxy "*"` 后两个 API 都通。
**→ Windows hermes 必须设 `NO_PROXY`/`no_proxy` 包含中心 IP**(`192.168.0.7`,建议加 `192.168.0.0/16,127.0.0.1`),
让 STT 的 OpenAI 客户端、TTS 桥接的 urllib 都绕过代理直连中心。

## Windows 侧 —— 待做
目标机已探明:Win11 24H2,原生 Python(anaconda 3.12 / Python 3.11),WSL 没装(不需要),hermes 未装。

1. **装 hermes**(PowerShell,非交互):`iex (irm https://hermes-agent.nousresearch.com/install.ps1)`
   —— 自带 uv/Python3.11/Node/ffmpeg/MinGit,装在 `%LOCALAPPDATA%\hermes`,免管理员。
2. **设 `NO_PROXY`**(用户或环境变量):`setx NO_PROXY "192.168.0.7,192.168.0.0/16,127.0.0.1,localhost"`。
3. **配 hermes 模型**(同中心):`provider: custom` → `https://api.minimaxi.com/v1` + 那个 MiniMax key;
   `custom_providers[].extra_body: {thinking: {type: disabled}}`(M3 关思考);`model.default: MiniMax-M3`。
4. **配 STT 指向中心**:`stt.provider: openai`,`stt.openai.base_url: http://192.168.0.7:8010/v1`,
   `stt.openai.api_key: dummy`,`stt.openai.model: large-v3`。
5. **配 TTS 指向中心**:把 `hud-app/cosyvoice_say.py` 拷到 Windows;`tts.provider: cosyvoice`,
   command 用 hermes 自带 python 跑该桥接,env 设 `COSYVOICE_API=http://192.168.0.7:8003` + `no_proxy=192.168.0.7`。
6. **SOUL**:把"短句、禁顿号列举"的人设拷到 Windows hermes。
7. **验收**:在 Windows 上 `hermes` 跑一轮对话(文本),确认走中心 STT/TTS;再让贾维斯读写本机文件、跑命令
   (验证"操作本机"那档)。HUD(Tauri)留到 2c。

## 完成定义
- Windows 上的 hermes 能:语音转写(经中心 whisper)→ MiniMax-M3 回复 → 合成念回(经中心 CosyVoice 昊然嗓);
- 且能读写 Windows 本机文件、跑本机命令(Git Bash)。
- 全程局域网直连中心(NO_PROXY 生效)。

## 不在本档内
- Pico/clawtouch GUI 自动化(2b,等硬件);Tauri 悬浮窗(2c)。
