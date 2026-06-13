# 控制权倒转(agent 编排 + 薄客户端)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把语音 HUD 的控制权从前端正则编排倒转为 agent 工具编排——KWS 开门后,STT 文本交 agent,agent 调 `play_music`/`stop_music`/`end_session` 工具驱动薄客户端;首个能力 = 重生对话循环 + 在线音乐(放/停/跟跳)。

**Architecture:** 网关内 in-process AIAgent 注册 `voice_hud` 本地工具;工具 handler 经 in-process `WakeHub.broadcast` 把带 turn-id 的动作事件推到 HUD 的 `/api/events`;前端退化薄客户端,只录音/STT/TTS/播放+跳动/执行动作,无语义判断。设计见 [design-agent-orchestration.md](design-agent-orchestration.md)。

**Tech Stack:** Python(FastAPI dev_server、tui_gateway、tools/registry)、TypeScript/Vite(hud 前端)、hermes 自定义 provider(MiniMax-M3 走 chat_completions/OpenAI 工具格式)。

**分支:** `feat/voice-hud-agent-orchestration`(新分支,现 Phase 3 loop 可回退)。

**复核:** 经 Codex 审查 + 代码核实修正(2026-06-13):schema 须 `{description,parameters}`、handler 收 `(args,**kw)`、`safe_schedule_threadsafe(coro,loop)` loop 必传、voice_hud 须并进 `enabled_toolsets`、turn-id 移除改串行+clear/drain、0.2 产出可执行 contract 测试、新增 0.3 全链路工具调用闸门、关键触发规则进工具 description。

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

- [ ] **Step 4: 产出可执行 contract 测试(非笔记)+ commit**

不只写附录笔记——写一个 `tests/test_voice_hud_contract.py`,断言已核实的契约,作为 Phase 1 骨架替换前的护栏:
```python
# 断言契约成立,任一处变了就红
def test_register_and_definition_shape():
    import sys; sys.path.insert(0,"hud-app"); import dev_server  # 触发注册
    from model_tools import get_tool_definitions
    defs = get_tool_definitions(enabled_toolsets=dev_server._enabled_toolsets_for_session())
    fn = next(d["function"] for d in defs if d["function"]["name"] == "play_music")
    assert fn["parameters"]["properties"]["query"]["type"] == "string"   # parameters 层级正确
```
Run: `.venv/bin/python -m pytest tests/test_voice_hud_contract.py -v` → 通过即契约锁定。附录同步写明 register 模板/handler 签名/schema 形状/toolset 启用点/loop 注入。

---

### Task 0.3: 全链路工具调用 smoke(curl 不够,验 hermes 适配器+registry+toolset 组合)

**Files:** 临时脚本,不入库。

- [ ] **Step 1: 真实路径发一次 prompt,确认产生 tool call**

0.1 的 curl 只验 minimaxi 端点;还要验 **hermes chat_completions 适配器 + registry schema + enabled_toolsets 三者组合后真把工具发给模型、且模型回 tool call**。
注册好 voice_hud 工具后(Phase 1 Task 1.3 完成后回跑此 smoke),起 dev_server,经 `/api/ws` 发 `prompt.submit`("放首晴天"),抓 hermes 发往 minimaxi 的请求体确认含 `tools`,且响应/回合产生 `play_music` tool call(可临时让 `_safe_emit` 打日志观测)。
Run: 裸测脚本 `ws_tool_smoke.py`(仿 `hud-app/ws_smoke.py`)→ 观测到 play_music handler 被触发。
- 触发 → 全链路通,Phase 3/4 可放心铺。
- 未触发 → 在进前端前先解决(toolset 没进 / schema 错 / 模型不调),**别带病往下**。

> 顺序:Task 0.1(端点能力)先行;0.2/0.3 的"真实路径"部分依赖 Phase 1 Task 1.1-1.3 完成 → 0.3 实际在 Phase 1 后、Phase 3 前作为闸门跑。0.2 的 contract 测试在 Task 1.3 后即可跑。

---

## Phase 1 — 后端:voice_hud 工具 + 事件广播

### Task 1.1: WakeHub 扩展 broadcast + turn 计数

**Files:**
- Modify: `hud-app/dev_server.py`(WakeHub 类)
- Test: `tests/test_wake_hub.py`

> **turn-id 已移除**(Codex 复核):原计划在 `set_busy(True)` 自增 turn,但整会话只 busy 一次→turn 不随多轮 prompt 走,隔离不了迟到动作。会话内 prompt.submit **本就串行**(前端 await message.complete 再听下一轮),改用"录音起始清缓冲 + complete 后 drain"即可(见 Task 3.x),WakeHub 不需要 turn。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_wake_hub.py 追加
def test_broadcast_emits_to_clients():
    ds = _load()
    hub = ds.WakeHub()
    sent = []
    class FakeWS:
        async def send_json(self, m): sent.append(m)
    hub.clients.add(FakeWS())
    import asyncio
    n = asyncio.get_event_loop().run_until_complete(hub.broadcast({"type": "play_music", "query": "晴天"}))
    assert sent[-1] == {"type": "play_music", "query": "晴天"}
    assert n == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_wake_hub.py::test_broadcast_emits_to_clients -v`
Expected: FAIL(`WakeHub` 无 `broadcast`)。

- [ ] **Step 3: 实现 broadcast**

在 `WakeHub` 加(沿用现有 clients 清理模式):
```python
    async def broadcast(self, event: dict) -> int:
        """Push an action event to all HUD /api/events clients. Returns live client count."""
        dead = []
        for c in self.clients:
            try:
                await c.send_json(dict(event))
            except Exception:
                dead.append(c)
        for c in dead:
            self.clients.discard(c)
        return len(self.clients)
```

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

# handler 签名须为 (args, **kw):registry.dispatch 调 handler(args, **kwargs),
# 会带 task_id 等 kw,单参 handler 会 TypeError。(已核实 registry.py dispatch)
def play_music_handler(args: dict, **kw) -> str:
    query = (args.get("query") or "").strip()
    _broadcast({"type": "play_music", "query": query})
    return f"已开始播放: {query or '热门音乐'}"

def stop_music_handler(args: dict, **kw) -> str:
    _broadcast({"type": "stop_music"})
    return "已停止"

def end_session_handler(args: dict, **kw) -> str:
    _broadcast({"type": "end_session"})
    return "会话结束"
```
测试调用同步桩 `m.play_music_handler({"query":"晴天"})` 仍可(kw 可省)。

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

在 `gateway_voice_patch.register()` 附近加。**schema 必须是 `{"description":..., "parameters":{...}}`**——
已核实 `registry.get_definitions` 做 `{**entry.schema,"name":entry.name}` 当 OpenAI `function` 对象,
裸 JSON Schema 会让 type/properties 跑到 function 顶层、缺 `parameters`:
```python
import voice_hud_tools
from tools.registry import registry

def _register_voice_hud_tools() -> None:
    voice_hud_tools.set_broadcast(_safe_emit)   # _safe_emit 见 Step 2
    registry.register(
        name="play_music", toolset="voice_hud",
        schema={"description": "在语音 HUD 播放在线音乐(用户想听歌/换歌时调用)",
                "parameters": {"type": "object",
                    "properties": {"query": {"type": "string", "description": "歌名或歌手,空=热门"}},
                    "required": ["query"]}},
        handler=voice_hud_tools.play_music_handler,
        description="在语音 HUD 播放在线音乐(用户想听歌/换歌时调用)")
    registry.register(name="stop_music", toolset="voice_hud",
        schema={"description": "停止音乐播放", "parameters": {"type": "object", "properties": {}}},
        handler=voice_hud_tools.stop_music_handler, description="停止音乐播放")
    registry.register(name="end_session", toolset="voice_hud",
        schema={"description": "结束本次语音对话、HUD 隐身(用户说退下/再见时调用)",
                "parameters": {"type": "object", "properties": {}}},
        handler=voice_hud_tools.end_session_handler,
        description="结束本次语音对话、HUD 隐身(用户说退下/再见时调用)")

_register_voice_hud_tools()
```
**enabled_toolsets 启用(关键,已核实)**:agent 用 `enabled_toolsets=_load_enabled_toolsets()`(读 HERMES_TUI_TOOLSETS/CLI 配置,有则不含 voice_hud)→ 仅 register **不等于**进 agent.tools。两种启用法,二选一(Task 0.2 定):
- 简单:dev_server 启动设 `os.environ["HERMES_TUI_TOOLSETS"]` 在现有值基础上**追加** `voice_hud`(别覆盖);
- 或在构建该会话 agent 处把 `voice_hud` 合并进 `enabled_toolsets`。

- [ ] **Step 2: 实现线程安全广播 `_safe_emit`(loop 必传)**

已核实签名 `safe_schedule_threadsafe(coro, loop, *, ...)`,**loop 必传**。dev_server 启动时捕获 uvicorn 主 loop:
```python
import asyncio
from agent.async_utils import safe_schedule_threadsafe

_main_loop: asyncio.AbstractEventLoop | None = None

@app.on_event("startup")
async def _capture_loop() -> None:
    global _main_loop
    _main_loop = asyncio.get_running_loop()

def _safe_emit(event: dict) -> None:
    safe_schedule_threadsafe(hub.broadcast(event), _main_loop)
```

- [ ] **Step 3: 集成 smoke——证明工具进入 agent.tools(不只是注册成功)**

裸测 `registry.get_all_tool_names()` 只证注册、不证 toolset 过滤后模型可见。改为对**真实会话 agent** 断言:
Run: `.venv/bin/python -c "import sys; sys.path.insert(0,'hud-app'); import dev_server; from model_tools import get_tool_definitions; defs=get_tool_definitions(enabled_toolsets=dev_server._enabled_toolsets_for_session()); names=[d['function']['name'] for d in defs]; print('play_music' in names, 'parameters' in (next(d['function'] for d in defs if d['function']['name']=='play_music')))"`
Expected: `True True`(play_music 在 agent 工具清单里,且 function.parameters 结构正确)。
（`_enabled_toolsets_for_session` = Step 1 启用法对应的 helper;若用环境变量法则直接 `_load_enabled_toolsets()`。）

- [ ] **Step 4: Commit**

```bash
git add hud-app/dev_server.py
git commit -m "feat(voice-hud): 注册 voice_hud 工具进网关 agent + 线程安全广播"
```

---

## Phase 2 — play-music skill

> **稳定触发靠工具 description(每轮可见),skill 是补充**(Codex 复核):skill 仅在按相关性进 prompt 时生效,短语音指令未必触发它;但工具 description("用户想听歌/换歌时调用")每轮都在 agent 工具清单里。故关键"何时调"规则放在 Task 1.3 的 `play_music` schema description,skill 提供同音纠错/抽歌名等 playbook 细节。Task 4.1 验收须确认**无需显式 `/play-music` 也能稳定调工具**。

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

- [ ] **Step 1: session.ts 加 ActionBuffer(clear + drain,无 turn-id;先测)**

turns 串行 → 无需 turn-id;靠"录音起始 `clear()` 丢弃上一轮 straggler + complete 后 `drain()`"。测试:
```typescript
import { ActionBuffer } from "./session.ts";
it("clear 丢弃上一轮残留,drain 返回当前轮(已排序)", () => {
  const b = new ActionBuffer();
  b.push({ type: "end_session" });
  b.push({ type: "play_music", query: "a" });
  b.clear();                                   // 模拟新一轮录音起始
  b.push({ type: "end_session" });
  b.push({ type: "play_music", query: "b" });
  expect(b.drain().map((x) => x.type)).toEqual(["play_music", "end_session"]); // 排序 + 只当前轮
  expect(b.drain()).toEqual([]);               // drain 后清空
});
```
实现:
```typescript
export class ActionBuffer {
  private buf: Action[] = [];
  clear(): void { this.buf = []; }
  push(ev: Action): void { this.buf.push(ev); }
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

把会话循环抽成**可注入依赖**的纯函数 `runSession(deps)`(deps = {listen, submitPrompt, speak, playMusic, stopMusic, setHudVisible, reportState, sleep, buffer, timeoutMs}),便于 fake-timer 测试:
```typescript
// session.ts:可注入的会话循环
export async function runSession(d: SessionDeps): Promise<void> {
  d.reportState("busy"); d.setHudVisible(true);
  await d.speak(d.pickGreeting());          // 固定招呼(前端自主说话之一)
  try {
    for (;;) {
      d.buffer.clear();                     // 录音起始:丢弃上一轮 straggler 动作
      const text = await d.listen();        // 复用现有录音/VAD/回声/静音逻辑
      if (text == null) continue;           // 无人声/回声:继续听(结束由 agent 决定)
      const reply = await withTimeout(d.submitPrompt(text), d.timeoutMs);
      if (reply === TIMEOUT) { await d.speak("没听清,再说一次?"); continue; }
      await d.speak(reply);                 // 念 agent 回复(message.complete 文本)
      await d.sleep(50);                     // 排空窗:收尾随动作事件
      let ended = false;
      for (const act of d.buffer.drain()) {
        if (act.type === "stop_music") d.stopMusic();
        else if (act.type === "play_music") await d.playMusic(act.query);
        else if (act.type === "end_session") ended = true;
      }
      if (ended) break;
    }
  } finally { d.setHudVisible(false); d.reportState("idle"); }  // busy 在此清(整会话结束)
}
```
`main.ts` 只负责装配 deps(真 AudioEngine/rpc/事件订阅:`play_music`/`stop_music`/`end_session` → `buffer.push`),调 `runSession`。

- [ ] **Step 2b: 会话循环 fake-timer 测试(补主行为覆盖)**

`session.test.ts` 加(vitest `vi.useFakeTimers()` + 桩 deps):
```typescript
it("play 在念完确认后才执行,end_session 退出循环", async () => {
  const calls: string[] = [];
  const buffer = new ActionBuffer();
  let turn = 0;
  const d = stubDeps({
    listen: async () => (turn++ === 0 ? "放首晴天" : null),
    submitPrompt: async () => { buffer.push({type:"play_music",query:"晴天"}); buffer.push({type:"end_session"}); return "好,放晴天"; },
    speak: async (t) => { calls.push("speak:"+t); },
    playMusic: async (q) => { calls.push("play:"+q); },
    buffer,
  });
  await runSession(d);
  // 招呼→念回复→play→end:play 在 speak 之后,end_session 使其退出
  expect(calls).toEqual(["speak:<greeting>", "speak:好,放晴天", "play:晴天"]);
});
it("submitPrompt 超时 → 念提示并继续听,不崩", async () => { /* listen 第一轮触发超时,断言 speak('没听清…') 且进入下一轮 */ });
```
（`stubDeps` 提供默认桩 + 覆盖;`withTimeout` 用注入的 sleep/timer 以便 fake-timers 推进。)
Run: `cd hud-app/hud && npm test -- session` → PASS。

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
