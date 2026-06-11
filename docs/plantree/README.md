# Plan Tree —— hermes-agent

本仓库 plan-tree 管理的规划入口。

## 权威顺序
1. 本 README(注册表 + 阅读指引)
2. `baseline/` —— 跨计划共享的项目基础上下文
3. `plans/<name>/` —— 具体计划根目录(每个计划以 roadmap 为持久真相)
4. `ideas/inbox.md` —— 未晋升前都是非承诺想法

## 基础上下文(baseline)
- [baseline/voice-stack.md](baseline/voice-stack.md) —— 现有语音/音频子系统(STT、TTS、网关语音 RPC)。任何语音相关工作前先读它。

## 进行中的计划
| 计划 | 范围 | 状态 |
|------|------|------|
| [jarvis-voice-hud](plans/jarvis-voice-hud/README.md) | Windows 桌面悬浮"贾维斯"语音 HUD 助手 | 设计已成稿,待用户复核 |

## 阅读路径
从这里开始 → 相关 baseline 文件 → 计划的 `README.md` → 它的 `roadmap.md` → 仅按需读链接到的 design/decision/question 文件。
