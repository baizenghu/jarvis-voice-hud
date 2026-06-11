# 未决问题:贾维斯语音 HUD

仅列未决项。已解决的迁入决策记录。

> 已解决:**运行时 = Windows(WSL2),HUD 连 localhost** —— 原 Q1。
> 已解决:**唤醒方式 = 语音热词(喊它名字)** —— 原 Q5。见
> [decisions/0003-activation-wake-word.md](decisions/0003-activation-wake-word.md)。热键/点击仅作开发期兜底。
> 已解决:**名字 = "贾维斯"(中文),引擎 = openWakeWord(训练自定义热词)** —— 原 Q1。

1. **WS 上的音频传输:** JSON 里的 base64(简单,体积大约 +33%)vs 二进制 WS 帧(高效,需
   `tui_gateway/ws.py` 支持二进制帧 —— 目前未审查)。Phase 0 查过 `ws.py` 后决定。
2. **唤醒监听器跑在哪:** 浏览器里持续跑(ONNX/WASM)vs Tauri Rust 侧。Rust 侧即使 WebView
   隐藏/休眠也能持续监听 —— 对"喊一声就醒"的常驻助手大概更合适。
3. **浏览器里的 VAD:** 复用 JS VAD 库(如 silero-vad WASM / ricky0123/vad)vs 像现有 Python
   `voice_mode.py` 那样的简单 RMS 阈值。影响"说完就自动回复"的自然程度。
4. **HUD 形象/视觉规格:** 具体长相 —— 纯环形 HUD vs 球 vs 隐约的脸?配色?尺寸?
   值得在 Phase 1 开建前先出个视觉 mockup。
5. **助手默认音色:** 从现有 provider 里哪家/哪个音色最有"贾维斯"味(Edge?ElevenLabs?),
   再考虑是否要克隆音色。
