## 目标 / 成功标准

把贾维斯↔agent 的边界收敛成**文本进、`{text, end}` 出**:

- `end` 不再走 `WakeHub.broadcast({type:end_session})` 这条「带外动作事件」,而是搭在 agent 一轮应答的**返回值**里(即 gateway `message.complete` 事件的 `payload.end`)。
- 前端只认这一个边界:从 buffer 里 `end_session` action 改成读 `submitPrompt` 返回的 `{text, end}`;删掉 hermes 私有方言(`/api/events` 上的 `play_music`/`stop_music`/`end_session` action 三件套)。
- `end` 的提取归各 agent 的**薄适配器**;本阶段只交付 **hermes 适配器**(`end_session` 工具置 flag,而非广播)。
- **同一系列收口**顺带删 `play_music`/`stop_music` 端到端死路径(阶段 0 已定性「去、并入此处」)。

**纪律(贯穿)**:绝不一次性大改;expand-contract——后端**先双发**旧 `{type:end_session}` 广播 + 新 `payload.end`,前端 feature flag 切到读 `end`,**真机验收后**才删旧广播分支与前端方言。每步 red-first。改动跟随现有 monkeypatch / 注入风格,**不重命名 `tui_gateway/server.py` 内部**(走别名/包装层,风险已知)。

成功标准(可验证):
1. 单测:hermes 适配器在 `end_session` 被调用后,该轮 `message.complete` payload 带 `end=true`;未调用则 `end` 缺省(falsy)。
2. 单测:前端 `runSession` 在 `submitPrompt` 返回 `{text, end:true}` 时,**先念完 text 再退出循环**。
3. 契约测试重写为新边界守卫(轮返回含 `end`、`end→待机`;`play_music/stop_music` 对 agent 不可见且不在前端 action union)。
4. 真机:念「退下」→先念完告别再隐身;TTS 期间 busy 抑制不破;空闲超时不误触;end 排序(动作做完再结束)不回归。
5. `play_music`/`stop_music` 全链路删除后,`npm run build` + `pytest` + `vitest` 全绿。

---

## 现状锚点(file:line,已 grounded)

后端:
- `hud-app/voice_hud_tools.py:23-31`:`play_music_handler`/`stop_music_handler`(死)。
- `hud-app/voice_hud_tools.py:34-36`:`end_session_handler` = `_broadcast({"type":"end_session"})` + 返回「会话结束」。
- `hud-app/dev_server.py:191-214`:`_safe_emit` 注入 + `_register_voice_hud_tools()`(只注册 `end_session`,注释已说 play/stop 退役)。
- `hud-app/dev_server.py:228-245`:`_patch_enabled_toolsets` monkeypatch（本阶段**不动**,见决策/计划:去不掉)。
- `hud-app/dev_server.py:292-310`:`/api/events` WS(busy/idle 上报 + `WakeHub`)。
- `tui_gateway/server.py:747-751`:`_emit(event, sid, payload)` 是唯一出事件口子(`message.complete` 等都经它)。
- `tui_gateway/server.py:5495-5505`:构造 `payload={"text":raw,"usage":...,"status":...}` 后 `_emit("message.complete", sid, payload)`。**这是 `text` 的产出点,`end` 要在此并入。**
- `tui_gateway/server.py:5284 _run_prompt_submit` / `5031 prompt.submit`:一轮 agent 应答的执行体。

前端:
- `hud-app/hud/src/voice/session.ts:7-13`:`Action` union(三件套)+ `RANK`。
- `hud-app/hud/src/voice/session.ts:36-49`:`SessionDeps`(`submitPrompt: (text)=>Promise<string>`)。
- `hud-app/hud/src/voice/session.ts:66-104`:`runSession`——`drain()` 里 `end_session→ended=true→break`(:92-94)。
- `hud-app/hud/src/voice/rpc.ts:95-103`:`handleMessage` 收 `message.complete` 取 `payload.text`(:98)。
- `hud-app/hud/src/voice/rpc.ts:133-141`:`submitPrompt` 返回 `this.replyText`(纯 string)。
- `hud-app/hud/src/main.ts:140-148`:`connectEvents` 把 `play_music/stop_music/end_session` 推进 `actionBuffer`。
- `hud-app/hud/src/main.ts:350-362`:`runSession` 装配 deps。

测试 / smoke:
- `tests/test_voice_hud_contract.py`:现绿基线(断言 end_session 可见、play/stop 不可见、dispatch 广播 `{type:end_session}`)。
- `tests/test_voice_hud_tools.py`:含 `play_music_handler`/`stop_music_handler`/`end_session_handler` 广播单测。
- `hud-app/hud/src/voice/session.test.ts`:`orderActions`/`ActionBuffer`/`runSession` 用例(含 play+end 排序)。
- `hud-app/ws_tool_smoke.py:18`:监听 `play_music/stop_music/end_session`。

---

## 适配器接口定义(本阶段交付契约)

**贾维斯只认 `{text, end}`。** 边界对象:

```ts
// hud-app/hud/src/voice/session.ts —— 边界类型,贾维斯侧唯一认知
export interface AgentReply {
  text: string;       // 要念给用户的口语(沿用现有 message.complete payload.text)
  end?: boolean;      // agent 语义判懂「退下/再见」后置;true → 念完 text 再回待机
}
```

`SessionDeps.submitPrompt` 签名从 `(text)=>Promise<string>` 改为 `(text)=>Promise<AgentReply>`。

**适配器职责**(后端):把各家 agent 表达「结束」的方式翻译成 `payload.end`。hermes 的表达 = 调 `end_session` 工具;适配器把这一调用翻译成该轮 `message.complete.payload.end=true`。**语义判断仍在 agent**(贾维斯不正则)。其它家(自研直接返回 end;Codex/CC 末尾 sentinel)非本阶段,接口先留住。

---

## TDD 测试清单(red-first,每条断言什么)

### 后端

**T1(hermes 适配器:end flag 注入)** 新增 `tests/test_voice_hud_end_flag.py`：
- T1a:模拟一轮里 `end_session_handler` 被 dispatch 后,该轮 `message.complete` 的 payload 带 `end=true`。
  - 实现路径决定断言形态:适配器用「turn-scoped 标志 + `_emit` 包装」时,断言 = 调 `dev_server` 包装后的 `_emit("message.complete", sid, {"text":"好,再见"})` → 实际写出的 params.payload 含 `end=true`(因本轮 handler 置过 flag);**且 flag 在该轮发射后被清(下一轮不残留)**。
  - 断言「先 dispatch end_session → 再 emit message.complete」顺序下 end=true;反之(未 dispatch)end 缺省。
- T1b:`end_session_handler` 仍返回非空确认串(agent 拿到工具结果,避免它以为失败重试);**双发期**:仍调 `_broadcast({"type":"end_session"})`(旧路不动)。
- T1c(契约形状守卫):`message.complete` 的其余字段(text/usage/status/rendered)不被包装破坏。

**T2(契约测试重写)** 改 `tests/test_voice_hud_contract.py`：
- 保留:`end_session` 对 agent 可见;`play_music`/`stop_music` 不可见(收缩后这俩 handler 已删,断言「不在 names」自然成立)。
- 新增:dispatch `end_session` 在**新边界**下置 turn flag(收缩后)/ 双发期同时仍广播(展开期)。**展开/收缩两态各跑一次或用注释标明切换时机**——实现者按当前 commit 阶段调整断言。
- 删除:`test_dispatch_routes_to_handler` 里 `events == [{"type":"end_session"}]` 的硬断言要随「收缩删旧广播」一并改为断言 flag 置位。

**T3(tools 单测收缩)** 改 `tests/test_voice_hud_tools.py`：
- red-first:删 `test_play_music_handler_broadcasts`/`test_play_music_empty_query_means_popular`,`test_stop_and_end_handlers_broadcast` 改为只测 `end`。先让测试反映「play/stop handler 不存在」(import 该函数 → AttributeError),再删 handler 转绿。

### 前端

**T4(session.ts 新边界)** 改 `hud-app/hud/src/voice/session.test.ts`：
- 删 `orderActions`/`ActionBuffer` 关于 `play_music`/`stop_music`/`end_session` action 的用例(收缩)。
- 新增 `runSession`:`submitPrompt` 返回 `{text:"好,我退下了", end:true}` → calls == `["speak:<greeting>","speak:好,我退下了"]` 且**循环退出**(断言「先 speak 后退出」=「先念完告别再隐身」)。
- 新增:`{text:"在的", end:false/缺省}` → 不退出,继续下一轮。
- 保留并改写超时用例:超时返回兜底(实现里把 `TIMEOUT` 映射成 `{text:"没听清,再说一次?", end:false}`)。

---

## expand-contract 分步(每步可验证 / 可回退)

> 顺序按依赖:先后端双发(纯加,不破旧)→ 前端 flag 读新(默认仍走旧)→ 真机验收 → 收缩删旧 + 删音乐死路径(打成一个「音乐退出契约」commit)。

### 步骤 A —— 后端展开:hermes 适配器双发 `end`(纯加法,旧广播不动)
**改 `hud-app/dev_server.py` + `hud-app/voice_hud_tools.py`**(都在契约基线内,不碰 `server.py` 内部):
1. 在 `dev_server.py` 加 turn-scoped end 标志机制(跟随现有 monkeypatch 风格):
   - 用 `contextvars.ContextVar`(agent 工具 dispatch 与 emit 同线程/同任务上下文时最稳;若 dispatch 在线程池另起,退化为 `threading.local` 或以 `sid` 为 key 的 dict——实现者按 T1a 实测线程关系选,**测试先证同上下文**)。
   - 包装 `tui_gateway.server._emit`:当 `event=="message.complete"` 且本轮 flag 置位 → `payload = {**payload, "end": True}`,emit 后清 flag。包装在 `dev_server` 模块加载期安装(与 `_patch_enabled_toolsets` 同一处装配,monkeypatch `_gw._emit`)。
   - **理由**:`message.complete` 的 payload 在 `server.py:5495` 构造,不改 server.py 就拿不到产出点;包 `_emit` 是最小侵入、与既有 `_load_enabled_toolsets` 包装同构的做法。
2. `voice_hud_tools.end_session_handler`:**双发**——既调注入的「置 flag」回调(新),又保留 `_broadcast({"type":"end_session"})`(旧)。新增第二个注入点 `set_end_flag(fn)`(对称 `set_broadcast`),由 `dev_server` 注入「置 contextvar」函数。
- 验证:T1 绿;契约/tools 测试不回归;后端单独跑 `pytest tests/test_voice_hud_*.py` 绿。**此步后旧前端完全不受影响**(广播照旧)。

### 步骤 B —— 前端展开:rpc 透传 `end` + feature flag 切 runSession 读新
**改 `rpc.ts` / `session.ts` / `main.ts`**:
1. `rpc.ts`:`handleMessage`(:97-101)收 `message.complete` 时除 `replyText` 再存 `replyEnd = payload?.end ?? false`;`submitPrompt`(:133-141)返回 `{text, end}`(`AgentReply`)。`replyText/replyEnd` 在 `awaitingReply` 起始清零。
2. `session.ts`:`SessionDeps.submitPrompt` 改返回 `AgentReply`;`runSession`(:79-98)`reply` 解构 `{text, end}`:超时 → `{text:"没听清…", end:false}`;`await speak(text)` 后 `if (end) break`(**先念后退**)。
3. **feature flag**:`main.ts` 顶部加 `const USE_REPLY_END = (window as any).__JARVIS_REPLY_END__ ?? false;`(默认 false = 仍走旧 action-buffer 的 `end_session` 退出路径)。`runSession` 走哪条由 flag 选:
   - flag off:维持现状(`submitPrompt` 包成 `{text, end:false}`,end 仍由 buffer 的 `end_session` action 驱动——保留 :146-148 的 `case "end_session"` 与 session.ts 里 end_session 分支)。
   - flag on:`submitPrompt` 透传真 `end`,**忽略** buffer 的 `end_session`。
   - 实现提示:flag 只切「end 从哪来」,play/stop 此步仍不动,保证可热回退。
- 验证:T4 绿(测 flag-on 行为);`npm run build` 通过;flag 默认 off → 浏览器/真机行为与今日一致(回退安全)。

### 步骤 C —— 真机验收(开 flag,先验后删)
临时置 `window.__JARVIS_REPLY_END__=true`(Tauri 壳注入或 dev 控制台),跑下方「真机验收门」。**全过**才进步骤 D。未过 → flag 关回,步骤 A/B 代码无害留存,零回退成本。

### 步骤 D —— 收缩:删旧广播 + 删 play/stop 死路径(单个「音乐退出契约」commit)
仅在 C 通过后:
1. 后端:
   - `voice_hud_tools.py`:删 `play_music_handler`/`stop_music_handler`(:23-31);`end_session_handler` 删 `_broadcast(...)` 旧分支,只置 flag(返回确认串保留)。可顺带删 `set_broadcast` 若 end 不再需要它(确认无其它 caller)。
   - `dev_server.py`:`_register_voice_hud_tools` 注释更新(已只注册 end_session,无需改注册);删 `set_broadcast` 注入若废。
   - `tests/test_voice_hud_tools.py` / `test_voice_hud_contract.py`:收缩到只剩 end-flag 守卫(去掉「广播 {type:end_session}」断言)。
   - `hud-app/ws_tool_smoke.py:18`:监听集去掉 `play_music/stop_music/end_session`(此 smoke 依赖广播,改为监听 `message.complete` 或直接删该脚本——它是「临时脚本不入库」,倾向删,但**提一句让用户定**,不擅自删非自己造的)。
2. 前端:
   - `session.ts`:删 `Action` union / `RANK` / `orderActions` / `ActionBuffer`(:7-34)与 `runSession` 里 play/stop/end action 分支(:86-95);`SessionDeps` 删 `playMusic`/`stopMusic`/`buffer`。
   - `main.ts`:删 `connectEvents` 的 `play_music/stop_music/end_session` 三 case(:140-148);删 `actionBuffer`(:71)、`audio.playMusic/stopMusic` 装配(:354-355、360)与 import；删 feature flag(转为永久新路径)。**保留** `audio`/`music_state`/`music_duck`/`/api/audio_level` 等真实音乐链路(与 play_music 无关,阶段 0 已定性)。
   - `session.test.ts`:删 action 相关用例,只留 `runSession` 新边界用例。
- 验证:`pytest` + `vitest` + `npm run build` 全绿;再跑一次真机门确认收缩无回归。

---

## 风险

- 🔴 **contextvar / 线程上下文**:`end_session` 工具 dispatch 与 `message.complete` 的 `_emit` 是否同上下文,决定 flag 机制选型。**T1a 必须先实测**(可在测试里打印线程/ctx);若 dispatch 在 agent 工具线程池而 emit 在主任务,contextvar 不通,退化为以 `sid` 为 key 的 turn dict(在 `prompt.submit` 起始建、`message.complete` 后清)。
- 🟠 **包装 `_emit` 的脆性**:monkeypatch `server._emit` 若上游重构会失配。缓解:只在 `event=="message.complete"` 命中时改写,其余透传;加注释指明这是契约别名层(与 `_load_enabled_toolsets` 包装同一理由)。
- 🟠 **双发期双触发结束**:展开期若 flag 误开 + 旧广播都在,可能两条路都判 end。缓解:flag-on 时前端**忽略** buffer 的 end_session(只认 payload.end),flag-off 时忽略 payload.end——互斥,不叠加。
- ⚠️ **`ws_tool_smoke.py` 依赖广播**:收缩删广播后该 smoke 失效;它是「临时不入库」脚本,删或改让用户定。
- ⚠️ **超时映射**:超时分支必须映成 `end:false`,否则一次 agent 慢响应被误判结束会话(回归「念没听清后还想继续」)。

---

## 真机验收门(代码验不了,必须真机)

1. **先念完告别再隐身**:念「退下/再见」→ agent 调 end_session → HUD **念完整句告别后**才 hide,不在话说一半切待机(决策行为 #1)。
2. **TTS 期间 busy 抑制不破**:整段告别 TTS 播放中,KWS 尾音不被当唤醒重触发(`WakeHub` busy + 240s 自愈 + cooldown 仍生效)。
3. **回声门控不回归**:`finishRecordingToText` 的自身回声过滤(main.ts:222-228)在新路径下仍丢弃自述。
4. **end_session 排序语义**:同一轮 agent 既执行动作(如开浏览器 skill)又判结束时,**动作先做完再退场**(原 RANK end_session 最后的语义,在新边界由「念完 text 后才 break」自然承接;真机确认无「动作没做完就隐身」)。
5. **空闲超时不误触**:agent 跑长任务(未返回)期间不被静音超时误判回待机(本阶段不改超时,只确认 end 改造未引入回归;空闲超时正式做在阶段 4)。
6. **flag 回退**:`__JARVIS_REPLY_END__=false` 时行为与今日完全一致(回退路径可用)。

---

## 依赖与排序

- **硬前置**:阶段 0(基线绿)已完成、阶段 1(鉴权)已完成。本阶段不依赖阶段 2(say/text sanitizer)——但若先做阶段 2,`text` 已被 sanitize,`end` 改造与之正交,无冲突。
- **同文件冲突**:`dev_server.py` 与阶段 1 鉴权改动在同一文件(已合入),本阶段新增 `_emit` 包装 + end flag 注入,**与鉴权区块不重叠**(加在 `_patch_enabled_toolsets` 装配附近 :228-289)。
- **阶段 4 接续**:本阶段交付「路①:end=true → 念完再回待机」的前端机制(步骤 B/D);阶段 4 的「路②空闲超时」与超时常量对齐在其后做,**不在本阶段**。
- **内部排序**:A(后端双发)→ B(前端 flag 读新)→ C(真机)→ D(收缩),严格串行;**绝不把换形状(A/B)与删旧(D)塞进同一 commit**。

---

## 明确不做(YAGNI)

- 不重命名 `tui_gateway/server.py` 内部事件名 / 不改 `_emit` 签名(只外层包装,风险已知)。
- 不去掉 `_patch_enabled_toolsets` 的 `_load_enabled_toolsets` monkeypatch(决策/计划明确:本阶段去不掉,属更大改动)。
- 不实现自研/Codex/CC/OpenClaw 适配器(只交付 hermes 适配器 + 接口留口)。
- 不动真实音乐链路(`audio_levels`/`music_state`/`music_duck`/`/api/audio_level`/`/api/music` 与 gequbao)——只删 webview `play_music/stop_music` 死路径。
- 不做阶段 2 的 sanitizer、阶段 4 的空闲超时与超时常量对齐、阶段 5/6 的流式/旁路。
- 不做 say/text 分离(阶段 2)。


---

## 元数据(workflow 抽取)

**改动文件**:
- hud-app/voice_hud_tools.py
- hud-app/dev_server.py
- hud-app/hud/src/voice/rpc.ts
- hud-app/hud/src/voice/session.ts
- hud-app/hud/src/main.ts
- hud-app/hud/src/voice/session.test.ts
- tests/test_voice_hud_contract.py
- tests/test_voice_hud_tools.py
- tests/test_voice_hud_end_flag.py
- hud-app/ws_tool_smoke.py

**依赖/冲突**:
- 阶段 0(契约绿基线)与阶段 1(鉴权门)必须已合入——本阶段在其上叠加
- 同文件冲突:dev_server.py 已含阶段1鉴权区块(_auth_*、middleware、_enforce_fail_closed);本阶段 _emit 包装/end-flag 注入需加在 _patch_enabled_toolsets 装配区(dev_server.py:228-289)且不与鉴权区重叠
- tui_gateway/server.py:5495-5505 是 message.complete 的 text 产出点,end 必须在此并入——但本阶段经 monkeypatch 包装 _emit 实现,不直接改 server.py
- 阶段 4(空闲超时/超时常量对齐)接续本阶段交付的『路① end=true→念完再回待机』前端机制,不可与本阶段同 commit

**真机验收门**:
- 念『退下/再见』→ 先念完整句告别再隐身(不在话说一半切待机)
- 整段告别 TTS 播放中 KWS 尾音不被当唤醒重触发(WakeHub busy + 240s 自愈 + cooldown 生效)
- 自身回声过滤(main.ts:222-228)在新 {text,end} 路径下仍丢弃自述,不回归
- 同一轮既执行动作(开浏览器 skill 等)又判结束时,动作先做完再退场(承接原 RANK end_session-最后语义)
- agent 跑长任务未返回期间不被静音超时误判回待机(确认 end 改造未引入回归)
- feature flag __JARVIS_REPLY_END__=false 时行为与今日完全一致(回退路径可用)

**风险**:
- contextvar/线程上下文:end_session 工具 dispatch 与 message.complete 的 _emit 是否同上下文决定 flag 机制选型,T1a 必须先实测,不通则退化为以 sid 为 key 的 turn dict
- monkeypatch server._emit 脆性:上游重构会失配;缓解=只在 event=='message.complete' 命中改写、其余透传,注释标明为契约别名层
- 双发期双触发结束:flag-on 只认 payload.end、flag-off 只认 buffer 的 end_session,互斥不叠加
- 超时分支必须映成 end:false,否则 agent 慢响应被误判结束会话
- ws_tool_smoke.py:18 依赖广播,收缩删广播后失效——它是『临时不入库』脚本,删或改让用户定,不擅自删非自己造的代码


---

## workflow 对抗 critic(待 Codex 复核合并)

**verdict**: 不能直接照搬执行,有 2 个 blocker 必须先解决。(1) 双 TTS:网关 server.py:5600 自带 speak_text 路径,本阶段把口播正式交给前端 runSession 后,若 HERMES_VOICE_TTS=1 会双念且网关那遍绕过 HUD busy/回声门控——这会让真机门#1/#2 直接失败,且 spec 全程未提此路径,属硬伤,动手前必须确认并关闭网关侧 TTS。(2) sid-keyed dict 退化方案不可实现:置 flag 在 handler、handler 经 registry.dispatch 拿不到 sid,该兜底落不了地;好在已 grounded 证明 dispatch(5429)与 message.complete emit(5505)在同一 run() 线程(5703),contextvar 方案成立——应删掉假退路、把同线程作为写死前提。其余:T2/T3 把『不可见』错绑到『删 handler』(实为未注册,与现有契约测试注释冲突)、rpc.ts onclose 复位漏 replyEnd(网关重启高频路径会误退会话)需在动手前修正。expand-contract 分步、red-first、互斥防双触发、不动 server.py 内部走 _emit 包装这些主干判断正确且符合 Simplicity/Surgical 约束,不算过度抽象。把上述 blocker/high 补齐后可执行。

- **[blocker]** 双 TTS 漏洞:网关 server.py:5600-5611 在 _voice_tts_enabled() 为真时,自己起线程 speak_text(raw) 念 agent 回复。本阶段把『念 text』正式纳入前端 runSession(speak(reply)),若真机/壳里 HERMES_VOICE_TTS=1,会出现网关念一遍+HUD 念一遍(且网关那遍不受 HUD busy 抑制、不进回声门控,会被 KWS 当唤醒重触发)。spec 完全没提这条并发 TTS 路径,真机门#1/#2(念完告别再隐身、TTS 期间 busy 抑制)会直接翻车。
  - fix: 动手前先确认 HUD 启动环境里 HERMES_VOICE_TTS 的取值;若为 1 必须在本阶段显式关掉(HUD 不需要网关侧 TTS,口播归前端)。把『确认网关侧 TTS 关闭/单一 TTS 来源』写成真机门第 0 条,并在 spec 现状锚点补 server.py:5600 这条路径。
- **[blocker]** sid-keyed dict 退化方案不可实现:spec 风险栏写『contextvar 不通则退化为以 sid 为 key 的 turn dict,在 prompt.submit 起始建、message.complete 后清』,但置 flag 发生在 end_session_handler 内,而 registry.dispatch(registry.py:390)只把 agent 传的 **kwargs 透传给 handler——handler 拿到的是 args(+可能 task_id),并不保证拿到 sid。message.complete 的 _emit 有 sid,但置 flag 的 handler 没有。所以『按 sid 写 dict』在 handler 侧无 key 可用,退化方案落不了地。
  - fix: 先实测确认 dispatch→emit 同线程(已 grounded:server.py:5429 run_conversation 与 5505 _emit 在同一 run() 线程,5703 起的同一 daemon thread),contextvar 方案成立、应作为唯一选型。删掉 spec 里『sid-keyed dict 退化』这条不可行的兜底,或改成『以 threading.get_ident()/当前线程为 key』(handler 与 emit 同线程才有意义);明确写死同线程前提,别给实现者一个假退路。
- **[high]** T2/T3 把『handler 删除』当成『agent 不可见』的依据,与现有契约测试和 SCHEMA 冲突。现状 test_voice_hud_contract.py 头注释(:8-9)明确『play_music/stop_music handler 仍存在于 voice_hud_tools.py,只是从未注册』,decisions/0007 也这么定性。spec 步骤 D 才删 handler,但 T2 说『收缩后这俩 handler 已删,断言不在 names 自然成立』——把『不可见』错误地绑定到『handler 删除』。不注册即不可见,删不删 handler 与可见性无关。
  - fix: T2 的『不可见』断言保持原样(基于未注册,而非未定义),与删 handler 解耦。删 handler 的验证放到 T3(import 报 AttributeError)。spec 文字纠正:play/stop 对 agent 不可见的根因是『未在 _register_voice_hud_tools 注册』,删 handler 只是清死代码、不影响可见性。
- **[high]** rpc.ts 断线复位路径漏了 replyEnd。spec 步骤 B 只说在 awaitingReply 起始清零 replyText/replyEnd,但 onclose(rpc.ts:62-73)在断线时也会 awaitingReply=false / replyText=''/ replyDone?.() 解挂——这里若不同步把 replyEnd 复位成 false,断线那一轮 submitPrompt 可能返回上一轮残留的 end=true,触发误退会话(网关重启场景已是高频路径,见提交历史 6846002)。
  - fix: 在 onclose(rpc.ts:70-72)分支同步加 this.replyEnd=false,与 replyText='' 并列;并在 T(前端单测)补一条:断线解挂时 submitPrompt resolve 的 reply.end 必为 false。
- **[medium]** 超时兜底当前实现并不会念完再听,而 spec 把超时映射成 {text:'没听清…',end:false} 后,session.ts:79-84 现状是『reply===TIMEOUT → speak(没听清) → continue』,改成 AgentReply 后若写成 await speak(text); if(end)break,逻辑等价没问题——但 spec 没说清超时分支是否还要走统一的 speak(text)+if(end) 路径还是单独 continue。两种写法对『超时后是否执行 buffer.drain 的残留动作』行为不同(flag-off 双发期残留 end_session action 可能在超时轮被 drain 误触发退出)。
  - fix: 明确:超时轮直接 continue,不走 buffer.drain(避免 flag-off 期残留 end_session action 在超时轮误触退出);并在前端单测固化『超时轮不退出且不消费 buffer』。
- **[medium]** _emit monkeypatch 是全局的,影响所有 session(含非语音 TUI 客户端)的 message.complete,而 spec 只从『脆性/上游重构』角度提风险,没点明它对所有会话生效。虽然 contextvar flag 未置位时是 no-op、行为安全,但实现者若把 flag 设计成模块级全局变量(非 contextvar/线程局部)会污染并发的其它会话。
  - fix: 在 spec 显式约束:flag 必须是 turn-scoped(contextvar 或线程局部),严禁模块级全局;wrapper 在 flag 未置位时对 payload 原样透传。补一条单测:并发两轮(一轮 end 一轮不 end)payload.end 不串台。
- **[low]** ws_tool_smoke.py 不止 :18 监听广播,run_prompt() 整个流程依赖 play_music 动作事件作为成功判据(PROMPT 默认『放首周杰伦的晴天』)。收缩删 play_music 后该脚本语义整体失效,不是改一行监听集就行。spec 把它当『改监听集或删』轻描淡写。
  - fix: spec 已倾向删且让用户定,OK;但补一句:该脚本的成功判据(play_music 动作)随阶段0音乐死路径移除已整体失效,不要试图改造成监听 message.complete(那是另一套断言),直接提请用户删除。
- **[low]** set_end_flag 第二注入点 + end_session_handler 双发,是为可回退,但收缩阶段 D 删 _broadcast 后,set_broadcast 注入点是否还有 caller 需确认。grep 显示 _safe_emit/set_broadcast 仅服务 voice_hud 三件套;play/stop 删除 + end 改置 flag 后 set_broadcast 与 _safe_emit 都成死代码。spec 说『可顺带删 set_broadcast 若无其它 caller』但没让实现者实际 grep 确认 hub.broadcast 是否还被 /api/wake 等其它路径用。
  - fix: 收缩前 grep set_broadcast / _safe_emit / hub.broadcast 全量 caller(/api/wake 仍直接用 hub 广播 wake,不经 _safe_emit),确认 _safe_emit/set_broadcast 确无其它 caller 再删,避免误删 hub.broadcast。
- **[low]** AgentReply.end 为 optional(end?),但 rpc.ts 返回处用 payload?.end ?? false 已收敛成 boolean,而 session.ts 接口又声明 end?:boolean——两处对『缺省』的表示不一致(optional vs 显式 false)。小但会让 T4 断言形态摇摆(『end:false/缺省』两种)。
  - fix: 统一:rpc 层负责把 end 收敛成确定 boolean(?? false),AgentReply.end 在边界内即声明为 end:boolean(非 optional),前端逻辑只判 truthy。T4 断言用 end:false 单一形态。

---

## Codex 复核(已接受,2026-06-13)

**BLOCKER(已核实)— 双 TTS**:`server.py:5605-5609` 在 `message.complete` 后、当 `HERMES_VOICE_TTS=1` 时另起线程 `speak_text`,与 HUD 前端 `voice.synthesize+audio.play` 并存 = 两路朗读。家里 `start_jarvis.sh` 未设该变量(默认 off),但**真机验收门必须显式 `HERMES_VOICE_TTS=0`**,否则双路音频会掩盖 `{text,end}` 语义。

**接受的修正**:
- **删 sid fallback**:`registry.dispatch` 只透传 `task_id=session_key`,**没有 sid**(`tools/registry.py`)。spec 里的 sid-key fallback 不成立,删掉;其余 alias 方案(扩 `message.complete` payload 加 `end`,前端 `rpc.ts` 读 `payload.end`)成立。
- **删除清单补全**:`AudioEngine.playMusic/stopMusic`(`audio.ts:317-359`)删 `main.ts` 调用点后变死代码,需列入;`/api/music` webview proxy(`dev_server.py:365-446`)去留要明确;`main.ts:360` 引用错(那是 `buffer: actionBuffer`)。
- **`onclose` 要一并重置 `replyEnd`**:`rpc.ts:62-74` 现只清 `replyText`,新增 `replyEnd` 必须同清,否则断线重连 flag 状态不定。
- **contextvar 并发未"已证明"**:hermes 有并发工具线程池,turn-scoped flag 必须实测,不能提前标 done。
- **false-green**:单测 mock `_emit("message.complete")` 会绕过真实 `agent.run_conversation` + 工具线程;需补完整 turn 集成测试。
- 真机门追加:`HERMES_VOICE_TTS=0`、并发串台、断线后 `replyEnd=false`。
- OK(无需改):alias 层可行;薄 adapter 比例恰当(实现勿引入 ABC/manager 通用框架)。
