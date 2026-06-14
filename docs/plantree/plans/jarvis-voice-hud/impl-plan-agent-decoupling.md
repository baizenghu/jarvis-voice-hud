# 实施计划:从现状迁到"agent 黑盒"解耦边界

依据 [decisions/0007-agent-decoupling-text-blackbox.md](decisions/0007-agent-decoupling-text-blackbox.md)。
目标边界:**贾维斯 = STT+TTS+HUD+loop;agent = 文本进 `{text,end}` 出的黑盒;MCP/skill 全在 agent 内部。**

> **总纪律:系统已跑通(Phase 3 真机验收过),绝不一次性大改。** 用扩展-收缩(expand/contract):
> 每步可独立验证、可热回退;后端**双发新旧**、前端 feature flag 切、真机验证后再删旧分支。
> 绝不在一个 commit 里同时换契约形状 + 排序 + 分发。

## 各阶段详细实施规格(已 workflow 产出 + Codex 逐份审查,2026-06-13)
`specs/` 下每阶段一份(read 前先看,含 file:line、TDD 测试清单、expand-contract 步、真机门、风险):
- [specs/phase2-say-text-sanitizer.md](specs/phase2-say-text-sanitizer.md)
- [specs/phase3-text-end-boundary.md](specs/phase3-text-end-boundary.md)(核心)
- [specs/phase4-dual-standby.md](specs/phase4-dual-standby.md)
- [specs/phase5-voice-service.md](specs/phase5-voice-service.md)

每份末尾有 **"Codex 复核(已接受)"** 节,优先于规格正文。跨阶段关键结论:
- **排序硬约束**:阶段2 应在阶段3 **之前**(接 chatty agent 前置);阶段4 **必须**在阶段3 合入后(依赖 `{text,end}`,代码里尚不存在);阶段5 与阶段3 同改 `rpc.ts` 但**方法不相交**——阶段5 逻辑挪到新 `voice_http.ts` 即可,需协调。
- **阶段2 策略变了**:`hermes_cli/voice.py:784-797` 已有 sanitizer 且 `speak_text` 在用 → **复用/抽共享模块**,不新写;唯一未 sanitize 的是 `synthesize_bytes`(HUD 的 `voice.synthesize`)。
- **阶段3 BLOCKER**:gateway auto-TTS(`server.py:5605-5609`,`HERMES_VOICE_TTS=1`)与 HUD TTS 双路;真机门必须 `HERMES_VOICE_TTS=0`。
- **阶段5 BLOCKER**:独立服务裸 `/transcribe`/`/synthesize` 不在 `/api/*` 下,阶段1 鉴权门覆盖不到,需自带。

## 状态图例
`[ ]` 待办 · `[~]` 进行中 · `[x]` 完成(需 commit / 测试绿 / 真机验收之一为证)

---

## 阶段 0 —— 对账与立基线(纯代码层,1–2 天)
迁移的真正起点,先拿到可信"迁移前绿"。
- [x] 跑 `pytest tests/test_voice_hud_contract.py`,确认它当前是 red 还是 skip;**先修它反映现实**
      (后端只 `register('end_session')`),拿到可信基线。
  - 基线结果(2026-06-13):**RED**(非 skip),正如预测——assert `play_music`/`stop_music` 但实际
    只注册 `end_session`,且 `dispatch('play_music')` 是 no-op(返回 `[]`)。注意:**须用项目 `.venv`
    (`uv run --no-sync python -m pytest`)**,anaconda base 跑会先撞 FastAPI/starlette 版本不兼容
    (`Router.__init__() got an unexpected keyword argument 'on_startup'`),那是环境问题不是契约问题。
  - 已修测试反映现实:断言 `end_session` 可见 + `play_music`/`stop_music` **不可见**(退役前向守卫) +
    `dispatch('end_session')` 广播 `{type:end_session}` 返回"会话结束"。**2 passed**,可信绿基线到手。
- [x] 产出**出货路径(Tauri HUD + `tui_gateway.entry.main`)与 `dev_server.py` harness 的差异清单**——
      契约以出货路径为基线,不是以自称 "Dev-only" 的 harness。
  - **结论(2026-06-13):出货路径与 dev_server 是同一条,不存在分叉**——担心的"以 harness 当基线"不成立。
    - 家里 `start_jarvis.sh` + Windows 出货 `start_gateway.bat` **都直接启动 `hud-app/dev_server.py`**;
      真网关入口 `tui_gateway.entry.main` / `hermes web` **无任何脚本/壳引用**。
    - Tauri 壳连它:`shell/src-tauri/tauri.conf.json:7` `frontendDist=../../hud/dist`;
      `shell/src-tauri/src/main.rs:12` 注入 `__JARVIS_WS_URL__ = ws://127.0.0.1:8765/api/ws`;
      `/api/events` 由 `hud/src/main.ts:112` 同源派生。
    - ⚠️ **`dev_server.py` 顶部 docstring "not part of the shipped product" 是过时且反向的——它就是出货后端。**
      (建议一处文档级修正,纠正这句误导,防止有人当临时代码丢弃;非阻塞,可随迁移顺手改。)
  - **契约基线 = `dev_server.py`(WakeHub + `/api/events` + `/api/wake` + voice_hud 注册 + 两处 monkeypatch +
    `/api/audio_level|music_state|music_duck|music`)叠在 `tui_gateway.ws.handle_ws`(真 RPC dispatch)之上。**
  - **真·dev-only(不在 Tauri 出货链路)**:`/harness` + `voice-harness.html`(Phase 0 浏览器 smoke)、
    dev_server 的 `StaticFiles` 提供 `hud/dist`(仅浏览器直访用;Tauri 自己加载 `frontendDist`)。
- [x] 决定死路径去留:`play_music`/`stop_music`(webview 工具已退役,音乐走外部浏览器 skill)
      **彻底退出消息契约**,只留 `end_session` 语义。
  - **判断(2026-06-13):去,但并入阶段 3,本阶段不删。**
  - 死活核实(端到端全死):handler 存在但**无人注册**(`dispatch('play_music')` no-op,agent 触发不了)/
    **无活发送方**(仅 handler 自广播、`ws_tool_smoke.py:18` 只监听)/ 前端 `session.ts`+`main.ts:140-144`
    消费机器在但永不触发。真实音乐 = `gequbao_play.py`(CDP)+ `/api/music_state` + `/api/music_duck`,
    与 play_music 无关。
  - 为何不现在删:前端那半(Action union / RANK / drain / `session.test.ts`)**正是阶段 3 要重写的**
    (end_session 从广播事件变 `{text,end}` 返回),现在删=碰两次。危险半(agent 误拿到死工具)**已被
    阶段 0 契约测试焊死**(断言 play_music/stop_music 对 agent 不可见)。
  - 阶段 3 一并删除清单:`voice_hud_tools.py:23-31`(两 handler)、`tests/test_voice_hud_tools.py`(对应单测)、
    `hud/src/voice/session.ts`(union/RANK/drain 分支)、`hud/src/main.ts:140-144`、`session.test.ts` 排序用例、
    `ws_tool_smoke.py:18` 监听。打成一个"音乐退出契约"的完整 commit。
- ~~核对真机部署 unknown~~ → **移到阶段 5 前置**(2026-06-13 重新归位):这不是"基线",是语音服务抽独立的
      前置调查,只对阶段 5 有用,对阶段 1-4 零影响,现在查是过早。详见阶段 5 + 文末"必须真机先验"清单。

> **阶段 0 已收口(纯代码层,无需真机)**:可信基线 = 契约测试绿(Codex 复核)+ 契约基线确认为 `dev_server.py`
> (非分叉 harness)+ 死路径定性。真机调查归阶段 5。

## 阶段 1 —— 鉴权门(🔴 接任何远程 agent 前的前置,纯加法)
- [x] RPC/WS/HTTP 入站加共享密钥校验;**绑非 localhost 时强制 token,fail closed**。
  - 实现(2026-06-13,TDD)= `hud-app/dev_server.py`:`_auth_required(host)`(loopback 放行/其余需鉴权)、
    `_token_ok`(常量时间比对 env `JARVIS_GATEWAY_TOKEN`)、`_authorized`、HTTP `/api/*` middleware、
    WS `/api/ws`+`/api/events` handler 内守(WS 走不同 scope,middleware 拦不到)、`__main__` 调
    `_enforce_fail_closed`(非 loopback 且无 token → `SystemExit`)。token 经 `?token=` 查询参(WS+HTTP 通用)。
  - 测试 `tests/test_voice_hud_auth.py`;契约+tools 无回归。
  - **Codex 审查(复核后全部接受,TDD 修复)**:① HIGH——`_AUTH_REQUIRED` 曾在 import 期冻结 + fail-closed 仅在
    `__main__` → 非 `__main__` 入口(`uvicorn dev_server:app`)绕过。修:鉴权决策改 **live**(`_auth_enabled()` 每次读
    env)+ 加 **startup hook** 调 `_enforce_fail_closed`(任何入口生效)。**残留(已在代码注释 + 此处记录)**:决策以
    env `HOST` 为"声明的绑定",看不到 uvicorn `--host` CLI,故启动器绑非 loopback 时**必须同时设 HOST env**(出货脚本已设)。
    ② MEDIUM——WS 路径无测试 → 补 `/api/ws`+`/api/events` 拒绝/放行测试。③ MEDIUM——`?token=` 进日志(见下,接受为残留);
    附带 `_token_ok` 加 try/except 防非 ASCII token → 500。修复后 **24 passed**(auth+契约+tools 全绿)。
- [x] 验收:无 token 连接被拒(401 / WS close 1008);localhost 默认行为不变(`_AUTH_REQUIRED=False` 全放行)。
- [ ] **部署侧后续(非 loopback 实际启用时才需,当前两端都绑 127.0.0.1 故未触发)**:让客户端带 token——
      Tauri 壳 `shell/src-tauri/src/main.rs` 注入的 WS URL、`kws_listener.py`/`audio_levels.py`/`gequbao_play.py`
      对 `/api/*` 的 POST 都要附 `?token=`,否则远程绑定后会被自己的客户端拒。**服务端门已建好,客户端透传留到真要远程暴露时做。**
  - ⚠️ 已知小代价:token 走查询参可能进访问日志(可信 WG 网内可接受);要更严可改 header,但 WS 浏览器端设不了 header。

## 阶段 2 —— say/text 分离 + sanitizer(🔴 接 chatty agent 的硬门槛)
- [x] TTS 入口加确定性 sanitizer:剥 markdown(`**`/反引号/代码块)/URL,得纯口语。
  - 实现(2026-06-13,TDD,按 Codex 复核策略=**复用不新写**):新建 `tools/tts_sanitize.py`
    `sanitize_for_speech()`(从 `hermes_cli/voice.py` 已有 inline 块**逐字抽取**,单一真相源);
    `tui_gateway/voice_bytes.py` + `hud-app/voice_bytes_vendored.py` 的 `synthesize_bytes` 在 `mkstemp` **之前**
    sanitize + sanitize 后空再短路(避免空音频报 5028);`speak_text` 改调共享函数(删重复块 + 孤立的 `import re`)。
  - 测试:`tests/test_tts_sanitize.py`(14)+ `test_voice_bytes.py` 加 sanitize-before-engine(断言精确输出)/
    sanitize-to-empty-skip/**vendored 字节 parity 守卫**。**49 passed**,无回归。两 voice_bytes 文件 byte-identical。
- [ ] agent 侧注入 voice system 提示(短句、纯口语)——**运行期 SOUL.md,非仓库代码**;部署时给 voice agent 加一句,本 commit 不含。
- [ ] **真机验收门(你来)**:喊一轮诱导 agent 回带 `**`/反引号/URL 的话 → 耳朵确认不念符号、正常中文韵律没变。

## 阶段 3 —— 定义 `{text, end}` 边界 + 适配器(核心)
把 agent 接口收敛成"文本进、`{text,end}` 出",`end` 提取归适配器。详细规格见 [specs/phase3-text-end-boundary.md](specs/phase3-text-end-boundary.md)。
- [x] **步骤 A —— 后端展开(双发,纯加法)**(2026-06-14,TDD):hermes 适配器把 `end_session` 翻译成 turn flag。
  - 机制:**复用 hermes 已有的 `tools.approval` session-key contextvar**(terminal_tool 同款,已在 tool 执行处生效)。
    `voice_hud_tools` 加 `set_end_flag` 注入;`end_session_handler` **双发**——旧 `_broadcast({type:end_session})` +
    新 `_end_flag()`(置 `dev_server._END_FLAGS[当前 session_key]`)。`dev_server` monkeypatch `server._emit`:
    `message.complete` 时该 session_key 在集合里 → payload 加 `end=True` 并清除。session-key 键 → turn-scoped、并发不串台、
    不依赖线程/sid。契约别名层,不碰 server.py 内部。
  - 测试 `tests/test_voice_hud_end_flag.py`(6):置位→end、未置→无、发射后清、并发不串台、非 complete 透传、handler 双发。
- [x] **步骤 B —— 前端展开(feature flag,默认 off=零行为变化)**(2026-06-14,TDD):
  - `session.ts`:`AgentReply{text,end}`、`SessionDeps.submitPrompt→Promise<AgentReply>`、加 `useReplyEnd`;
    `runSession` 念 `reply.text`,结束 `useReplyEnd ? reply.end : endedByBuffer`(互斥防双触发)。
  - `rpc.ts`:`replyEnd` 字段,`handleMessage` 读 `payload.end`,`submitPrompt` 返回 `{text,end}`,
    **`onclose` 同清 `replyEnd`**(Codex:防断线残留误退)。
  - `main.ts`:`USE_REPLY_END = window.__JARVIS_REPLY_END__ ?? false`(默认 off);dev textTurn 改 `reply.text`。
  - 测试 `session.test.ts`:flag-off 现状两例保留 + flag-on 三例(end=true 先念后退 / end=false 续 / 忽略 buffer end)。
    **vitest 8 passed + `tsc --noEmit` 0 + 后端 55 passed,无回归。**
- [x] **步骤 C —— 真机验收(2026-06-14,0.3 家里机)**:开 `__JARVIS_REPLY_END__=true`(经 ssh rsync 10 文件到 0.3 +
      flag sed on + `start_jarvis.sh`,带 `XAUTHORITY` 启 GUI)。**3 条全过**:退下念完告别才隐身 / 告别期尾音不重唤醒 /
      多轮不提前退场。`HERMES_VOICE_TTS` 空(默认 off,无双念)。
- [x] **步骤 D —— 收缩(2026-06-14,本 commit)**:agent 边界永久收敛为 `{text,end}`,删死契约。
  - 后端:`voice_hud_tools.py` 只剩 `end_session_handler`(置 flag,**删** play/stop handler + `_broadcast`/`set_broadcast` +
    旧 `{type:end_session}` 广播);`dev_server.py` 删随之变死的 `_safe_emit`/`_main_loop`/`safe_schedule_threadsafe` import +
    `set_broadcast` 注入(`_capture_loop`→`_on_startup` 只留 fail-closed)。
  - 前端:`session.ts` 删 `Action`/`RANK`/`orderActions`/`ActionBuffer` + `SessionDeps.{playMusic,stopMusic,buffer,useReplyEnd}`,
    `runSession` 结束**只认 `reply.end`**(先念完 text 再退);`main.ts` 删 `actionBuffer`/play-stop-end 事件 case/`USE_REPLY_END`/
    死 deps。
  - 测试:`test_voice_hud_tools`/`contract`/`end_flag`/`session.test.ts` 收缩到只守新边界。
    **后端 57 passed + vitest 18 passed + tsc 0 + npm run build 0**,无回归。
  - **[x] webview-music 退役(2026-06-14,独立 commit)**:落实"放歌=agent skill"。删 `audio.ts` 的 webview `<audio>`
    子系统(`playMusic`/`stopMusic`/`ensureMusic`/`gatewayBase`/`isMusicPlaying`/`duckForSpeech` + music 字段)、`main.ts`
    的 `resumeMusic` 机制(已全是 no-op)、`dev_server` 的 `/api/music` 代理 + `_proxy_stream`/`_resolve_stream_url`/
    `MUSIC_*` + 随之孤立的 `asyncio`/`httpx`/`quote`/`StreamingResponse` import、`start_jarvis.sh` 的 `MUSIC_UPSTREAM=`。
    决策 0006 加 superseded 横幅。**保留**:gequbao、`/api/music_state`/`music_duck`/`audio_level`、analyser/getBands/duck。
    57+18 passed + tsc/build 0。已核实与真实音乐链路解耦(`MUSIC_UPSTREAM` 只服务 `/api/music`)。
  - **仍留(非我所建)**:`hud-app/ws_tool_smoke.py`(tracked dev 脚本,成功判据依赖已删的 play_music 广播 → 失效;
    提请你定删/留)。
- 真机验收门:① 念"退下"先念完告别再隐身;② TTS 期 busy 抑制不破;③ 回声门控不回归;④ 同轮动作先做完再退场;
  ⑤ 长任务不被超时误退;⑥ **`HERMES_VOICE_TTS=0`(Codex blocker:网关 auto-TTS 与 HUD TTS 双念,家里默认 off 须确认)**;
  ⑦ flag 回退(`=false` 行为同今日)。

## 阶段 4 —— 双路回待机
- [x] 路①:agent `end=true` → 念完 `text` 再回待机(随 phase 3 落地)。
- [x] 路②:**空闲超时**(2026-06-14,TDD,前端 only)。`session.ts` 加 `now()` 单一时间源 + `idleTimeoutMs`;
      `runSession` 在 `listen()==null` 分支查 `now()-lastSpeechAt >= idleTimeoutMs` → 退场。**基线 `lastSpeechAt`
      只在"轮真正结束后"复位**(Codex:不在转写到达时,否则慢 submitPrompt 误判);长任务在 text 分支、不入静默计时。
      `main.ts` `IDLE_TIMEOUT_MS=30000` + `now: performance.now`。测试 3 例(静默退 / 说话重置基线 / 长任务不误退),
      vitest 21 passed + tsc/build 0,后端无关。
- [x] 对齐跨进程超时常量:`IDLE_TIMEOUT_MS=30s` ≪ `SESSION_TIMEOUT_MS=180s` < `BUSY_MAX_S=240s`;空闲退场让 busy 更早清,
      不破坏关系(已在代码注释记)。
- [ ] **真机验收(你来)**:喊"贾维斯"→"退下"立即退场(路①,已验过);不说话→约 30s 后自动退场(路②);
      长任务(查 skill/跑 terminal)期间不被误退。

## 阶段 5 —— 语音服务独立(difficulty 3,云 backend 留口不实现)
- [x] **STT 百度云 backend(2026-06-14,TDD,提前做)**:用户要求"语音识别改百度"。**收敛实现**——不重写整个
      独立服务,只在 `transcribe_bytes`(网关 STT 入口)加 `STT_BACKEND` 选择器:`=baidu` → `tools/baidu_stt.py`
      (ffmpeg 转 16k 单声道 PCM → 百度短语音识别 REST → 文本),**绕开中心 whisper、不用 GPU**;默认仍走 whisper,
      可一键回退(契合"backend local|baidu 可选")。两 voice_bytes 文件同步(parity)。测试 `test_baidu_stt.py`(6)+
      voice_bytes 路由 2 例,mock ffmpeg/HTTP,**44 passed**。
  - 🔴 **用户前提**:`BAIDU_STT_API_KEY`/`BAIDU_STT_SECRET_KEY`(百度智能云 语音应用)+ `STT_BACKEND=baidu`,
    设在 0.3 网关 env(**别提交密钥**)。可能要关梯子(百度国内云)。真机验:中文识别准确率/延迟 vs whisper。
    `BAIDU_STT_DEV_PID` 默认 1537(普通话含标点)。
- [ ] (原)`whisper_api` 重写成不依赖 `tools.voice_mode` 的独立 STT 服务——**STT 改百度后此项优先级降**(云 STT
      已不经 whisper);仅当要保留本地 whisper 作 backend 时才需。
- [ ] 统一契约:`POST /transcribe`、`POST /synthesize`、`GET /health`;`backend` 选 `local|baidu`(STT 侧已用 env
      选择器达成雏形;完整独立服务+TTS backend 仍待)。
- [ ] cosyvoice 侧基本现成(已零依赖独立 HTTP),仅对齐端点名 + backend 选择;保留 `_infer_lock`
      串行 + 短文本毒化补偿(`text+text`)两个生产事故约束。
- [ ] HUD 直连语音服务(`rpc.ts` 的 transcribe/synthesize 从 WS RPC 改 fetch);处理 CORS/跨机鉴权。

## 阶段 6 —— 后续能力(超出当前边界,需另开下行旁路;先记录不实施)
`文本→{text,end}` 请求-响应装不下,留作独立设计:
- [ ] TTS 流式首字延迟(`say.delta` 分片)。
- [ ] 长任务进度帧(60s 工具期 HUD 不再静默)。
- [ ] 打断 / barge-in(先做 double-talk 声学验证:已知 AEC 在 double-talk 下压不净)。
- [ ] agent 主动说话(定时提醒 / 长任务完成回报)。

---

## 必须真机先验、代码验不了的前提
1. STT 自打自环是否真被规避(启动环境未纳管)。
2. 中心 GPU(10.8.0.2)上 STT/TTS 真实部署形态。
3. double-talk 声学:全音量 TTS 时 analyser 能否稳定区分人声与回授(barge-in 前置)。
4. 单 GPU 12G:large-v3 + CosyVoice 已近上限;CosyVoice 全局 `_infer_lock` 串行 → 多并发会话第二个
   首字延迟 = 第一个整句合成时间(TTS 是共享单点单线程瓶颈)。
5. 若日后走 MCP/外部 CLI 当 agent:Codex/Claude Code headless 能否维持常驻多轮 + 端到端延迟。

## 调研出处
完整可行性/难度/盲点报告:多 agent workflow `wf_06743372-854`(4 现状核实 grounded 在代码 +
6 可行性评估 + 8 对抗 critic)。各 agent 适配器难度:自研 3(最适合当参考实现)、hermes 3、
Claude Code/Codex via MCP 5(架构倒置)、OpenClaw 4(甲死路 / 乙换骨)。
