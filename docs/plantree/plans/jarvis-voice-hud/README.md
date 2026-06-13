# 计划:贾维斯语音 HUD(Jarvis Voice HUD)

一个面向 hermes-agent 的 Windows 桌面悬浮 AI 助手:一个漂亮的 WebGL"贾维斯"风格 HUD,
常驻桌面置顶,喊它名字唤醒,听你说话,把语音走正常的 hermes agent 回合处理,再用语音把
回复说出来 —— 全程带音频驱动的动效。

灵感来自 [LumiOS](https://github.com/maoxiansheng946-dev/-lumi-OS);视觉目标是钢铁侠/贾维斯
那种 HUD(发光环、音频驱动的声纹/粒子、待机呼吸感)。

## 范围与权威
- 本 `README.md` —— 范围与文件地图。
- [design.md](design.md) —— 持久的架构与设计真相(重点读这个)。
- [roadmap.md](roadmap.md) —— 分期状态:已完成 / 进行中 / 下一步 / 延后。
- [open-questions.md](open-questions.md) —— 仅未决问题。
- [decisions/](decisions/) —— 稳定决策。

前置阅读:[../../baseline/voice-stack.md](../../baseline/voice-stack.md)。

## 文件地图
| 文件 | 角色 |
|---|---|
| [design.md](design.md) | 架构、分层、数据流、组件、错误处理、测试 |
| [impl-plan-phase0.md](impl-plan-phase0.md) | Phase 0 可执行实施计划(逐任务 TDD,Linux/浏览器) |
| [impl-plan-phase1.md](impl-plan-phase1.md) | Phase 1 环形 HUD 前端实施计划 |
| [impl-plan-phase2a.md](impl-plan-phase2a.md) | Phase 2a Windows 原生 hermes + 远程语音实施计划 |
| [impl-plan-phase2c.md](impl-plan-phase2c.md) | Phase 2c Tauri 悬浮 HUD(M1 壳✅ → M2 文字往返 → M3 语音 → M4 打包) |
| [impl-plan-music-playback.md](impl-plan-music-playback.md) | Phase 4 在线音乐播放 + HUD 跟跳(M1 网关代理 → M2 播放 → M3 声纹核音乐模式 → M4 停/验收) |
| [roadmap.md](roadmap.md) | Phase 0→4 计划与状态 |
| [open-questions.md](open-questions.md) | 仍待拍板的事项 |
| [topics/music-vs-asr-isolation.md](topics/music-vs-asr-isolation.md) | 放歌不干扰 KWS/STT 的分层防御策略(Phase 4 硬约束) |
| [design-agent-orchestration.md](design-agent-orchestration.md) | **架构重构**:控制权倒转 = agent 编排 + 薄客户端(取代前端语义触发) |
| [impl-plan-agent-orchestration.md](impl-plan-agent-orchestration.md) | 上文设计的可执行实现计划(Phase 0 阻塞门 minimaxi tools → 后端工具 → skill → 薄客户端 → 真机) |
| [decisions/0001-audio-capture-location.md](decisions/0001-audio-capture-location.md) | 为何音频在前端采集,而非 Python 主机 |
| [decisions/0002-shell-and-visuals.md](decisions/0002-shell-and-visuals.md) | Tauri v2 外壳 + WebGL HUD |
| [decisions/0003-activation-wake-word.md](decisions/0003-activation-wake-word.md) | 唤醒方式 = 喊它名字 |
| [decisions/0004-linux-first-milestone.md](decisions/0004-linux-first-milestone.md) | 首个里程碑 = 先在 Linux 浏览器内跑通 |
| [decisions/0005-windows-native-agent-deployment.md](decisions/0005-windows-native-agent-deployment.md) | agent 原生上 Windows 操控本机;STT/TTS 当 Linux API;GUI 用 clawtouch |
| [decisions/0006-music-playback-in-webview.md](decisions/0006-music-playback-in-webview.md) | 在线音乐在 webview 内播(网关同源代理)让声纹核跟跳;否决 mpv |

## 已确认约束(来自用户)
- 最终运行目标:**Windows**(hermes 在 WSL2 里;HUD 连 localhost)。开发机:**Linux**。
- 视觉:漂亮的、带动态效果的**贾维斯风格 HUD**。
- 交互模型:**喊名字"贾维斯"** —— 桌面待机,喊名字唤醒,说话,它用语音回复。
- 唤醒引擎:**openWakeWord**(训练自定义中文热词,本地、免费)。
