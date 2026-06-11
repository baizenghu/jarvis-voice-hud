# 决策 0004 —— 首个里程碑:先在这台 Linux 上(浏览器内)跑通

日期:2026-06-11。状态:已采纳。

## 背景
最终目标仍是 Windows(decision 0003),但用户决定**先在这台 Linux 开发机上把整个语音回路
跑通**,之后再处理 Windows/Tauri 打包。这台 Linux 有原生音频(ALSA/PulseAudio),且浏览器在
Linux 上同样能拿到原生麦克风 + Web Audio。

## 决策
- 首个可用里程碑 = **Phase 0 + Phase 1 在 Linux 浏览器里跑通**:喊话(点击/热键触发)→ 前端
  录音 → `voice.transcribe` → agent 回合 → `voice.synthesize` → 前端播放 + HUD 动效。
- 仍采用"前端采音频"的目标架构(decision 0001),**不**临时改用主机侧 `sounddevice` 管线 ——
  因为前端方案在 Linux 浏览器里同样能跑,跑通的就是最终 Windows 架构,不是一次性 demo。
- **Phase 2(Tauri/Windows 打包)和 Phase 3(openWakeWord 唤醒词)推迟**到 Linux 回路稳定之后。
  在此之前用开发期热键/点击触发即可。

## 后果
- ✅ 最快拿到能用的东西,且不浪费——跑通的架构可直接搬去 Windows。
- ✅ 开发期不需要 Rust/Tauri 工具链,也不需要先训热词模型。
- ➖ 在 Linux 上,前端方案需要浏览器麦克风权限(localhost/https);比直接用 `sounddevice`
  多一点点接线,但避免了之后重写。
