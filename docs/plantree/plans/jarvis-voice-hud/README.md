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
| [roadmap.md](roadmap.md) | Phase 0→3 计划与状态 |
| [open-questions.md](open-questions.md) | 仍待拍板的事项 |
| [decisions/0001-audio-capture-location.md](decisions/0001-audio-capture-location.md) | 为何音频在前端采集,而非 Python 主机 |
| [decisions/0002-shell-and-visuals.md](decisions/0002-shell-and-visuals.md) | Tauri v2 外壳 + WebGL HUD |
| [decisions/0003-activation-wake-word.md](decisions/0003-activation-wake-word.md) | 唤醒方式 = 喊它名字 |
| [decisions/0004-linux-first-milestone.md](decisions/0004-linux-first-milestone.md) | 首个里程碑 = 先在 Linux 浏览器内跑通 |

## 已确认约束(来自用户)
- 最终运行目标:**Windows**(hermes 在 WSL2 里;HUD 连 localhost)。开发机:**Linux**。
- 视觉:漂亮的、带动态效果的**贾维斯风格 HUD**。
- 交互模型:**喊名字"贾维斯"** —— 桌面待机,喊名字唤醒,说话,它用语音回复。
- 唤醒引擎:**openWakeWord**(训练自定义中文热词,本地、免费)。
