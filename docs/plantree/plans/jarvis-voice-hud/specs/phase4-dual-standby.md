# 阶段 4 实施规格 —— 双路回待机

依据 decisions/0007 第 53-63 行 + impl-plan 阶段 4(L97-102)。

## 目标 / 成功标准
回待机两条路,任一触发即回,谁先谁生效:
- **路①(agent 主动结束)**:agent 返回 `end=true` → **先念完 `text` 再回待机**(保留"喊一声退下立刻消失"的即时感)。
- **路②(空闲超时,贾维斯自管)**:**仅在"本轮已结束、正在等用户开口"时**计时,连续 `IDLE_TIMEOUT_MS` 无人说话 → 自动回待机。**agent 还在跑长任务(submitPrompt 未返回)时不计时**(否则慢工具被误判静音退场)。

成功标准(全部可验证):
1. 单测(vitest,fake timers)证明:`end=true` → 念完 text 后 break;空闲累计超时 → break;**submitPrompt 挂起期间空闲计时不推进**;有一次成功转写后空闲计时归零。
2. busy 抑制行为**不变**:busy 只在整会话 finally 清(session.ts:100-103),TTS 期间不放行唤醒。
3. 跨进程超时常量对齐:后端 `BUSY_MAX_S=240`(dev_server.py:127)仍 `>` 前端每轮 agent 硬超时 `SESSION_TIMEOUT_MS=180000`(main.ts:262);新增的空闲超时是**独立第三个常量**,且 `< SESSION_TIMEOUT_MS`,不与 busy 自愈冲突。
4. 真机:喊"贾维斯"→对话→"退下"立即退场;不说话→空闲超时自动退场;长任务(看 skill/跑 terminal 数十秒)期间不误退。

## 硬依赖(必须先就位)
**dep: 阶段 3 已落地 `{text, end}` 返回值。** 本阶段读 `end` 这个 bit,前提是:
- `rpc.submitPrompt` 已从返回 `string` 改为返回 `{text: string, end: boolean}`(rpc.ts:155-163 当前返回 `this.replyText: string`,阶段 3 改);
- `SessionDeps.submitPrompt` 类型(session.ts:39)随之改为 `() => Promise<{text, end}>`;
- hermes 适配器侧 `end_session` 工具不再(或不只)经 WakeHub 广播,而是置返回值 `end=true`(impl-plan L85-88)。

**若阶段 3 仅"双发"(旧 `{type:end_session}` 广播 + 新 `end` 同时在),本阶段在 feature flag 打开后只读 `end`,旧广播分支的删除归阶段 3 的 contract 收尾,不在本阶段删。** 本阶段**绝不删 play_music/stop_music/end_session 广播分支**(那是阶段 3 的"音乐退出契约"commit)。

## 改动文件清单(file:line)
1. **hud-app/hud/src/voice/session.ts**
   - L37-49 `SessionDeps`:`submitPrompt` 返回类型随阶段 3 变 `{text,end}`(若阶段 3 已改则此处仅消费);**新增** `idleTimeoutMs: number` 字段(与现有 `timeoutMs` 并列,语义区分见下)。
   - L66-104 `runSession` loop 主体:
     - L79-84:`reply` 现为 `{text,end}`(或 TIMEOUT);念 `reply.text`;
     - **路①**:念完 `reply.text` 后,若 `reply.end === true` → `break`(在执行完 drain 动作之后、或直接 break——见"与现有 ActionBuffer 的关系");
     - **路②**:`listen()` 返回 `null` 时(L76-78 现为 `continue`)→ 改为累计空闲时长,超 `idleTimeoutMs` 则 `break`,否则 `continue`;**任一次成功转写(text != null)→ 空闲累计归零**。
   - L51-61 `withTimeout`:保持不动(它是路①/硬超时复用的工具,不是空闲超时)。
2. **hud-app/hud/src/main.ts**
   - L262 `SESSION_TIMEOUT_MS`:保留(=agent 每轮硬超时,传 `timeoutMs`)。
   - **新增** `IDLE_TIMEOUT_MS` 常量(建议 30000,见"常量对齐"),并在 L350-362 `runSession({...})` 装配处传 `idleTimeoutMs: IDLE_TIMEOUT_MS`。
   - L350-362:`submitPrompt: (text) => rpc.submitPrompt(text)` 随阶段 3 已返回 `{text,end}`,本阶段确认透传不再 `.text` 解包(若阶段 3 没改 main 装配则在此对齐)。
3. **hud-app/hud/src/voice/session.test.ts**
   - 新增 red-first 用例(见 TDD 清单)。`stubDeps`(L29-44)补 `idleTimeoutMs` 默认值;`submitPrompt` 桩返回值改 `{text,end}`(与阶段 3 对齐)。
4. **dev_server.py**(仅文档/常量注释,非逻辑):L127-128 注释已说明 `BUSY_MAX_S > SESSION_TIMEOUT_MS`;**补一句**空闲超时(前端)与 busy 自愈(后端)的关系——空闲超时 `< SESSION_TIMEOUT_MS < BUSY_MAX_S`,不需要后端配合(空闲退场前端自己 break,会走 finally 报 idle → 后端 set_busy(False))。**不改后端逻辑。**

## 与现有 ActionBuffer / 广播 end_session 的关系(关键边界,别踩)
当前 `end_session` 是经 `/api/events` 广播 → `actionBuffer.push({type:end_session})`(main.ts:146-147)→ loop drain 时 `ended=true`(session.ts:92-94)。阶段 3 把 end 改为 `submitPrompt` 返回值的 `end` bit。本阶段路①**优先读返回值 `reply.end`**:
- 若阶段 3 已切到 feature flag 读 `end`:本阶段 `break` 条件用 `reply.end`,**保留** drain 里 `end_session` 分支不动(双发期它仍可能从广播来,两者都触发 break 是幂等的)。
- **不要**在本阶段动 ActionBuffer 的 RANK/drain/union(那是阶段 3"音乐退出契约"的删除清单,见 impl-plan L93-94,本阶段碰它=越界、=同文件冲突)。

## TDD 测试清单(red-first,vitest fake timers;每条断言什么)
全部加在 session.test.ts 的 `describe("runSession")`。先写、先 red、再改 session.ts 转绿。

1. **`end=true → 念完 text 再 break`**
   - 桩:`listen` 第一轮返回 `"退下"`;`submitPrompt` 返回 `{text:"好,我退下了", end:true}`;`speak` 记录调用。
   - 断言:`calls == ["speak:<greeting>", "speak:好,我退下了"]`,且 `runSession` resolve(循环退出);`setHudVisible(false)` 被调用(finally 走到)。**断言"念在前、退在后":speak 调用发生在 promise resolve 之前**(speak 记录里有该句)。

2. **`end=false → 不退,继续下一轮`**
   - 桩:`listen` 第一轮 `"几点了"`、第二轮 `"退下"`;`submitPrompt` 第一轮 `{text:"三点", end:false}`,第二轮 `{text:"好的", end:true}`。
   - 断言:两轮 reply 都被念,最终退出;证明 `end=false` 不误退。

3. **`空闲超时 → break`(路②核心)**
   - fake timers。`idleTimeoutMs` 设小值(如 3000);`listen` 恒返回 `null`(每次 `listen` 内部用注入 `sleep` 推进一个"窗口耗时",或测试侧让 `listen` 自身 await 一段 sleep 模拟一个监听窗)。累计 null 时长超 3000 → break。
   - 断言:`runSession` resolve(退出),且只念了招呼(没有 reply),`setHudVisible(false)` 调用。
   - **实现选择(写进 spec 供实现者定)**:空闲计时用"累计 listen 返回 null 的次数×窗口时长"还是"wall-clock(performance.now/注入 now)"?**推荐 wall-clock**:loop 内记 `lastSpeechAt`,每轮 listen 返回 null 后比较 `now() - lastSpeechAt > idleTimeoutMs`。这要求给 `SessionDeps` 注入 `now: () => number`(便于 fake)。**注意:autoListen(main.ts:271)本身有 WAKE_WAIT_SPEECH_MS=5000 的"等开口"窗,所以一次 null 已代表约 5s 静音;空闲超时是"连续几个这种窗"。**

4. **`submitPrompt 挂起期间空闲计时不推进`(路②防误退的命脉)**
   - fake timers。`listen` 第一轮返回 `"看下天气"`(触发 submitPrompt),`submitPrompt` 返回一个挂很久(如 100s,但 < timeoutMs)才 resolve 的 promise;期间用 `vi.advanceTimersByTime` 推进超过 `idleTimeoutMs`。
   - 断言:**不 break、不报空闲超时**;submitPrompt resolve 后正常念 reply。证明长任务期间空闲计时冻结(因为计时只在 listen 返回 null 后判,submitPrompt 期间根本没进 listen)。
   - 推论:**只要空闲判定点放在"listen 返回 null 之后",submitPrompt 期间天然不计时**——这是最简实现,无需显式"暂停计时器"。把这条作为实现约束写死。

5. **`一次成功转写后空闲累计归零`**
   - 桩:`listen` 序列 `null, null, "在吗", null, null, ...`;`idleTimeoutMs` 设为"3 个 null 才超时"。
   - 断言:中间的成功转写把累计清零,故前 2 null + 后 2 null 不会触发(若不清零则第 4 个 null 误退)。证明 `lastSpeechAt` 在成功轮被刷新。

6. **(回归)`submitPrompt 硬超时仍走"没听清"兜底`**:保留现有 L75-103 用例不破(阶段 3 改返回值后该用例的 `submitPrompt` 桩返回 `{text,end}`,超时分支 reply===TIMEOUT 不变)。

## expand-contract 分步(每步可验证可回退)
- **步 0(基线)**:确认阶段 3 已 merge、`npm run test`(vitest)绿、契约测试绿。拿到"迁移前绿"。
- **步 1(红)**:加 TDD 用例 1-5(session.test.ts)+ 给 `SessionDeps` 加 `idleTimeoutMs`/`now` 字段类型 + stubDeps 默认值。跑测试 → 新用例 red,旧用例仍绿。**可回退**:只动测试文件。
- **步 2(绿,路①)**:session.ts loop 读 `reply.end` → break(用例 1/2 转绿)。**纯加法**,旧 drain end_session 分支保留。
- **步 3(绿,路②)**:session.ts loop 加 `lastSpeechAt`/空闲累计 + null 后判超时 break(用例 3/4/5 转绿)。
- **步 4(装配)**:main.ts 加 `IDLE_TIMEOUT_MS` 常量 + runSession 装配传 `idleTimeoutMs`/`now: () => performance.now()`。**feature flag 不需要新建**——空闲超时是纯前端新增行为,无后端契约面,默认开即可(若要保守,可用一个 `IDLE_TIMEOUT_MS = Infinity` 的逃生阀,真机验收后改成 30000;写进注释)。
- **步 5(真机验收)**:跑真机门(见下)。三条全过后,本阶段收口。**旧 end_session 广播分支的删除不在本阶段**(阶段 3 收尾)。
- **回退**:任一步异常,git revert 对应 commit;空闲超时设 `Infinity` 即等价回到"只靠 agent end 退"的旧行为。

## 风险
- 🔴 **空闲计时点放错位置 → 长任务误退**:若把计时放在 wall-clock 定时器而非"listen 返回 null 后判",submitPrompt 期间会继续走表 → 慢工具被砍。**用例 4 焊死此约束。**
- 🟠 **autoListen 的 WAKE_WAIT_SPEECH_MS(5s)与 IDLE_TIMEOUT_MS 的语义叠加**:一次 listen=null 已耗约 5s。若 IDLE_TIMEOUT_MS=30s,实际是"约 6 个空窗才退",体感更长。真机定值时按"几个空窗"思考而非纯秒数(写进注释)。
- 🟠 **end=true 但 text 为空**:agent 只想退、没话说。`speak("")` 在 main.ts:235-237 已 early-return 无害;loop 仍 break。补一句注释,不需额外处理。
- 🟠 **双发期 end 同时从返回值 + 广播来**:两条都 set break,幂等;但别让广播来的 end_session 在"submitPrompt 还没返回"时提前 break(ActionBuffer 在 drain 时才读,drain 在念 reply 之后,时序安全)。确认不引入新竞态。
- ⚠️ **常量对齐**:IDLE_TIMEOUT_MS < SESSION_TIMEOUT_MS(180s) < BUSY_MAX_S(240s)。空闲退场走 finally 报 idle,后端 set_busy(False),不依赖 busy 自愈,无跨进程竞态。

## 真机验收门(代码验不了,必须真机)
1. **喊"退下"即退**:唤醒→说"退下/再见"→agent 念完告别那一瞬 HUD 隐身,不在告别念完前就消失(验路①"先念完")。
2. **不说话超时退**:唤醒→念完招呼后保持沉默→约 IDLE_TIMEOUT_MS 后 HUD 自动隐身、后端恢复可唤醒(验路② + finally 报 idle)。
3. **长任务不误退**:唤醒→说一句触发"看 skill + 跑 terminal/网络"的慢任务(数十秒)→任务进行期间 HUD 不隐身、不报空闲超时、最终正常念出结果(验用例 4 的真机对应,防误退)。
4. **TTS 期不被自身尾音唤醒**:念长回复时 KWS 不重触发(busy 抑制未被本阶段破坏的回归确认)。

## 明确不做(YAGNI)
- 不删 play_music/stop_music/end_session 广播分支、不动 ActionBuffer RANK/drain/union(阶段 3 的"音乐退出契约"commit)。
- 不改后端 dev_server.py 逻辑(仅可选注释)。不动 BUSY_MAX_S/WakeHub。
- 不实现 barge-in / TTS 流式 / 长任务进度帧 / agent 主动说话(阶段 6)。
- 不为空闲超时新建后端契约面或 WS 消息(纯前端行为)。
- 不做"可配置空闲时长 UI";常量足矣。


---

## 元数据(workflow 抽取)

**改动文件**:
- hud-app/hud/src/voice/session.ts
- hud-app/hud/src/voice/session.test.ts
- hud-app/hud/src/main.ts
- hud-app/dev_server.py (仅注释,可选)

**依赖/冲突**:
- 阶段 3 必须先落地:submitPrompt/rpc.ts 返回值从 string 改为 {text,end}(rpc.ts:155-163、session.ts:39 SessionDeps.submitPrompt 类型、main.ts:350-362 装配),否则本阶段无 end bit 可读
- 同文件冲突:session.ts loop 主体(66-104)与 main.ts(146-147、262、350-362)阶段 3 也在改 —— 必须等阶段 3 这两文件改动 merge 后再开本阶段,避免同区块冲突
- 同文件冲突:session.test.ts 阶段 3 重写 contract/桩为 {text,end};本阶段在其之上加用例,需在阶段 3 之后
- ActionBuffer/RANK/drain/play_music 死路径删除是阶段 3 的'音乐退出契约'commit —— 本阶段不得触碰(同文件 session.ts/main.ts 不同区块)

**真机验收门**:
- 喊'退下/再见':agent 念完告别那一刻才隐身,不在告别播完前消失(路①先念后退)
- 唤醒后保持沉默约 IDLE_TIMEOUT_MS:HUD 自动隐身且后端恢复可再唤醒(路②空闲超时 + finally 报 idle)
- 触发数十秒慢任务(看 skill+跑 terminal/网络)期间:HUD 不隐身、不报空闲超时、最终正常念结果(防长任务误退,对应单测 4 的真机面)
- 念长回复时 KWS 不被 TTS 尾音重触发(busy 抑制未被破坏的回归)

**风险**:
- 空闲计时若用 wall-clock 定时器而非'listen 返回 null 后判',submitPrompt 长任务期会继续走表 → 慢工具误退;单测 4 焊死该约束
- autoListen 自带 WAKE_WAIT_SPEECH_MS=5s,一次 null≈5s 静音,IDLE_TIMEOUT_MS 实际是'若干空窗',真机定值按空窗数而非纯秒思考
- end=true 且 text 为空时 speak('') 已 early-return 无害,但 loop 仍须 break(别因 text 空跳过 break)
- 双发期 end 同时来自返回值与广播:幂等但需确认 drain(念 reply 之后)读广播 end 不引入提前 break 竞态
- 常量须满足 IDLE_TIMEOUT_MS < SESSION_TIMEOUT_MS(180s) < BUSY_MAX_S(240s);空闲退场走 finally 报 idle,不依赖后端 busy 自愈


---

## workflow 对抗 critic(待 Codex 复核合并)

**verdict**: 不能直接照搬执行,需先补三处 blocker/high 才可下手。核心硬伤一条:规格把『空闲判定放在 listen=null 之后就天然不会在长任务期计时』当成已证明的最简约束并焊死用例 4,但真正的误退发生在『长任务 submitPrompt 返回之后的第一次 listen=null』——此时 now-lastSpeechAt 已积累整个长任务时长,会立即误退;用例 4 完全测不到这条路(那段不进 listen)。必须明确 lastSpeechAt 的刷新点 = 本轮收尾(念完 reply/drain 之后)而非转写成功之时,并补对应用例。其次:rpc.ts 行号(写 155-163,实为 133-141)错误会误导阶段 3 衔接;路①该用 reply.end 还是仍跑 drain、end=true 同轮的 stop_music 是否执行没说清(影响真机门与音乐收尾);fake-timers 下注入 now 与 sleep 双时间源的协同范式没给(performance.now 是否被 fake 未交代),实现者易写出 now 不前进的死循环。整体结构(expand-contract、YAGNI 边界、不碰 ActionBuffer)是健康的,真机门覆盖到位,但『先念后退』那条断言措辞恒真等于没测。建议:引入 idleWindows(空窗计数)替代 now 第二时间源以降复杂度并贴合『按空窗数思考』的自述语义;dev_server.py 彻底移出本阶段。补齐后可执行。

- **[blocker]** 【lastSpeechAt 基准点错位 → 长任务后"立即"误退,而非长任务"期间"】规格反复强调"只要把空闲判定放在 listen 返回 null 之后,submitPrompt 期间天然不计时"(用例 4、风险🔴),并把它当最简实现焊死。但用 wall-clock + lastSpeechAt 时存在真正的坑:若在「listen 返回有效 text 那一刻」就刷新 lastSpeechAt,然后 submitPrompt 挂 100s,submit 返回、念完 reply,再进下一轮 listen 返回 null —— 此时 now() - lastSpeechAt ≈ 100s+ >> idleTimeout(30s),会在长任务结束后的第一个空窗立即误退。用例 4 只断言『submitPrompt 挂起期间不 break』(那一段根本没进 listen,当然不 break),完全没覆盖『submitPrompt 返回之后第一次 listen=null 时的判定』,所以这个真 bug 测不出来。正确语义应是:lastSpeechAt 必须在『念完 reply、本轮真正结束、开始等下一句』那一刻刷新,而不是在转写成功那一刻。
  - fix: 明确规定 lastSpeechAt 的刷新点 = 『本轮处理完成、即将回到 listen 等下一句』之时(reply 念完/动作 drain 之后),而非转写成功之时。并新增一条 TDD 用例:listen 返回有效 text → submitPrompt 挂 100s 后 resolve → 再 listen 返回 null 一次 → 断言『不 break』(因 lastSpeechAt 已在本轮收尾刷新)。这条才真正覆盖『长任务后不误退』。
- **[high]** 【rpc.ts 行号与现实严重不符,会误导实现者】规格 deps 与正文多处写 rpc.submitPrompt 在 rpc.ts:155-163 返回 this.replyText。实测 submitPrompt 在 L133-141,return this.replyText 在 L140;文件只有 152 行,根本没有 155-163。其余如 SessionDeps.submitPrompt(L39)、main.ts SESSION_TIMEOUT_MS(L262)、dev_server BUSY_MAX_S(L127)、main.ts 装配(L350-362)经核对均正确,唯独 rpc.ts 错。这会让阶段 3 实现者按错行号定位,且暴露规格作者未对该文件做真实核对。
  - fix: 把所有 rpc.ts:155-163 更正为 rpc.ts:133-141(submitPrompt),return 点 L140。既然这是阶段 3 的硬依赖锚点,务必校准,否则阶段 3/4 衔接的 contract 断言会对不上。
- **[medium]** 【路①断言『念在前、退在后』在串行 async 模型下不可能 false,等于没测】runSession 是 await speak(reply) 之后才读 reply.end break,本就串行;『speak 调用发生在 promise resolve 之前』在任何实现里都恒真。规格把它当成核心断言(用例 1),但它无法捕捉真正的回归——比如有人误把 break 放到 speak 之前(那 calls 里压根不会有该句,用例自然挂,但断言措辞『resolve 之前 speak 被调用』描述失准)。措辞制造了『已验证先念后退』的虚假安全感。
  - fix: 把用例 1 的断言简化为:calls 序列 == [greeting, reply.text] 且 setHudVisible(false) 被调用一次、且在 speak(reply) 之后调用(用调用顺序记录验证 hud 隐身晚于念回复)。删掉『resolve 之前』这种恒真措辞。
- **[high]** 【真机门『退下那一瞬隐身』代码与现有时序天然有 800ms+排空 50ms 延迟,门设得过于绝对】路①真机门要求『agent 念完告别那一刻 HUD 隐身,不在念完前消失』。但 runSession 念完 reply 后还有 sleep(50) drain 窗,且若仍读广播 end_session 需等 drain;若改读 reply.end 则 break 在 speak 后立刻发生——两条路退场时机不同(reply.end 早于 drain 的广播路约 50ms+)。规格说『双发期两者都 break 幂等』,但没说清本阶段 break 到底用哪条、drain(50ms)是否还跑。这关系到真机门能否过、以及 play/stop_music 收尾动作在 end=true 那轮是否还执行。
  - fix: 明确:本阶段 break 用 reply.end,但 break 前必须仍执行 sleep(50)+drain(否则 end=true 那轮里 agent 同时调的 stop_music 会被吞)。即 reply.end 只决定『drain 后是否 break』,不短路 drain。把这写成用例:reply.end=true 且同轮 buffer 有 stop_music → 断言 stopMusic 被调用 AND 退出。
- **[high]** 【空闲计时与 listen() 内部阻塞(800ms+5000ms)的耦合未澄清,fake-timers 用例会很脆】用例 3 说『listen 恒返回 null,每次内部 await 注入 sleep 推进一个窗口』。但真实 autoListen 的等待用的是 setTimeout / setInterval(L273、L288-304)且静音窗约 5s,不是注入的 sleep。测试里 listen 是桩(可控),但规格没规定桩 listen 是否要消耗时间。若桩 listen 立即返回 null 且 idle 判定用 now()-lastSpeechAt,而 now 也是桩——必须明确『谁推进 now』。规格让实现者自己在『次数×窗口』和『wall-clock』之间二选一又强推 wall-clock+注入 now,但没给桩 listen 如何与注入 now 协同推进的范式,实现者很可能写出 now 永不前进、用例死循环。
  - fix: 在用例 3/5 中规定:注入 now 为可控计数器(let t=0; now=()=>t),桩 listen 每次返回 null 前执行 t += WINDOW(如 5000),idleTimeoutMs=12000 → 第 3 个 null 时 t-lastSpeechAt=15000>12000 break。把这个具体范式写进规格,避免实现者在 fake timer + 注入 now 的组合上反复试错。
- **[medium]** 【SessionDeps 新增 now 字段,但 withTimeout/sleep 已用注入 sleep 做时间——引入 now 是第二套时间源,有过度抽象之嫌】现有代码所有时间推进走注入 sleep(便于 fake timers)。规格又为空闲超时引入 now: ()=>performance.now()。两套时间源(sleep 推进 + now 读钟)在 fake-timers 下需保持一致(vi 的 fake timer 会同时接管 performance.now 吗?vitest 默认 fake timers 不一定 mock performance.now,需显式 toFake 含 'performance')。这是真机/测试一致性陷阱,且违反 Simplicity——能否复用『累计 null 次数 × 已知窗口』避免第二时间源?
  - fix: 二选一并写死:(a) 若用 now,规格须注明 vi.useFakeTimers({toFake:['performance']}) 否则 performance.now 不被 fake、用例 4 advanceTimersByTime 不影响 now;(b) 更简方案:不引入 now,空闲用『连续 null 计数 × 单窗估时(WAKE_WAIT_SPEECH_MS)』,idleTimeoutMs 改成 idleWindows:number(如 6 个空窗)。考虑到规格自己在风险里说『按空窗数思考而非纯秒』,(b) 反而语义更贴合且少一个依赖。建议默认 (b)。
- **[low]** 【dev_server.py 仅改注释也算改文件,但硬约束里有 CRLF/锁等真机约束未在本阶段复述】MEMORY 指针提到 GPU/锁/cmd/CRLF 硬约束。规格让动 dev_server.py 注释(即便只注释),Python 文件若被 CRLF 化或触发某锁会翻车。规格把 dev_server 改动标『可选注释』是对的,但既然 deps 说阶段 3/4 同文件冲突敏感,应明确『dev_server.py 本阶段一行不改(连注释都跳过)』以彻底消除该文件进 diff 的风险,注释挪到阶段 3 或单独 doc commit。
  - fix: 把 dev_server.py 从本阶段 files 移除,标注『注释说明合并进阶段 3 常量对齐 commit 或独立 doc commit』。本阶段产物只剩 session.ts / session.test.ts / main.ts 三个前端文件,diff 更干净、零后端文件风险。
- **[medium]** 【步 0 基线依赖『阶段 3 已 merge』,但规格同时允许『阶段 3 仅双发』的中间态——两者矛盾,开工前置条件不唯一】依赖段说必须等阶段 3 两文件 merge;但正文又给出『若阶段 3 没改 main 装配则在此对齐』『若阶段 3 仅双发本阶段只读 end』等多个分叉。实现者无法确定开工时阶段 3 到底处于哪态,可验证的开工门(submitPrompt 是否已返回 {text,end})没有一句『先跑 X 命令确认 rpc 返回类型』的现实核对。
  - fix: 加一条 expand-contract 步 0 前置核对命令:grep 'Promise<{ *text' rpc.ts 或 tsc 类型检查确认 submitPrompt 返回 {text,end};若仍为 string → 阶段 4 不能开。把『阶段 3 必须已把 rpc 返回类型改完(不论广播是否还双发)』定为唯一开工门,消除多分叉。
- **[low]** 【end=true 且 text 为空:speak('') early-return 无害——已核实正确,但 main 的 speak 还会先 set replyEl/lastReply/machine.send 吗?】实测 main.ts speak L235 `if(!text) return` 在最前,确实在设 replyEl 之前 early-return,规格『无害』成立。这条不是 bug,但规格说『loop 仍 break,别因 text 空跳过 break』需要一条用例钉死,而 TDD 清单没有 end=true&&text='' 的用例。
  - fix: 补一条小用例:submitPrompt 返回 {text:'', end:true} → 断言不调用 speak(或 speak('') 不进 calls)且 runSession 退出。成本极低,把规格自己点名的边界钉死。

---

## Codex 复核(已接受,2026-06-13)

**CRITICAL — 硬依赖未满足**:Phase 3 的 `{text,end}` **代码里还不存在**(`session.ts:39`/`rpc.ts:133` 的 `submitPrompt` 仍返回 `Promise<string>`,`main.ts:352/385` 仍按 string 念)。**Phase 4 必须在 Phase 3 合入后才能开工**,不可并行。

**HIGH — 空闲判定落点(核心硬伤)**:idle 基线必须在**一轮真正结束之后**复位,不能在"转写到达"时复位。否则一次长 `submitPrompt`(`session.ts:79→84` 之间)会让下一个 listen=null 窗口被误判为静音。spec 的"成功转写即 reset idle"措辞要改成"轮完成后 reset"。

**接受的修正**:
- 计时源:必须钉**单一可注入时间源**(实际 `autoListen` 用 `performance.now()`/`setTimeout`/`setInterval`,见 `main.ts:273/288/290`),否则 fake-timer 测试 false-green。
- "先念完告别再隐身":`speak(reply)` 在 `session.ts:84` await、隐身在 `finally`(`:101`);加 `reply.end` 后必须显式钉死顺序,否则竞态。
- 引用修正(实际路径 `hud-app/hud/src/...`):`submitPrompt` 在 `rpc.ts:133`(非 155-163);`SESSION_TIMEOUT_MS` 在 `main.ts:262`;`BUSY_MAX_S` 在 `dev_server.py:127`。
- OK(无需改):跨进程常量已对齐(`BUSY_MAX_S=240 > SESSION_TIMEOUT_MS=180`);TTS 期 busy 抑制已由现有 `session.ts:67→102` + `dev_server` 拒唤醒覆盖。
