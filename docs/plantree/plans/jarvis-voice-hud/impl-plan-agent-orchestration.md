# 控制权倒转(agent 编排 + 薄客户端)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把语音 HUD 的控制权从前端正则编排倒转为 agent 工具编排——KWS 开门后,STT 文本交 agent,agent 调 `play_music`/`stop_music`/`end_session` 工具驱动薄客户端;首个能力 = 重生对话循环 + 在线音乐(放/停/跟跳)。

**Architecture:** 网关内 in-process AIAgent 注册 `voice_hud` 本地工具;工具 handler 经 in-process `WakeHub.broadcast` 把带 turn-id 的动作事件推到 HUD 的 `/api/events`;前端退化薄客户端,只录音/STT/TTS/播放+跳动/执行动作,无语义判断。设计见 [design-agent-orchestration.md](design-agent-orchestration.md)。

**Tech Stack:** Python(FastAPI dev_server、tui_gateway、tools/registry)、TypeScript/Vite(hud 前端)、hermes 自定义 provider(MiniMax-M3 走 chat_completions/OpenAI 工具格式)。

**分支:** `feat/voice-hud-agent-orchestration`(新分支,现 Phase 3 loop 可回退)。

---

## 文件结构

| 文件 | 角色 | 动作 |
|------|------|------|
| `hud-app/voice_hud_tools.py` | 新:`voice_hud` toolset 三工具(play_music/stop_music/end_session),handler 经回调推事件 | 创建 |
| `hud-app/dev_server.py` | `WakeHub` 扩展 `broadcast(event)` + turn 计数;启动时注册 voice_hud 工具并注入广播回调 | 修改 |
| `tests/test_voice_hud_tools.py` | 后端:工具 handler 推出正确事件(mock 广播) | 创建 |
| `tests/test_wake_hub.py` | 扩展:broadcast/turn 行为 | 修改 |
| `skills/media/play-music/SKILL.md` | agent 何时/怎么调 play_music 的 playbook | 创建 |
| `hud-app/hud/src/voice/session.ts` | 新:薄客户端会话驱动器(动作事件分发 + 轮内缓冲/排序) | 创建 |
| `hud-app/hud/src/voice/session.test.ts` | 前端:事件分发 + play 先于 end_session 排序 + turn 过期丢弃 | 创建 |
| `hud-app/hud/src/main.ts` | 删语义代码(DISMISS_RE/parseMusicIntent/parseMusicDirective/handleMusic),接 session 驱动器 | 修改 |
| `hud-app/hud/src/voice/audio.ts` | 删 `parseMusicDirective`;保留 playMusic/stopMusic/duckForSpeech/getBands | 修改 |
| `hud-app/hud/src/voice/audio.test.ts` | 删 parseMusicDirective 测试 | 修改 |

---

## Phase 0 — 阻塞式 de-risk(不过不继续)

### Task 0.1: 验证 minimaxi 端点支持 OpenAI tools 函数调用

**Files:** 仅临时脚本,不入库。

- [ ] **Step 1: 打一个真 tools 请求**

在中心(能联网)跑(key 从家里 config 读,勿硬编码进库):
```bash
# 仅本地验证,key 用环境变量传,别写进文件/提交
curl -s https://api.minimaxi.com/v1/chat/completions \
  -H "Authorization: Bearer $MINIMAX_KEY" -H "Content-Type: application/json" \
  -d '{"model":"MiniMax-M3","messages":[{"role":"user","content":"放首周杰伦的晴天"}],
       "tools":[{"type":"function","function":{"name":"play_music",
         "description":"播放在线音乐","parameters":{"type":"object",
         "properties":{"query":{"type":"string"}},"required":["query"]}}}],
       "extra_body":{"thinking":{"type":"disabled"}}}' | python3 -m json.tool | head -40
```

- [ ] **Step 2: 判定**

Expected(通过):响应含 `tool_calls`,其中 `function.name=="play_music"`、`arguments` 含 `query`(类似"晴天"/"周杰伦 晴天")。
- **通过** → 整方案前提成立,继续 Phase 1。
- **不支持 tools / 报错 / 不返回 tool_calls** → **停**,升级给用户:换支持工具的 provider/模型(设计风险节的 Claude Haiku 兜底),不要往下做。

- [ ] **Step 3: 记录结论**

把判定结果(支持/不支持 + 样例响应片段)追加到 design-agent-orchestration.md 的风险节,commit。

### Task 0.2: 钉死工具集成契约(读码,不写实现)

**Files:** 仅产出契约笔记(写进本计划末尾"契约"附录,commit)。

- [ ] **Step 1: 读 handler/schema 约定**

读一个已有内建工具确认精确约定:
Run: `sed -n '1,60p' tools/computer_use_tool.py; sed -n '860,900p' tools/cronjob_tools.py`
提取:① `registry.register(...)` 的 `schema` 字段精确形状(是否 OpenAI function schema、含 name/description/parameters);② `handler(...)` 收什么参数(params dict?如何取 `query`);③ 返回值类型(用 `tools/registry.py` 的 `tool_result`/`tool_error`)。

- [ ] **Step 2: 读 toolset 如何对网关 agent 生效**

Run: `grep -rn "toolset\|enabled_toolsets\|get_definitions\|allowed" tui_gateway/server.py agent/agent_init.py | head -20`
提取:`voice_hud` toolset 要怎样才会被 in-process agent 纳入工具清单(自动全量?还是需在某允许列表/config 里启用?)。**这决定 Task 1.3 的接入点。**

- [ ] **Step 3: 读如何从工具 handler 够到 dev_server 的 WakeHub**

确认 handler 与 dev_server 同进程(已核实 in-process agent),设计接入方式:dev_server 启动时把 `hub.broadcast` 作为回调注入 `voice_hud_tools`(模块级 setter),handler 调用它。确认 `safe_schedule_threadsafe` 用法:
Run: `grep -n "safe_schedule_threadsafe" tui_gateway/ws.py agent/async_utils.py`

- [ ] **Step 4: 把契约写进本文件附录并 commit**

附录写明:register 调用模板、handler 签名、schema 形状、toolset 启用点、广播回调注入方式。后续 Phase 1 严格按此写。

---

## Phase 1 — 后端:voice_hud 工具 + 事件广播

### Task 1.1: WakeHub 扩展 broadcast + turn 计数

**Files:**
- Modify: `hud-app/dev_server.py`(WakeHub 类)
- Test: `tests/test_wake_hub.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_wake_hub.py 追加
def test_broadcast_increments_turn_and_emits():
    ds = _load()
    hub = ds.WakeHub()
    sent = []
    class FakeWS:
        async def send_json(self, m): sent.append(m)
    hub.clients.add(FakeWS())
    import asyncio
    t1 = asyncio.get_event_loop().run_until_complete(hub.broadcast({"type": "play_music", "query": "晴天"}))
    assert sent[-1]["type"] == "play_music"
    assert sent[-1]["query"] == "晴天"
    assert "turn" in sent[-1] and isinstance(sent[-1]["turn"], int)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_wake_hub.py::test_broadcast_increments_turn_and_emits -v`
Expected: FAIL(`WakeHub` 无 `broadcast`)。

- [ ] **Step 3: 实现 broadcast**

在 `WakeHub` 加(沿用现有 clients 清理模式):
```python
    async def broadcast(self, event: dict) -> int:
        """Push an action event to all HUD /api/events clients. Returns live client count."""
        payload = dict(event)
        payload.setdefault("turn", self.turn)
        dead = []
        for c in self.clients:
            try:
                await c.send_json(payload)
            except Exception:
                dead.append(c)
        for c in dead:
            self.clients.discard(c)
        return len(self.clients)
```
并在 `__init__` 加 `self.turn = 0`;在 `set_busy(True)` 时 `self.turn += 1`(每轮自增,供前端丢弃过期事件)。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_wake_hub.py -v`
Expected: PASS(含原有 gating 测试不回归)。

- [ ] **Step 5: Commit**

```bash
git add hud-app/dev_server.py tests/test_wake_hub.py
git commit -m "feat(voice-hud): WakeHub.broadcast + turn 计数(动作事件下发)"
```

### Task 1.2: voice_hud 三工具模块

**Files:**
- Create: `hud-app/voice_hud_tools.py`
- Test: `tests/test_voice_hud_tools.py`

> 按 Task 0.2 契约写 register/handler/schema 的精确形状;下方为结构骨架,Step 3 用契约填精确签名。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_voice_hud_tools.py
import importlib.util, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "hud-app"))

def _load():
    spec = importlib.util.spec_from_file_location(
        "voice_hud_tools", Path(__file__).parent.parent / "hud-app" / "voice_hud_tools.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def test_play_music_handler_broadcasts():
    m = _load()
    events = []
    m.set_broadcast(lambda e: events.append(e))   # 注入同步桩
    out = m.play_music_handler({"query": "晴天"})
    assert events == [{"type": "play_music", "query": "晴天"}]
    assert "晴天" in out          # 返回给 agent 的确认串

def test_stop_and_end_handlers_broadcast():
    m = _load(); events = []
    m.set_broadcast(lambda e: events.append(e))
    m.stop_music_handler({}); m.end_session_handler({})
    assert events == [{"type": "stop_music"}, {"type": "end_session"}]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_voice_hud_tools.py -v`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 实现工具模块**

```python
# hud-app/voice_hud_tools.py
"""voice_hud toolset: agent 调这些工具驱动 HUD(播放/停止/结束)。
handler fire-and-forget:推事件给 HUD 后即返回确认串,不等播放结果。"""
from typing import Callable

_broadcast: Callable[[dict], None] = lambda e: None  # dev_server 启动时注入

def set_broadcast(fn: Callable[[dict], None]) -> None:
    global _broadcast
    _broadcast = fn

def play_music_handler(params: dict) -> str:
    query = (params.get("query") or "").strip()
    _broadcast({"type": "play_music", "query": query})
    return f"已开始播放: {query or '热门音乐'}"

def stop_music_handler(params: dict) -> str:
    _broadcast({"type": "stop_music"})
    return "已停止"

def end_session_handler(params: dict) -> str:
    _broadcast({"type": "end_session"})
    return "会话结束"
```
（注:handler 入参/返回若 Task 0.2 契约不同,按契约调整,但保持 set_broadcast 注入点不变。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_voice_hud_tools.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add hud-app/voice_hud_tools.py tests/test_voice_hud_tools.py
git commit -m "feat(voice-hud): voice_hud 三工具 handler(fire-and-forget 推事件)"
```

### Task 1.3: 注册工具进网关 agent + 注入广播回调

**Files:**
- Modify: `hud-app/dev_server.py`(启动处)

> 按 Task 0.2 契约的 register 模板 + toolset 启用点。

- [ ] **Step 1: 注册 + 注入(dev_server 启动)**

在 `gateway_voice_patch.register()` 附近加:
```python
import voice_hud_tools
from tools.registry import registry  # 路径以 Task 0.2 确认为准

def _register_voice_hud_tools() -> None:
    voice_hud_tools.set_broadcast(lambda e: _safe_emit(e))   # _safe_emit 见 Step 2
    registry.register(
        name="play_music", toolset="voice_hud",
        schema={"type": "object", "properties": {"query": {"type": "string",
                "description": "歌名或歌手,空=热门"}}, "required": ["query"]},
        handler=voice_hud_tools.play_music_handler,
        description="在语音 HUD 播放在线音乐(用户想听歌/换歌时调用)")
    registry.register(name="stop_music", toolset="voice_hud",
        schema={"type": "object", "properties": {}},
        handler=voice_hud_tools.stop_music_handler, description="停止音乐播放")
    registry.register(name="end_session", toolset="voice_hud",
        schema={"type": "object", "properties": {}},
        handler=voice_hud_tools.end_session_handler, description="结束本次语音对话、HUD 隐身(用户说退下/再见时调用)")

_register_voice_hud_tools()
# 若 Task 0.2 显示 toolset 需显式启用,在此把 "voice_hud" 加进 agent 的 enabled toolsets。
```

- [ ] **Step 2: 实现线程安全广播 `_safe_emit`**

handler 可能在线程池跑,需把异步 `hub.broadcast` 投回事件循环:
```python
def _safe_emit(event: dict) -> None:
    from agent.async_utils import safe_schedule_threadsafe   # 以 Task 0.2 确认为准
    safe_schedule_threadsafe(hub.broadcast(event))
```

- [ ] **Step 3: 裸测注册成功**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0,'hud-app'); import dev_server; from tools.registry import registry; print('play_music' in registry.get_all_tool_names())"`
Expected: `True`。

- [ ] **Step 4: Commit**

```bash
git add hud-app/dev_server.py
git commit -m "feat(voice-hud): 注册 voice_hud 工具进网关 agent + 线程安全广播"
```

---

## Phase 2 — play-music skill

### Task 2.1: 写 skill + 装到家里

**Files:**
- Create: `skills/media/play-music/SKILL.md`

- [ ] **Step 1: 写 SKILL.md**

```markdown
---
name: play-music
description: 用户想听歌/放音乐/换歌/停止时,调 play_music / stop_music 工具在语音 HUD 播放
platforms: [linux, windows]
metadata:
  hermes:
    tags: [music, audio, voice-hud, playback]
---
# 播放音乐(语音 HUD)
用户想听歌/换歌时:调 `play_music(query=真实歌名)`。纠正同音错字("放手晴天"→晴天),
可带歌手("周杰伦 晴天")。没指定具体歌→`query=""`(放热门)。想停/别放了→`stop_music`。
听懂"退下/再见/不聊了"→`end_session`。
调完工具,再用一句口语确认(会被念出来),例:"好,这就放晴天。"
普通对话不要调这些工具。
```

- [ ] **Step 2: 装到家里 agent 的 skills 目录**

```bash
SSHPASS=baizh sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null baizh@10.8.0.3 \
  'mkdir -p ~/hermes-home/skills/media/play-music'
tar czf - -C /home/baizh/hermes-agent skills/media/play-music/SKILL.md | \
  SSHPASS=baizh sshpass -e ssh ... baizh@10.8.0.3 \
  'tar xzf - -C /tmp && cp /tmp/skills/media/play-music/SKILL.md ~/hermes-home/skills/media/play-music/'
```
（精确 ssh 串同本仓库既有部署命令;确认家里 `~/hermes-home/skills` 是 agent 实际扫描目录——已核实 `get_skills_dir()=HERMES_HOME/skills`。)

- [ ] **Step 3: Commit**

```bash
git add skills/media/play-music/SKILL.md
git commit -m "feat(voice-hud): play-music skill(agent 工具调用 playbook)"
```

---

## Phase 3 — 前端:薄客户端会话驱动器

### Task 3.1: 删前端语义代码

**Files:**
- Modify: `hud-app/hud/src/voice/audio.ts`、`audio.test.ts`、`hud-app/hud/src/main.ts`

- [ ] **Step 1: 删 audio.ts 的 parseMusicDirective + 其测试**

删 `audio.ts` 中 `MusicDirective`/`parseMusicDirective`;删 `audio.test.ts` 中 `parseMusicDirective` describe 块。**保留** playMusic/stopMusic/duckForSpeech/isMusicPlaying/getBands/bandLevels。

- [ ] **Step 2: 删 main.ts 语义代码**

删 `main.ts` 中:`parseMusicDirective` import、`applyMusicReply`/`handleMusic`、`DISMISS_RE`、`parseMusicIntent` 引用、wakeTurn 里的音乐 break 分支。(会暂时破坏编译,Task 3.3 重建。)

- [ ] **Step 3: 跑前端单测确认 audio 部分仍绿**

Run: `cd hud-app/hud && npm test -- audio`
Expected: audio.test 通过(无 parseMusicDirective 残留引用)。

- [ ] **Step 4: Commit**

```bash
git add hud-app/hud/src/voice/audio.ts hud-app/hud/src/voice/audio.test.ts hud-app/hud/src/main.ts
git commit -m "refactor(voice-hud): 删前端语义编排代码(移交 agent)"
```

### Task 3.2: 会话驱动器 — 动作事件分发 + 轮内排序(纯逻辑,先测)

**Files:**
- Create: `hud-app/hud/src/voice/session.ts`
- Test: `hud-app/hud/src/voice/session.test.ts`

- [ ] **Step 1: 写失败测试(纯排序/过期逻辑)**

```typescript
import { describe, expect, it } from "vitest";
import { orderActions, type Action } from "./session.ts";

describe("orderActions", () => {
  it("play_music 永远排在 end_session 之前", () => {
    const a: Action[] = [{ type: "end_session" }, { type: "play_music", query: "晴天" }];
    expect(orderActions(a).map((x) => x.type)).toEqual(["play_music", "end_session"]);
  });
  it("stop_music 保持在前,end_session 最后", () => {
    const a: Action[] = [{ type: "end_session" }, { type: "stop_music" }];
    expect(orderActions(a).map((x) => x.type)).toEqual(["stop_music", "end_session"]);
  });
});
```

- [ ] **Step 2: 跑确认失败**

Run: `cd hud-app/hud && npm test -- session`
Expected: FAIL(session.ts 不存在)。

- [ ] **Step 3: 实现 orderActions + 类型**

```typescript
// hud-app/hud/src/voice/session.ts
export type Action =
  | { type: "play_music"; query: string }
  | { type: "stop_music" }
  | { type: "end_session" };

// 确定性排序:end_session 永远最后(先把动作做完再结束/隐身)。
const RANK: Record<Action["type"], number> = { play_music: 0, stop_music: 0, end_session: 9 };
export function orderActions(actions: Action[]): Action[] {
  return [...actions].sort((x, y) => RANK[x.type] - RANK[y.type]);
}
```

- [ ] **Step 4: 跑确认通过**

Run: `cd hud-app/hud && npm test -- session`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add hud-app/hud/src/voice/session.ts hud-app/hud/src/voice/session.test.ts
git commit -m "feat(voice-hud): 会话驱动器动作排序(play 先于 end_session)"
```

### Task 3.3: 会话驱动器 — 接 main.ts(事件循环 + 轮内缓冲 + 执行)

**Files:**
- Modify: `hud-app/hud/src/main.ts`、`hud-app/hud/src/voice/session.ts`

- [ ] **Step 1: session.ts 加事件缓冲 + turn 过期丢弃(先测)**

测试(追加 session.test.ts):
```typescript
import { TurnBuffer } from "./session.ts";
it("丢弃 turn 过期的事件,只保留当前轮", () => {
  const b = new TurnBuffer();
  b.setTurn(5);
  b.push({ type: "play_music", query: "a", turn: 4 }); // 过期
  b.push({ type: "play_music", query: "b", turn: 5 });
  expect(b.drain().map((x: any) => x.query)).toEqual(["b"]);
});
```
实现:
```typescript
export class TurnBuffer {
  private turn = 0;
  private buf: (Action & { turn?: number })[] = [];
  setTurn(t: number): void { this.turn = t; }
  push(ev: Action & { turn?: number }): void {
    if (ev.turn != null && ev.turn < this.turn) return; // 过期丢弃
    this.buf.push(ev);
  }
  drain(): Action[] { const out = orderActions(this.buf); this.buf = []; return out; }
}
```
Run: `cd hud-app/hud && npm test -- session` → PASS。

- [ ] **Step 2: main.ts 重建为薄客户端会话驱动器**

接线(用既有 AudioEngine/RingHud/rpc/machine + 新 session):
- `/api/events` 订阅扩展:`wake`→进会话;`play_music`/`stop_music`/`end_session`→入 `TurnBuffer`。
- 会话循环:wake→报 busy(整会话)+ 固定招呼 TTS→loop{ `autoListen`(VAD/回声/静音丢弃/duckForSpeech)→`voice.transcribe`→`rpc.submitPrompt(text)` 等 message.complete→TTS 念回复→`buffer.drain()` 后**排空 50ms**再执行动作:stop_music 立即、play_music 念完后播、end_session→隐身退出 }。
- submitPrompt **加超时**(如 30s):超时念"没听清,再说一次?"回 listen。
- busy 仅在 end_session 执行完 / 超时恢复后清。

```typescript
// main.ts 关键骨架(替换原 wakeTurn/endTurn 编排)
async function runSession(): Promise<void> {
  reportState("busy"); setHudVisible(true);
  await speak(pickGreeting());            // 固定招呼(前端自主说话之一)
  try {
    for (;;) {
      const text = await autoListen();    // 复用现有录音/VAD/回声/静音逻辑
      if (text == null) continue;         // 无人声/回声:继续听(不结束——结束由 agent 决定)
      buffer.setTurn(/* 取本轮 turn:可用收到的事件 turn 或前端自增并随 submit 传 */);
      const reply = await withTimeout(rpc.submitPrompt(text), 30000);
      if (reply === TIMEOUT) { await speak("没听清,再说一次?"); continue; }
      await speak(reply);                 // 念 agent 回复(message.complete 文本)
      await sleep(50);                    // 排空窗:收尾随动作事件
      let ended = false;
      for (const act of buffer.drain()) {
        if (act.type === "stop_music") audio.stopMusic();
        else if (act.type === "play_music") await audio.playMusic(act.query);
        else if (act.type === "end_session") ended = true;
      }
      if (ended) break;
    }
  } finally { setHudVisible(false); reportState("idle"); }  // busy 在此清
}
```
（`turn` 协调:简单做法=前端不发 turn,直接信任本会话内事件;turn 过期丢弃主要防跨会话串扰。实现时若 submitPrompt 不暴露 turn,用"收到 message.complete 即 drain + 50ms"即可,TurnBuffer 的 turn 作防御性保留。)

- [ ] **Step 3: 类型检查 + build**

Run: `cd hud-app/hud && npm run build`
Expected: tsc 通过、vite build 成功。

- [ ] **Step 4: lint + 全前端单测**

Run: `cd hud-app/hud && npm run lint && npm test`
Expected: 全绿(session + audio + machine)。

- [ ] **Step 5: Commit**

```bash
git add hud-app/hud/src/main.ts hud-app/hud/src/voice/session.ts hud-app/hud/src/voice/session.test.ts
git commit -m "feat(voice-hud): 薄客户端会话驱动器(agent 编排,事件缓冲+排序+超时)"
```

---

## Phase 4 — 集成 + 真机验收

### Task 4.1: 部署家里 + 工具调用真机测

**Files:** 无(部署 + 验收)

- [ ] **Step 1: 部署**

推 `dev_server.py`/`voice_hud_tools.py`/`hud/src` 到家里(tar 连 hud/src,红线),重建 dist,重启网关(带 `MUSIC_UPSTREAM`)+ 重启 tauri 壳。按 HANDOFF ② 命令。

- [ ] **Step 2: 工具调用可靠性真机测(头号风险)**

喊"贾维斯"→说多种放歌说法各 5 次:"放首晴天" / "放手晴天" / "来点周杰伦" / "我想听七里香" / "随便放首歌"。
记录 agent 调 `play_music` 命中率。
- 命中率达标(如 ≥8/10)→ 通过。
- 不达标 → 按设计风险节:先加 SOUL.md 指针重测;仍不行→把本会话路由到 Claude Haiku(anthropic_messages)。

- [ ] **Step 3: 端到端验收门**

喊"贾维斯"→"放首晴天"→**agent 调 play_music**→出声 + 声纹核/背景跟跳;说"换一首"→换;说"退下"→**agent 调 end_session**→隐身、音乐继续。

- [ ] **Step 4: 回写 roadmap/HANDOFF**

把真机结果(命中率、是否走兜底模型)写进 roadmap;更新 HANDOFF 现状。

---

## 契约附录(Task 0.2 产出后填)

> Task 0.2 完成后在此填:register 精确模板、handler 签名、schema 形状、`voice_hud` toolset 启用点、`safe_schedule_threadsafe` 用法、家里 skills 扫描确认。Phase 1/3 严格按此。
