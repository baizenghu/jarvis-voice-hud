# 实施规格 — 阶段 2:say/text 分离 + TTS sanitizer

依据 `docs/plantree/plans/jarvis-voice-hud/decisions/0007-agent-decoupling-text-blackbox.md`(🔴 风险条)与 `impl-plan-agent-decoupling.md` 阶段 2(`:77-80`)。

## 1. 目标 / 成功标准

接 chatty agent(Codex / Claude Code / 弱模型)前的硬门槛:agent raw 文本含 markdown 强调号、反引号、代码块、列表符号、URL,直灌 TTS 会逐字念"星号""反引号""http冒号斜杠斜杠"。本阶段加一个**确定性、纯 stdlib、无网络、无配置**的 sanitizer,在 TTS 合成入口前把文本压成口语。

成功标准(全部可测):
- 含 markdown(`**粗体**`、`` `code` ``、` ``` ` 围栏代码块、`#` 标题、`-`/`1.` 列表)的回复 → 念出来听不到任何标记符号。
- 含 URL(`https://example.com/a?b=c`)的回复 → 不逐字念 URL(替换成"链接"或剥成域名,见 §4 决策点)。
- 纯中文/纯英文正常句子 → **逐字不变**(sanitizer 不得吞正常内容)。
- 空/纯空白 → 维持现有 `synthesize_bytes` 的 `(b"", "")` 短路,不调引擎。
- 现有 `tests/tui_gateway/test_voice_bytes.py` 全绿(无回归)。
- `agent 侧 voice system 提示` 作为运行期配置点明(非仓库代码),spec 区分"代码兜底"与"运行期软约束"。

## 2. 关键架构发现(决定 sanitizer 落点)

TTS 唯一服务端入口 = `synthesize_bytes(text)`,**存在两个字节级完全相同的副本**:
- `tui_gateway/voice_bytes.py:65`(本 fork 的真入口)
- `hud-app/voice_bytes_vendored.py:65`(上游 Windows 部署缺 `tui_gateway` 包时的兜底副本;`gateway_voice_patch.py:18-21` 先 try fork、ImportError 再 fallback vendored)

二者 `diff` 确认 IDENTICAL。两条 RPC 注册(`gateway_voice_patch.py:38-49` 与 `tui_gateway/server.py:8989`)都最终调 `synthesize_bytes`。

→ **结论:sanitizer 必须落在 `synthesize_bytes` 内、调 `text_to_speech_tool` 之前(`voice_bytes.py:78`)。** 这是真正的"TTS 入口前",且 agent-agnostic:无论哪个 agent 吐什么,所有 TTS 路径(HUD agent 回复、招呼语、超时兜底、按住说话、文本轮)统一经此。

为何不放前端(`hud-app/hud/src/main.ts:234 speak()` / `rpc.ts:143 synthesize()`):
- 前端 sanitizer 只护 HUD 这一个调用方,`synthesize_bytes` 还被 `tui_gateway/server.py:8989` 直接调用(其它客户端),会漏。
- 阶段 5 计划把 STT/TTS 抽成独立服务,服务端 sanitizer 自然跟着走;前端逻辑会被 fetch 改写丢失。
- 服务端是单点,TS+Py 双份逻辑违反"最少代码"。

为何**不复用** `tools/tts_tool.py`:那是 hermes 全平台 TTS(Telegram/Discord 等),加 sanitizer 会改变非语音场景行为,越界(Surgical Changes)。

## 3. 改动文件清单(file:line)

### 3.1 新增:sanitizer 模块(stdlib-only,双副本,跟 voice_bytes 同样的 fork/vendored 模式)
- `tui_gateway/tts_sanitize.py`(新)— 导出 `sanitize_for_speech(text: str) -> str`。纯 `re`,无第三方依赖,无 IO,无 config。
- `hud-app/tts_sanitize_vendored.py`(新)— 字节级同上(上游 Windows 部署用)。
  - 理由:`voice_bytes_vendored.py:7` 注释明确"上游 Windows 缺 tui_gateway 包",sanitizer 若只放 `tui_gateway/` 下,vendored 路径 import 会炸。必须沿用既有双副本约定。
  - 维护提醒:两文件顶部各加一行注释"// 与 <对方路径> 必须保持一致(vendored for upstream Windows)",并在 PR 描述列出"改一处要同步另一处"。

### 3.2 接线:在两个 `synthesize_bytes` 里调用
- `tui_gateway/voice_bytes.py`:
  - 顶部 import:`from tui_gateway.tts_sanitize import sanitize_for_speech`(放在 `:16 from tools.tts_tool import ...` 同区)。
  - `:71-72` 空文本短路**之后**、`:78 text_to_speech_tool(text=text, ...)` **之前**插一行:`text = sanitize_for_speech(text)`,并在 sanitize 后**再判一次空**(sanitizer 可能把纯 URL/纯代码块压成空串)→ 空则返回 `(b"", "")`,不调引擎。
- `hud-app/voice_bytes_vendored.py`:同样改动,import 改为 vendored 路径(try fork import、except 用 `tts_sanitize_vendored`,与 `gateway_voice_patch.py:17-21` 同款双 import,或直接 `from tts_sanitize_vendored import sanitize_for_speech` —— 因为本文件本身就是 vendored 入口,直接配对 vendored sanitizer 最简单)。

### 3.3 不改但点明(运行期配置,非本 commit 代码)
- agent 侧 voice system 提示 = 运行期 `SOUL.md`(hermes 的 persona/system 提示文件),**不是仓库代码**。spec 要求"两手都要":sanitizer 是硬兜底,SOUL.md 加一句"语音模式:短句、纯口语、不要 markdown / 代码块 / 念 URL"是软约束。实现者**不在本 commit 改 SOUL.md**(那是运行期配置,且因 agent 而异),只在 PR 描述/交接里记一条 TODO:"部署时给 voice agent 的 SOUL.md 加纯口语指令"。

## 4. 决策点(实现者须在写 red 测试前定,二选一,建议默认)

**URL 处理**:
- 默认(建议):整个 URL token → 替换为 `"链接"`(中文)。简单、确定、不念乱码。
- 备选:剥成裸域名(`example.com` → "example dot com"?)——更复杂、收益低,**YAGNI,不做**。

**代码围栏块** ` ``` ... ``` `:整块**删除**(不念代码),不是"念内容去掉反引号"。行内 `` `x` `` → 保留 `x` 内容去掉反引号(短标识符念出来通常有用)。

## 5. TDD 测试清单(red-first)

新建 `tests/tui_gateway/test_tts_sanitize.py`(直接测纯函数,快,无 monkeypatch)。每条先红(函数还没实现/接线):

1. `test_strips_bold_markers`:输入 `"这是**重点**内容"` → 断言输出 `"这是重点内容"`(无 `*`)。
2. `test_strips_inline_code_backticks`:输入 `` "运行 `ls -la` 命令" `` → 断言含 `ls -la`、不含反引号。
3. `test_removes_fenced_code_block`:输入 `` "好的:\n```py\nprint(1)\n```\n完成" `` → 断言输出不含 `print(1)`、不含 ```` ``` ````,断言含"好的"和"完成"。
4. `test_replaces_url_with_链接`:输入 `"详见 https://example.com/a?b=c 这里"` → 断言不含 `http`、不含 `example.com`、含"链接"。
5. `test_strips_list_markers`:输入 `"- 第一\n- 第二"` 与 `"1. 甲\n2. 乙"` → 断言行首 `-`/`1.` 被去掉,内容保留。
6. `test_strips_heading_hashes`:输入 `"## 标题"` → 断言输出 `"标题"`(无 `#`)。
7. `test_plain_chinese_unchanged`:输入 `"今天天气不错,我们去散步吧。"` → 断言**逐字相等**(防误吞)。
8. `test_plain_english_unchanged`:输入 `"The meeting is at three pm."` → 断言逐字相等。
9. `test_collapses_whitespace_and_strips`:多行/多空格 markdown 清理后断言无连续空行、首尾无空白(给 TTS 干净输入)。
10. `test_pure_url_becomes_speakable_or_empty`:输入纯 `"https://x.com"` → 断言结果是"链接"(非空、非乱码)。

回归层(`tests/tui_gateway/test_voice_bytes.py`,改/补,验证接线):
11. `test_synthesize_bytes_sanitizes_before_engine`:monkeypatch `text_to_speech_tool` 捕获 `text` 实参,输入 `"念**这个**"` → 断言传给引擎的 `text` 不含 `*`(证明 sanitize 在调引擎前发生)。
12. `test_synthesize_bytes_sanitized_empty_short_circuits`:输入纯代码围栏块(sanitize 后变空)→ 断言**未调** `text_to_speech_tool`、返回 `(b"", "")`(复用现有空短路 fake 计数手法,见 `test_voice_bytes.py:23-37`)。
13. 现有 `test_synthesize_bytes_reads_engine_output`(`:8`)、`test_synthesize_bytes_empty_text_returns_empty`(`:23`)保持绿。

vendored 副本无独立测试(与 fork 字节相同;PR 描述声明同步)。前端**不加** TS 测试(本阶段不动前端)。

运行:`uv run --no-sync python -m pytest tests/tui_gateway/test_tts_sanitize.py tests/tui_gateway/test_voice_bytes.py`(用项目 `.venv`,**勿用 anaconda base**——会撞 starlette 版本,见 impl-plan `:21-23`)。

## 6. expand-contract 分步(每步可验证可回退)

本阶段是**纯加法**(新模块 + 入口前插一行),无契约形状变更、无双发/feature-flag 需求(sanitizer 对正常文本是幂等近似——见测试 7/8)。但仍分小步:

- **步 1(红)**:只建 `tests/tui_gateway/test_tts_sanitize.py`(测 1-10),引用尚不存在的 `tts_sanitize.sanitize_for_speech` → 全红(ImportError)。验证:pytest 报 collection/import error。回退:删测试文件。
- **步 2(绿)**:写 `tui_gateway/tts_sanitize.py` 实现 → 测 1-10 绿。验证:`pytest test_tts_sanitize.py` 全绿。回退:删模块(测试回到红)。
- **步 3(接线+回归)**:在 `tui_gateway/voice_bytes.py:synthesize_bytes` 插 import + sanitize 调用 + sanitize 后空短路;补回归测 11-12。验证:`pytest test_voice_bytes.py test_tts_sanitize.py` 全绿。回退:revert voice_bytes.py 单文件(sanitizer 模块留着无害)。
- **步 4(vendored 同步)**:复制 `tts_sanitize.py` → `hud-app/tts_sanitize_vendored.py`,接线 `hud-app/voice_bytes_vendored.py`。验证:`diff tui_gateway/tts_sanitize.py hud-app/tts_sanitize_vendored.py` 仅顶部注释差异(或完全相同);`diff` 两个 voice_bytes 仅 import 路径差异。回退:删 vendored 改动(fork 路径不受影响)。
- **真机步**(代码验不了,见 §7):一句话 commit 后真机喊一轮,让 agent 回带 markdown/URL 的话,耳朵确认不念符号。

每步独立 commit;**绝不**把"建模块 + 接线 fork + 接线 vendored"挤进一个 commit(便于 bisect / 单文件回退)。

## 7. 真机验收门(代码验不了)

1. 真机喊"贾维斯",诱导 agent 回一段含 `**`、`` ` ``、URL 的话 → **耳朵确认**:不念"星号/反引号/aitch-tee-tee-pee"。自动化测只能证字符串干净,念出来的听感(尤其中英混读、URL 替换词"链接"是否自然)必须人耳过。
2. 确认 sanitizer 没把正常中文/标点念秃(逗号停顿、句末语气)——sanitizer 只剥 markdown/URL,不应动标点;真机听一句普通回复确认韵律没变。
3. (软约束)若已给 voice agent 配 SOUL.md 纯口语提示,确认提示生效后 raw 文本本身就更干净(sanitizer 命中率应下降)——验证"两手"协同。

## 8. 风险

- **误吞正常内容**:中文里出现的 `*`(很少)或英文里 `_my_var_` 被当强调剥掉。缓解:正则只匹配**成对**强调标记且内部非空;测 7/8 守正常句不变;倾向"宁可漏剥也不误吞"(漏剥最多多念一个符号,误吞改变语义)。
- **代码块删除过激**:把看似围栏实则正常文本的内容删掉。缓解:只匹配标准 ` ``` ` 围栏(行首三反引号),不猜测。
- **双副本漂移**:`tts_sanitize.py` 与 vendored 副本日后改一处忘另一处。缓解:顶部注释 + PR 描述声明 + 可选加一条 CI/测试 `diff` 断言(YAGNI,先靠纪律)。
- **URL 替换词不自然**:"链接"在英文语境里突兀。本阶段接受(默认中文 HUD);跨语言留后续。
- **sanitize 后变空导致"静默轮"**:agent 只回了个代码块 → TTS 空 → 用户听不到任何反馈。缓解:§3.2 空短路返回 `(b"","")`,前端 `main.ts:243-247 speak()` 已处理 `syn` 为 null(只显文本不出声)——可接受;真机门 §7.1 留意。

## 9. 依赖与排序

- **依赖**:无硬代码依赖于阶段 1/3。阶段 1(鉴权)已完成且不碰 voice_bytes;阶段 3 才动 `voice_hud_tools.py`/契约。本阶段与 3/4 **零文件冲突**(不碰 `session.ts`/`main.ts`/`voice_hud_tools.py`/`dev_server.py`/契约测试)。
- **排序**:决策 0007 列为接 chatty agent 的"前置硬门槛",应在阶段 3(定 `{text,end}` 边界、接 Codex/CC 适配器)**之前**落地,否则一接 chatty agent 立刻念符号。
- 可与阶段 1 的"部署侧 token 透传"(impl-plan `:72`)并行,互不碰。

## 10. 明确不做(YAGNI)

- 不做可配置 sanitizer(无 config 项、无 provider 分支)。
- 不做前端 TS sanitizer(服务端单点已够)。
- 不改 `tools/tts_tool.py`(hermes 全平台 TTS,越界)。
- 不做 URL→裸域名朗读、不做 emoji 处理(除非真机发现 agent 大量吐 emoji,留后续)。
- 不在本 commit 改 SOUL.md(运行期配置,记 TODO 即可)。
- 不动阶段 3 的契约/前端 union/`end_session`。


---

## 元数据(workflow 抽取)

**改动文件**:
- tui_gateway/tts_sanitize.py (新)
- hud-app/tts_sanitize_vendored.py (新)
- tui_gateway/voice_bytes.py (接线: import + synthesize_bytes:71-78 区插 sanitize + sanitize 后空短路)
- hud-app/voice_bytes_vendored.py (同上,vendored import 路径)
- tests/tui_gateway/test_tts_sanitize.py (新, red-first)
- tests/tui_gateway/test_voice_bytes.py (补回归: sanitize-before-engine / sanitized-empty 短路)

**依赖/冲突**:
- 与阶段 3/4 零文件冲突:本阶段不碰 voice_hud_tools.py / dev_server.py / session.ts / main.ts / 契约测试
- 应排在阶段 3(接 chatty agent 适配器)之前落地,否则接 Codex/CC 立即逐字念 markdown 符号
- sanitizer 必须双副本同步: tui_gateway/tts_sanitize.py 与 hud-app/tts_sanitize_vendored.py(沿用 voice_bytes 的 fork/vendored 约定,因上游 Windows 部署缺 tui_gateway 包)

**真机验收门**:
- 真机喊一轮,诱导 agent 回含 **/反引号/代码块/URL 的文本,人耳确认 TTS 不逐字念符号(自动化只能证字符串干净,念出来的听感+中英混读+URL 替换词'链接'是否自然必须人耳过)
- 真机听一句普通中文回复,确认 sanitizer 没动标点韵律(逗号停顿/句末语气没变秃)
- 若已配 voice agent 的 SOUL.md 纯口语提示,确认软约束生效后 raw 文本更干净、与 sanitizer 协同(两手都要)

**风险**:
- 正则误吞正常内容(中文偶发 * 或英文 _var_ 被当强调剥):靠'只匹配成对非空标记'+ 正常句逐字不变测试守,倾向宁漏剥不误吞
- 双副本(tts_sanitize.py / vendored)日后改一处忘另一处:顶部注释 + PR 声明 + 可选 diff 断言
- agent 只回代码块 → sanitize 后空 → 静默轮:空短路返回 (b'','') ,前端 speak() 已容忍 null(只显文本),真机门留意
- URL 替换词'链接'在英文语境突兀:本阶段接受(中文 HUD),跨语言留后续
- 误把正常三反引号文本当代码块删除:只匹配行首标准围栏,不猜测


---

## workflow 对抗 critic(待 Codex 复核合并)

**verdict**: 方向正确、落点判断准(sanitizer 收口在 synthesize_bytes 是对的,双副本/fork-vendored 约定也对,YAGNI 边界基本克制)。但【不能直接照单执行】,有 3 个 high 必须先补:(1) vendored 接线与 step4 diff 验证门自相矛盾(两 voice_bytes 当前字节相同,spec 描述会让验证门失败);(2) 误吞反例(snake_case / 数学 *)缺红线测试,贪婪正则能蒙混过现有 10 条;(3) 不闭合代码围栏会吞掉后续正文(流式截断高频),测清单完全没覆盖。另有 2 个 medium 影响正确性:sanitize 后空判必须插在 mkstemp(:74) 之前否则泄漏临时文件(spec 行号区间太宽);静默轮缓解机制描述与实际 RPC 层(转 error 5028 而非返回空)不符。建议补完上述后再开工。还缺:不闭合围栏/奇数反引号的确定性行为定义、下划线强调是否处理的明确表态、一条 RPC 级空短路回归测或显式声明不测、一个不依赖 'agent 恰好吐 markdown' 的确定性真机验证路径(直接对 voice.synthesize 灌已知文本)。建议把双副本 diff 断言从 YAGNI 上调为本阶段做(5 行,替代靠人记忆的同步纪律)。

- **[high]** §3.2 vendored 接线自相矛盾,会让 step 4 的 diff 验证门必然失败。spec 一边要求 hud-app/voice_bytes_vendored.py 改 import 为 vendored 路径(from tts_sanitize_vendored import ...),一边在 step 4 验证里写 'diff 两个 voice_bytes 仅 import 路径差异'。但实测当前两个 voice_bytes.py 是【字节完全相同】(连 import 都一样,都是 from tools.tts_tool import ...,没有任何 tui_gateway. 前缀的差异)。一旦给 vendored 加 `from tts_sanitize_vendored import sanitize_for_speech`、给 fork 加 `from tui_gateway.tts_sanitize import sanitize_for_speech`,两文件就【不止 import 一行差异】——实现者照 spec 走会发现验证门描述与现实对不上,浪费时间排查。
  - fix: 明确写死:fork 加 `from tui_gateway.tts_sanitize import sanitize_for_speech`,vendored 加 `from tts_sanitize_vendored import sanitize_for_speech`(bare,因 dev_server.py:50 已 sys.path.insert(0, HERE))。step 4 的验证门改成 'diff 两个 voice_bytes 仅 sanitize 的 import 行差异(1 行)' 而非 '仅 import 路径差异'(易误读为整体同一行)。
- **[medium]** 漏掉真正的 TTS 入口副本之一:tools/tts_tool.py 不是唯一,但 voice.synthesize 的 RPC handler 在 server.py:8998 与 gateway_voice_patch.py:44 各自【函数内 lazy import】synthesize_bytes。spec 说 'sanitizer 落在 synthesize_bytes 内' 是对的(两条 RPC 都收口到它),这点没问题。但 spec 没点出 server.py 的 handler 在 sanitize 后变空时会返回 error 5028 'synthesis produced no audio'(见 server.py:9000-9002 与 patch:45-46),【不是】返回 (b'','') 让前端静默。即:agent 只回代码块时,RPC 会回一个 JSON-RPC error,前端 rpc.synthesize() 走 catch 分支。spec §8/§3.2 把静默轮的缓解描述成 '空短路返回 (b'','') + 前端容忍 null',与实际链路(RPC 转成 error → 前端 catch)不符。
  - fix: 在 §8/§3.2 写清实际行为:sanitize 后空 → synthesize_bytes 返回 (b'','') → RPC handler 把空 audio 转成 error 5028 → 前端 rpc.synthesize() throw → speak() 进 catch 只 log。因为 speak() 在调 synthesize 【之前】已 replyEl.textContent=Jarvis:... 设了文本,所以静默轮仍能看到文字,结论(可接受)不变,但缓解机制的描述要改对,否则实现者验回归测 12 时会困惑 RPC 层为何报 error 而非静默。
- **[low]** 回归测 12(test_synthesize_bytes_sanitized_empty_short_circuits)只测 synthesize_bytes 层返回 (b'','') 且未调引擎,【没测到】RPC 层把这个空结果转 error 的行为。而真正影响用户(静默轮)的是 RPC 层。spec 自己在 §2 强调 '两条 RPC 都调 synthesize_bytes',却没要求一条 RPC 级回归测覆盖 'sanitize 后空 → voice.synthesize 返回 error 5028'。现有 test_voice_bytes.py:82 已有 RPC dispatch 测试范式可复用。
  - fix: 可选补一条:server.dispatch(voice.synthesize, text=纯代码围栏) → 断言 resp 含 error(5028)。或在 spec 里显式声明 'RPC 层 error 转换不在本阶段测试范围,靠现有 5028 路径',避免实现者以为漏测。
- **[medium]** sanitizer 与现有 tools/voice_mode 的 whisper 幻觉过滤、以及 transcribe_bytes 的 strip 行为无关,但 spec 完全没提 synthesize_bytes 现有的 '.mp3 优先 .ogg fallback' 逻辑(voice_bytes.py:83-96)会不会被 sanitize 后空短路绕过——实际不会(短路在 78 行前),但 spec §3.2 说 '插在 :71-72 空短路之后、:78 之前',要求 'sanitize 后再判一次空 → 返回 (b'','')'。这意味着新增的第二次空判要【在 mkstemp(74) 之前】,否则会创建临时文件再返回、泄漏 fd/文件。spec 给的行号区间(71-78)正好把 mkstemp(74) 夹在中间,实现者若把 sanitize+空判插在 74 之后就会泄漏临时文件。
  - fix: 明确:sanitize 调用 + 第二次空判必须插在 :71-72 短路块之后、:74 mkstemp 之前(即顺序:原空判 → text=sanitize(text) → if not text.strip(): return b'','' → mkstemp)。spec 写 'before :78' 太宽,要收紧到 'before :74 mkstemp'。
- **[high]** 正则误吞风险(§8)被低估且缺测试覆盖关键反例。spec 测 7/8 只测纯中文/纯英文正常句,但最危险的是【混合】场景:正常英文里的 snake_case(my_var_name)、数学/乘法语境的 *(2 * 3)、Markdown 风格但实为正常的连字符列表语义。测清单没有一条 '英文 _var_name_ 不被剥' 或 '2 * 3 不被当强调' 的守门测试,而 §8 自己承认这是主要风险。'倾向宁漏剥不误吞' 是对的方针,但没有 red 测试钉住它,实现者写贪婪正则也能过现有 10 条测试。
  - fix: 加 2 条红线测试:(a) test_snake_case_not_stripped: 'call my_func_name here' → 逐字不变(下划线不当强调);(b) test_asterisk_in_math_not_stripped: '面积是 2 * 3' 或 '用 * 通配符' → * 保留或至少内容不丢。强调正则只匹配【成对、紧贴非空白、且常见于 markdown 的】**...** 与 *...*,且 *...* 两侧需非字母数字边界,避免吞 snake_case 不适用(那是 _ )——所以 _..._ 强调【本阶段直接不剥】(中文 HUD 几乎不会出现 markdown 斜体下划线,YAGNI),只剥 ** 和单 *,降低误吞面。spec 应明确 '下划线强调不处理'。
- **[high]** 行内 code 决策(保留 x 去反引号)与代码围栏决策(整块删)在【嵌套/不闭合】边界没定义。agent 实际输出常见不闭合围栏(```python 后被截断没有结尾 ```)、单反引号不成对(英文撇号 it's 不涉及但 `半个反引号 常见于流式截断)。测清单无 '不闭合围栏' 与 '奇数个反引号' 用例。不闭合围栏若按 'until next ```' 匹配会把后续全部正文吞掉 → 严重静音/吞内容。
  - fix: 加测试 test_unterminated_fence_does_not_eat_rest: '说明:```python\nprint(1)' (无闭合) → 断言不把整段后文删空(要么删到行尾保留后续,要么 fallback 当行内处理)。实现上:围栏正则用非贪婪且要求成对闭合 ```...```;不成对的孤立 ``` 仅当作普通行删除该行标记,不吞正文。spec §4 必须补 '不闭合围栏' 的确定性行为。
- **[medium]** 真机门 §7 没有可执行的诱导脚本/最小复现命令,且依赖 'agent 恰好回 markdown'。chatty agent 是否吐 markdown 不可控,真机验收可能 flaky(喊一轮 agent 正好回纯口语就验不到)。同时 §7 是人耳门,但没给 '如何在不接 chatty agent 的前提下验证接线生效' 的代码侧 fallback(本阶段还没接 Codex/CC,阶段 3 才接)——本阶段真机时根本【没有 chatty agent】,只有 hermes/SOUL,默认就偏口语,可能整轮诱导不出符号。
  - fix: 补一个【确定性】真机验证路径:用 voice.synthesize RPC 直接打一条含 **/```/URL 的文本(curl 或前端 console 调 rpc.synthesize),人耳听播放——绕开 'agent 是否吐 markdown' 的不确定性。§7.1 改成 '直接对 voice.synthesize 灌已知 markdown 文本' 而非 '诱导 agent 回 markdown'(后者本阶段无 chatty agent,不可靠)。
- **[low]** 双副本同步靠纪律(§8 把 CI diff 断言列为 YAGNI)。但本仓库历史已多次踩 fork/vendored 漂移(voice_bytes 本身就是双副本)。一条 pytest 级 diff 断言成本极低(<5 行),把它列 YAGNI 是把已知高频坑留给未来。这不算过度抽象,是廉价护栏。
  - fix: 建议把 'tests 里加一条 assert 两个 sanitize 文件正文(去掉顶部注释行)逐字相等' 从 YAGNI 上调为本阶段就做——5 行测试,直接钉死漂移。这比 PR 描述里写一句 '记得同步' 可靠得多,且不违反 Simplicity(它替代了靠人记忆的纪律)。
- **[low]** spec 假设 agent raw 文本是【纯文本字符串】进 synthesize_bytes,但没核实 HUD agent 回复链路是否已在别处做过任何清理(如 render.py 的 markdown 渲染只走前端显示,不影响 TTS 文本来源)。若回复文本来源还经过别的 strip/transform,sanitizer 落点可能不是唯一真入口。spec §2 只 diff 了 voice_bytes 两副本,没追 'text 从哪来'(runSession→agent reply→哪个字段→speak/synthesize)。
  - fix: 补一句溯源:确认传入 synthesize_bytes 的 text 就是 agent 原始回复(经 main.ts speak() 的 text 参数 / RPC params.text),中间无其他清理。已读 main.ts:234 speak(text) 直接 rpc.synthesize(text),无中间清理——结论成立,但 spec 应显式记这条溯源,避免阶段 3 接适配器后落点假设失效。

---

## Codex 复核(已接受,2026-06-13)

> 4 份 spec 经 Codex 逐份审查 + 我 spot-verify 代码确认。本节为本阶段接受的修正,**优先于上文**。

**重大策略修正 — 复用已有 sanitizer,不要新写**(F8,已核实):
- `hermes_cli/voice.py:784-797` **已有一套完整 markdown/URL sanitizer**(fenced code/`[](url)`/裸URL/bold/italic/inline code/headers/list/hr/空行),且 `speak_text` 已在用它。
- 已核实**只有 `synthesize_bytes`(HUD 的 `voice.synthesize`)路径未 sanitize**;gateway auto-TTS(`server.py:5605-5609`,`HERMES_VOICE_TTS=1`)和 `voice.tts`(`server.py:8949-8951`)都走 `speak_text` → **已经 sanitize**。
- ⟹ 正确做法:把 `voice.py:784-797` 的逻辑**抽成单一共享模块**,`speak_text` 与 `synthesize_bytes` **都 import 同一个**(single source of truth)。这比"新写模块 + vendored 双副本"更对,也消解漂移风险(F4)。仅当 vendored Windows 路径 import 不到时才保留副本,并加 parity 测试。

**其余接受的修正**:
- F5:sanitize 必须放在 `mkstemp`(`voice_bytes.py:74`)**之前**,不只是 engine 调用(`:78`)之前。
- F6:sanitize 后变空 → `synthesize_bytes` 返回空 → RPC 把空音频转成 **error 5028**(`server.py:9000`),不是静默。spec 必须处理:sanitize 后为空则回退(保留原文 or 跳过出声),别让正常轮报 5028。
- F7:测试断言**精确 sanitized 字符串**,不只是"不含 `*`"。
- F8 边界红测:未闭合 fence、数学 `*`、snake_case、中英混排、中文标点。
- F2:点明 `voice.tts`/auto-TTS 走 `speak_text` 已 sanitize,本阶段只补 `synthesize_bytes`。
