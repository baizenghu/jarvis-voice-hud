# 设计:控制权倒转 —— agent 编排 + 薄客户端

日期:2026-06-12。状态:设计成稿,待写实现计划。
> 本文是 Phase 4 之上的**架构重构设计**,经 brainstorming 逐节确认。它**取代**前期"前端意图识别/标记"那套触发(见 [decisions/0006](decisions/0006-music-playback-in-webview.md) 仍管 webview 播放+中心中转,**只换触发层**)。

## 背景与问题
现架构是**反的**:前端 `hud-app/hud/src/main.ts` 当大脑——跑对话循环、正则判"退下"、判音乐意图、决定是否继续听;
agent(MiniMax)只是埋在 `submitPrompt` 里一次"文本进文本出"的调用。后果:每加一种语义(放歌、同音字、
多样说法)都要在前端打正则补丁(已暴露:"放首"被 whisper 转成"放手"导致正则失配)。中文语义本就是 LLM 的活。

## 决策
**STT 之后把文本交给 agent 当编排者**,由它判断该不该答、放不放歌、何时结束;前端退化成**薄客户端**(纯 I/O + 执行器)。
- **唤醒分工**:KWS(本地轻量、一直听)仍当**廉价门**,听到"贾维斯"→ `POST /api/wake` 开门;**之后全部交给 agent**。
  (否决"把环境声常开喂 LLM 判唤醒"——成本/延迟/GPU 12G 红线。)
- **范围**:一步到位完整倒转;首个跑通能力 = **重生的对话循环 + 音乐**(放/停/跟跳)。架构泛化:以后加能力 = 加 agent 工具。
- **机制 = agent 工具当执行器(Approach A)**,非"结构化回复契约"(后者不 agent-native,"操作电脑"那天要推倒重来)。

## 组件边界
| 组件 | 唯一职责 | 不做 |
|------|---------|------|
| KWS 监听器(独立进程,不变) | 一直听,"贾维斯"→ `POST /api/wake` | 任何语义 |
| 薄客户端 HUD(前端,重写) | I/O+执行器:录音/VAD、播 TTS、播音乐+跳动、显隐;执行 agent 下发动作 | 不判退下/音乐/是否答(无语义) |
| Agent(网关内 hermes,成为大脑) | 收每轮文本→判断→调工具(放歌/停/结束)+ 出话 | —— |

## 数据流 / 对话生命周期
```
KWS──POST /api/wake──▶ 网关 ──event:wake──▶ HUD(进入会话,报 busy 抑制重触,播固定招呼)
loop:
  listen:录音 + VAD 静音端点 + 回声门控 + 纯静音丢弃(不送 STT)
    └ 若音乐在放,listen 窗内 duckForSpeech 压音乐保 STT
  → voice.transcribe → prompt.submit(文本) → 等这一轮
  轮内到达的动作事件入缓冲;message.complete 到 = 轮结束
  → TTS 念回复;按序应用缓冲动作:
       stop_music 立即;play_music 留到念完再播(不盖确认语);
       end_session → 念完隐身、报 idle、退出 loop
  否则接着 listen
```
- **谁决定结束**:agent(听懂"退下"或判断结束 → 调 `end_session`)。前端**删 `DISMISS_RE`**。
- **谁决定不答/误触**:agent(回空 / 调 end_session / 澄清)。
- **机械信号留前端**:VAD 静音端点、回声门控、纯静音丢弃、duckForSpeech——是信号处理非语义,放 agent 徒增延迟/STT 成本。

## Agent 执行器工具(hermes `ToolRegistry.register`,toolset `voice_hud`)
| 工具 | 入参 | handler | 返回给 agent |
|------|------|---------|-------------|
| `play_music` | `query:string`(歌名/歌手;`""`=热门) | 推 `{type:"play_music",query}` 给 HUD | `"已开始播放: <query>"` |
| `stop_music` | 无 | 推 `{type:"stop_music"}` | `"已停止"` |
| `end_session` | 无 | 推 `{type:"end_session"}` | `"会话结束"` |

**无 `speak` 工具**:agent 要说的话走正常回复(`message.complete`),前端 TTS 念。工具只管动作。
**fire-and-forget**:工具推完即返回成功,agent 照常说"好,放晴天";播放失败由前端本地兜底,不阻塞 agent。

## Agent → HUD 动作事件协议(走现有 `/api/events`)
HUD 本就订阅 `/api/events`(收 wake)。统一动作事件(JSON):
```
{type:"wake"} {type:"play_music",query:"晴天"} {type:"stop_music"} {type:"end_session"}
```
- **接线**(writing-plans 第一件钉死):工具 handler 与 dev_server 同进程 → 直接 `hub.broadcast(event)`;
  若分进程 → 经 `/api/pub`(event_publisher 已有此路)。

## play-music skill(语义判断的归宿)
`skills/media/play-music/SKILL.md` —— 教 agent 何时/怎么调 `play_music`(纠正同音字、抽真实歌名、未指定→query=""、想停→stop_music;调完用一句口语确认)。
工具 schema 自带简短描述(每轮可见),skill 是详细 playbook(按相关性加载)。
**SOUL.md 指针先不加**:靠工具描述+skill;真机测出短指令漏调工具,再在 `~/hermes-home/SOUL.md` 加一行。

## 错误处理
- agent 一轮超时/无 message.complete → 前端**加超时**(现无限等),超时念"没听清,再说一次?"回 listen。
  (**前端自主说话仅限两处**:wake 固定招呼 + 此超时兜底;其余话全由 agent 出。)
- play_music 播放失败(resolve 502/解码)→ 前端本地兜底:界面提示+日志,不自主说话,会话继续。
- end_session + 同轮 play_music → 先播再隐身;**隐身不停音乐**(音乐元素与 overlay 可见性解耦)→ 退下后音乐继续。
- KWS 会话期过敏重触 → 整会话报 busy 抑制(扩展现有 per-turn busy 到 whole-session)。
- 网关重启 → rpc.ts/connectEvents 已有自动重连,保留。

## 测试
- 前端单测(vitest):动作事件→handler 分发;**轮内动作缓冲与排序**(play 延到 TTS 后)用 mock;VAD/静音/回声。删 parseMusicDirective 测试。
- 后端单测(pytest):三工具 handler 推正确事件(mock hub.broadcast);/api/music 代理(现有保留)。
- 真机验收门(家里):喊贾维斯→"放首晴天"→agent 调 play_music→出声+跳动;"退下"→end_session→隐身。
- ⚠️ **头号风险 = 工具调用可靠性**:MiniMax-M3 对短语音指令能否**稳定调 play_music**。只能真机测;不稳→强化工具描述/加 SOUL 指针。

## 迁移路径
- 新分支 `feat/voice-hud-agent-orchestration` 做;现 Phase 3 loop 在 git 可回退。
- 后端:加三工具+注册进网关 agent+事件发射;前端:重写会话驱动器、删语义代码(`DISMISS_RE`/`parseMusicIntent`/`parseMusicDirective`/`handleMusic`);加 play-music skill。
- **保留不动**:`/api/music` 代理 + `MUSIC_UPSTREAM` 中转、`AudioEngine`(playMusic/stopMusic/duckForSpeech/getBands)、`RingHud` 音乐态、VAD/录音/回声。
- 前期 4 个音乐提交:执行器部分留用,语义触发部分被本设计取代——非白费。
- 招呼:wake 时前端发固定句(快、非语义),不为打招呼跑 agent。

## YAGNI / 不做
- 不做"操作电脑"工具(以后加工具即可)。不做 agent 知道播放成败的回推(fire-and-forget)。不预先改 SOUL.md。
