# 路线图:贾维斯语音 HUD

持久的分期状态。每个阶段实现的架构见 [design.md](design.md)。

## 已完成
- _(暂无 —— 设计已成稿,待用户复核)_

## 进行中
- **当前里程碑(decision 0004):先在这台 Linux 上、浏览器内跑通 Phase 0 + Phase 1。**
  Windows/Tauri(Phase 2)与唤醒词(Phase 3)推迟到 Linux 回路稳定后。
- **Phase 0 代码已完成**(commits 至 `voice-hud-phase0` 分支):`voice_bytes` 适配 + 两个 RPC + 浏览器 harness,8 个单测全绿,两轮 subagent 审查通过。**仅剩真机端到端实测**(需用户的浏览器+麦克风)未做——通过后即可移入"已完成"。

## 下一步
### Phase 0 —— 服务端语音字节 RPC + 开发验证环
> 可执行实施计划:[impl-plan-phase0.md](impl-plan-phase0.md)(逐任务、TDD、含浏览器 harness)。
- 在 `tui_gateway/server.py` 增加 `voice.transcribe`(音频字节→文本)和 `voice.synthesize`
  (文本→音频字节),通过一个薄适配模块委托给现有 STT/TTS 引擎。
- 用一个 fixture WAV + 一段短文本做单测。
- 一个临时 HTML 页面,在 Linux 浏览器里跑通回路。
- **验收门:** 浏览器录音 → 文本 → agent 回复 → 合成语音,全程在 Linux 上跑通。

### Phase 1 —— HUD 前端(`hud-app/`)
- 把 `hud-app/` 搭成 TS 工程(package.json + tsconfig + **flat config `eslint.config.mjs`**,
  规则见 [topics/frontend-lint.md](topics/frontend-lint.md))。
- 语音状态机(idle/listening/transcribe/think/speak)。
- Web Audio 麦克风采集 + VAD + TTS 播放;AnalyserNode 接线。
- WebGL 贾维斯 HUD,带四种音频反应视觉状态。
- 点击/热键唤醒(开发期)。先跑在普通浏览器里(尚无外壳)。
- **验收门:** 用真实 HUD 在浏览器里(Linux)跑通完整语音回路。

### Phase 2 —— Tauri 外壳(`hud-shell/`)+ Windows 打包
- 无边框、透明、置顶、可拖动窗口;托盘;全局热键(开发期兜底)。
- GitHub Actions 工作流构建 Windows `.exe`。
- **验收门:** 悬浮 HUD 助手在真实 Windows 目标上运行。

### Phase 3 —— 唤醒词(喊它名字)—— 已确认
喊出助手名字唤醒是核心交互(decision 0003),非可选项。
- 引擎与名字已定(open-questions 已解决):**openWakeWord** + **"贾维斯"**(训练自定义中文热词)。
- 跑一个常驻监听器(倾向 Tauri Rust 侧),触发 IDLE→LISTENING。
- 取代开发期的热键/点击成为主触发方式。
- **验收门:** 待机时喊"贾维斯"即唤醒 HUD 并开始聆听,全程免手动。

## 延后
- 声音克隆 TTS(GPT-SoVITS / CosyVoice)—— 仅当用户想要克隆音色时再做。
- macOS/Linux 桌面打包。
- 流式 / 抢断打断。
