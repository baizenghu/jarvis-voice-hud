# 决策 0007 —— agent 与系统彻底解耦:agent = 文本进 `{text,end}` 出的黑盒

日期:2026-06-13。状态:已采纳(待实施)。

> **取代** [design-agent-orchestration.md](../design-agent-orchestration.md) 的核心决策("STT 后把文本交给
> in-process agent 当**编排者/大脑**,agent 工具当执行器,经 in-process WakeHub 广播动作")。
> 那套把 agent 绑死在网关进程内(monkeypatch `_load_enabled_toolsets` + 共享全局 `WakeHub`),
> **无法替换 agent**;本决策反过来把 agent 降级成可插拔黑盒。design-agent-orchestration.md 里
> "语义全交 agent、前端正则已废"的方向**保留并强化**,被取代的只是"agent 是系统内嵌大脑"这一点。

## 背景:诉求是"换成任何 agent 框架"

用户要的是整套系统与 agent **解耦**——agent 可替换成自研、Codex、Claude Code、OpenClaw 等**任意框架**。
现状是反的:网关 in-process 构造 `AIAgent`(`tui_gateway/server.py:3071,3136,3162`),voice_hud 工具靠
`dev_server.py` 的运行期 `registry.register` + monkeypatch `_load_enabled_toolsets` 注入,handler 经
共享全局 `WakeHub.broadcast` 推动作。换 agent = 这一整套推倒重来。

### 多 agent 调研已证实(workflow `wf_06743372-854`,4 readers grounded 在代码)
- "**前端拥有对话 loop、agent 只当一轮应答器**"——**已经是现状**(`hud/src/voice/session.ts:66-104`
  runSession + `SessionDeps.submitPrompt`),不是要新建的能力。
- 前端**基本已 agent-agnostic**:legacy 语义解析(`DISMISS_RE`/`parseMusicIntent`)在 src+dist 已清零,
  只剩 `session.ts:7-13` 一处具名 Action。
- **放歌已经是 agent 的 skill 干的**(gequbao 独立浏览器),HUD 音乐跳动靠**监听声卡**(`audio_levels.py`),
  不靠 agent 告知 → "任务执行(含放歌/操作电脑)归 agent、贾维斯只读音频"本来就成立。
- `whisper_api.py:24` 硬 `import tools.voice_mode`,**不是独立 STT 服务**,是 hermes STT 的 HTTP 薄壳。
- 承载这一切的 `dev_server.py` 自称 *"Dev-only / not part of the shipped product"*;契约测试
  `test_voice_hud_contract.py` 与实现已不一致(assert `play_music/stop_music` 但后端只 `register('end_session')`)。

## 决策:agent 是 `文本 → {text, end?}` 的黑盒

```
语音 ─STT─▶ 文本 ─▶ [ agent 黑盒:内部用 mcp / skill 完成任务 ] ─▶ {text, end?} ─▶ TTS 念 text ─▶ 反馈
                     ↑ MCP、skill 是 agent 自己的能力,贾维斯不暴露、不感知、不参与
```

- **贾维斯系统 = 嘴和耳朵**:STT、TTS、HUD 动效、唤醒(KWS)、对话循环、机械信号(VAD/回声门控/
  静音丢弃/duck/busy 抑制)。这些是信号处理,不是语义。
- **agent = 脑和手**:拿到文本,**爱用什么 MCP / skill 去放歌、操作电脑都是它内部的事**,最后只还
  `{text, end?}`。
- **接口 = 文本进、`{text, end?}` 出**——所有 agent/LLM/框架的最小公约数。换 agent = 换一个"吃文本
  吐文本"的东西,不需要它懂任何贾维斯私有协议。

### 关键纠偏:MCP 不在边界上
曾考虑"贾维斯当 MCP server 暴露 say/play_music,agent 当 MCP client 连入"——**已否决**。
那样把贾维斯的能力塞进 agent 的工具空间,反而**耦合**。MCP/skill 是 **agent 自带的内部能力**,
不该和 agent 分开,也不该被贾维斯托管。贾维斯侧**没有** play_music/say 这类能力,只有 STT/TTS/loop。

### 返回值里为什么需要 `end`(唯一不进"纯文本"的一个 bit)
`文本→文本` 装不下"**退下/结束会话**"——它不是要念给用户的话,是要告诉**贾维斯**"别再听了,回待机"。
所以返回值是 `{text, end?}`:`text`=要念的口语;`end`=agent 语义判懂了"退下/再见/拜拜"后置的结束位。
**语义判断仍在 agent**(贾维斯不正则、不猜)。

## 回待机的两条路(任一触发即回)
1. **agent 返回 `end=true`** → 先念完 `text`,再回待机(保留"喊一声退下立刻消失"的即时感)。
2. **静音超时(贾维斯自管)** → 一轮已结束、在等用户开口时,N 秒无人说话 → 自动回待机。

两条逻辑不冲突,谁先触发谁生效。

## 三个必须守住的行为(否则踩已知坑)
1. **`end=true` 时先念完告别再隐身**——别在"好的,再见"还没念完就切待机。
2. **任何 TTS 期间保持 busy 抑制**——否则 TTS 尾音被 KWS 当唤醒词重触发(保留现有 240s 自愈 + cooldown)。
3. **静音超时 = "空闲超时"而非"硬超时"**——agent 还在干长任务(未返回)时不能误判静音回待机;
   计时只在"轮已结束、等用户开口"时跑。

## 落地细节:`end` 这个 bit 怎么提取 = 适配器的事
agent 怎么表达 `end` 因家而异,**翻译归各自的薄适配器,贾维斯只认 `{text, end}`**:
- **自研**:直接返回 `{text, end}`。
- **hermes**:让它的 `end_session` 工具置这个 flag。
- **Codex / Claude Code**(只会吐文本):适配器把某个约定(如末尾 sentinel)翻译成 `end=true`。
- **OpenClaw**:它是 ②+③ 网关而非纯 agent,接入是另一档工程(见调研),非本决策首选适配器。

## 为何不采用 design-agent-orchestration 的"5 消息契约 / in-process 大脑"
- in-process 大脑(monkeypatch + 共享 `WakeHub`)**结构上不可换 agent**,与首要诉求冲突。
- 调研里那套自造 `session.start/turn/say/action/turn.end` 5 消息 WS 契约,在"agent=文本黑盒"下**多余**:
  放歌等动作是 agent 内部 skill,不需要 say/action 出现在边界;边界只剩 `文本 → {text,end}`,更简单。

## 已知风险 / 未决(迁移时处理,详见 [impl-plan-agent-decoupling.md](../impl-plan-agent-decoupling.md))
- 🔴 **链路零鉴权 + agent 跑 `HERMES_YOLO_MODE=1` + terminal 工具集**:谁连到端口 = 拿无审批 shell。
  绑非 localhost(WireGuard/LAN)前必须加入站鉴权。
- 🔴 **无 say/text 分离**:agent raw 文本(markdown/代码块/URL)直灌 TTS;接 chatty agent(Codex/CC)
  会逐字念星号反引号。TTS 入口需 sanitizer + agent 侧 voice 提示。
- 🟠 **TTS 流式 / 长任务进度 / 打断(barge-in)/ agent 主动说话**:`文本→{text,end}` 这条请求-响应
  边界**装不下**这几样,需另开一条贾维斯→agent 的下行旁路或接受妥协;**不在本决策范围**,留作后续。
- ⚠️ **静音超时与 busy 抑制的跨进程超时常量**(前端 `SESSION_TIMEOUT_MS` 与后端 `BUSY_MAX_S=240`)
  须重新对齐。
- ⚠️ **出货 Tauri 路径 vs `dev_server` harness 的差异**:契约必须以出货路径为基线核对。
