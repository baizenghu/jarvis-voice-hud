# 阶段 5 实施规格 —— STT/TTS 抽成独立 HTTP 服务,HUD 直连

> 依据 `docs/plantree/plans/jarvis-voice-hud/decisions/0007-agent-decoupling-text-blackbox.md`
> 与 `impl-plan-agent-decoupling.md` 阶段 5(行 104-111)。
> **总纪律:绝不一次性大改;expand-contract(后端双发新旧、前端 feature flag 切、真机验收后再删旧);每步 TDD red-first;改动精准跟随现有风格。**

## 0. 目标 / 成功标准

把语音(STT/TTS)从「HUD → WS RPC(`voice.transcribe`/`voice.synthesize`)→ 网关进程内 `voice_bytes` → hermes 引擎」这条**绑在网关进程内**的链路,抽成一个**独立的 HTTP 语音服务**(下称 `voice_svc`),HUD 经 `fetch` 直连,不再经 agent/网关。

边界对齐 0007:贾维斯 = 嘴和耳朵(STT/TTS),语音服务是「嘴耳」的实现,与 agent 黑盒平行、互不依赖。

**成功标准(可验证):**
1. `voice_svc` 进程 **不 import `tools.voice_mode` / `tools.transcription_tools` / `tools.tts_tool` / `tui_gateway.*`**(grep 断言 + 进程可在剥离 hermes 的环境启动)。STT 质量不回退(large-v3 + VAD + 幻觉抑制 + 中文过滤 + `_JARVIS_ALIASES` 全搬过)。
2. 统一契约:`POST /transcribe`、`POST /synthesize`、`GET /health`,三端点齐全;`backend` 可选 `local|baidu`,**baidu 留接口不实现**(命中即 501 + 明确文案)。
3. CosyVoice 的两个生产事故约束保留:`_infer_lock` 串行 + 单可发音字符毒化补偿(`text+text`)。
4. HUD 经 feature flag 在「WS RPC(旧)」与「fetch 直连(新)」间切换;真机验收前两条都在。
5. 直连引入的 CORS + 鉴权(复用阶段 1 `JARVIS_GATEWAY_TOKEN`)就位,非 loopback fail-closed。

**明确不做(YAGNI):**
- 不实现 baidu 云 backend(仅留 provider 抽象的注册点 + 501)。
- 不做 TTS 流式 / barge-in / 长任务进度(0007 阶段 6,另开下行旁路)。
- 不重构 `tools/transcription_tools.py` 的 6-provider 体系、不动 `tui_gateway/server.py` 的其它 RPC。
- 不把 STT 模型从 large-v3 改小、不引入新依赖之外的「灵活性」。
- 不在本阶段删 WS RPC 路径(收缩留到真机验收后的独立 commit)。

---

## 1. 现状链路(已 grounded,file:line)

**STT 当前:**
- HUD `hud-app/hud/src/voice/rpc.ts:123-130` `transcribe()` → WS RPC `voice.transcribe`。
- 注册:`tui_gateway/server.py:8959`(fork)+ `hud-app/gateway_voice_patch.py:23`(upstream 兜底)。
- 实现:`tui_gateway/voice_bytes.py:33 transcribe_bytes` → `tools.voice_mode.transcribe_recording`(`voice_mode.py:899`)→ `tools.transcription_tools.transcribe_audio` → `_transcribe_local`(`transcription_tools.py:1115`,faster-whisper)。
- STT 调优散落两处:
  - 幻觉抑制 + 中文过滤:`voice_mode.py:824-893`(`WHISPER_HALLUCINATIONS` 集合、`_HALLUCINATION_REPEAT_RE`、`is_whisper_hallucination`)。
  - VAD / 解码参数:`transcription_tools.py:1136-1155`(`vad_filter=True`、`condition_on_previous_text=False`、`temperature=0.0`、`no_speech_threshold=0.6`、`compression_ratio_threshold=2.4`、`beam_size=5`、可选 `initial_prompt`、CUDA→CPU 回退 `_load_local_whisper_model:1088`、`_looks_like_cuda_lib_error:1076`)。
  - 助手名归一化:`hud-app/whisper_api.py:30 _JARVIS_ALIASES` + `_normalize_names`(**注意:此归一化目前只在 `whisper_api.py` 这个旁路 HTTP 壳里,HUD 主链路 `voice_bytes` 没有它**——搬迁时务必并入 `voice_svc` 主路径)。

**TTS 当前:**
- HUD `rpc.ts:143-150` `synthesize()` → WS RPC `voice.synthesize`。
- 注册:`server.py:8989` + `gateway_voice_patch.py:38`。
- 实现:`voice_bytes.py:65 synthesize_bytes` → `tools.tts_tool.text_to_speech_tool`(配置成 command provider)→ `hud-app/cosyvoice_say.py`(stdlib client)→ POST `cosyvoice_server.py:100 /tts`(`:8003`,已零依赖独立,`_infer_lock` `cosyvoice_server.py:97`、毒化补偿 `:108-114`)。
- 即:**CosyVoice 已是独立 HTTP 服务**,当前 HUD 只是绕了 WS RPC + tts_tool + command-provider + ffmpeg-transcode 一大圈才到它。

**HUD base-url 派生:** `rpc.ts:27 wsUrl()`(Tauri 注入 `window.__JARVIS_WS_URL__`,否则同源);HTTP 基址惯例 `main.ts:331`(`wsUrl().replace(/^ws/,"http").replace(/\/api\/ws$/,"")`)。直连语音服务需类似派生一个 `voiceSvcBase`。

**鉴权基线(阶段 1 已建):** `dev_server.py:68-110`(`_auth_required`/`_token_ok`/`_authorized`/`_enforce_fail_closed`/HTTP middleware/WS 守卫),token 经 `?token=` 查询参,env `JARVIS_GATEWAY_TOKEN` + `HOST`。`voice_svc` 直接复用这套**思路与常量名**(不 import dev_server,拷贝最小鉴权助手——它只有 ~30 行且已被阶段 1 测试焊死)。

---

## 2. 改动文件清单

**新增:**
- `hud-app/voice_svc.py` —— 独立 STT/TTS HTTP 服务(zero hermes import)。主体。
- `hud-app/voice_svc_stt.py` —— 搬迁后的 STT 引擎(faster-whisper + VAD + 幻觉过滤 + 中文过滤 + 名字归一化),供 `voice_svc` 调用。(拆出独立模块便于单测,不与 FastAPI 耦合。)
- `hud-app/start_voice_svc.sh` —— 启动脚本(对齐 `start_cosyvoice.sh` 风格,设 `HOST`/`PORT`/token)。
- `tests/test_voice_svc_stt.py` —— STT 引擎纯函数单测(幻觉过滤/名字归一化/契约形状)。
- `tests/test_voice_svc_http.py` —— HTTP 契约 + 鉴权 + backend 选择 + baidu 501 测试(用 FastAPI TestClient,STT/TTS 引擎 monkeypatch 成桩,不碰 GPU)。
- `hud-app/hud/src/voice/voice_http.ts` —— HUD 侧 fetch 直连客户端(`transcribeHttp`/`synthesizeHttp`/`voiceSvcBase`)。
- `hud-app/hud/src/voice/voice_http.test.ts` —— 客户端单测(URL 派生 / token 透传 / 错误降级)。

**修改:**
- `hud-app/hud/src/voice/rpc.ts` —— **(与阶段 3 冲突文件,见 §6)** feature flag 切换 transcribe/synthesize 到 fetch;旧 WS RPC 方法保留(双路)。
- `hud-app/hud/src/main.ts` —— 注入 `voiceSvcBase` / feature flag(若用 env/`window` 注入);调用点 `main.ts:216,243` 不改语义,只改它们背后走哪条路(由 rpc 内部 flag 决定,理想情况下 main.ts 零改动)。
- (可选,文档级)`hud-app/cosyvoice_server.py` —— 仅对齐:`voice_svc` 的 `/synthesize` 默认转发到它;**不改它的推理逻辑**。若决定让 `voice_svc` 直接进程内加载 CosyVoice 则不改 cosyvoice_server(见 §4 决策点)。

**收缩阶段(真机验收后,独立 commit)才动:**
- `tui_gateway/voice_bytes.py`、`hud-app/gateway_voice_patch.py`、`tui_gateway/server.py:8959/8989`、`rpc.ts` 旧分支。**本规格不删,只标记。**

---

## 3. 统一契约(冻结)

```
GET  /health
  → 200 {"ok": bool, "stt_backend": "local"|"baidu", "tts_backend": "local"|"baidu",
         "stt_ready": bool, "tts_ready": bool}

POST /transcribe        (multipart/form-data)
  file: <audio bytes>   (mime 由 Content-Type / filename 后缀推断,沿用 _MIME_TO_SUFFIX)
  backend: str?         (默认 env STT_BACKEND 或 "local")
  → 200 {"text": str}        (空串 = 静音/幻觉/回声,沿用现有「空文本=没听清」语义)
  → 501 {"error": "..."}     (backend=baidu)
  → 401                       (非 loopback 且 token 不符)

POST /synthesize        (application/json)
  {"text": str, "backend": str?}
  → 200 audio/wav 或 audio/mpeg 原始字节(见 §4 格式决策)
  → 400 {"error":"text required"}  /  500 合成失败
  → 501 backend=baidu / 401 未鉴权
```

**契约取舍:**
- `/transcribe` 用 multipart(对齐既有 `whisper_api.py:43` 与浏览器 `FormData`,前端不再 base64;比当前 WS 的 base64 更省一次编码)。
- `/synthesize` 返回**原始音频字节**(非 base64 JSON),前端 `await resp.arrayBuffer()` 直接喂 `audio.play`。当前 WS 路径回 base64 是 JSON-RPC 限制;HTTP 无此限制,去掉 base64 往返。
- backend 选择优先级:**请求体/表单 `backend` > env(`STT_BACKEND`/`TTS_BACKEND`)> "local"**。

---

## 4. provider 抽象 + 关键决策点

**STT provider 抽象(`voice_svc_stt.py`):**
```
def transcribe(audio_path: str, backend: str = "local") -> str  # 返回纯文本,空串=无效
```
- `backend=="local"`:搬迁的 faster-whisper 路径(§5.A)。
- `backend=="baidu"`:`raise NotImplementedError` → HTTP 层翻成 501。**留注册点不实现。**
- 不做 6-provider 通用体系(那是 hermes messaging 网关的需求,本服务只需 local + 未来 baidu)。

**TTS provider 抽象:**
- `backend=="local"`:转发到现成的 `cosyvoice_server.py:8003/tts`(stdlib `urllib`,照搬 `cosyvoice_say.py:30-55` 的 POST + 忽略代理 opener,**但不再 transcode 成 mp3**——直接回 CosyVoice 的 WAV,省一次 ffmpeg)。
- `backend=="baidu"`:501。

> **决策点 A(实现者需在 spec 评审时确认,默认取①):**
> ① **`voice_svc` 只做 TTS 的 HTTP 转发到独立的 `cosyvoice_server`(:8003)** —— 两个进程(STT+转发 svc 一个、CosyVoice 一个)。优点:不动已稳定的 cosyvoice_server、`_infer_lock`/毒化补偿天然保留在它内部、GPU 加载逻辑零搬迁。缺点:多一跳 localhost HTTP。**推荐①**(最小改动、风险最低)。
> ② `voice_svc` 进程内直接 `import cosyvoice` 加载模型 —— 省一跳但要把 `cosyvoice_server.py:63-137` 的模型加载/锁/毒化补偿全搬进来,且与 STT 抢同一进程的 GPU(12G 已近上限,见真机门)。**不推荐**,除非真机证明多进程显存吃不消。
>
> 若取①:`_infer_lock` + 毒化补偿**留在 cosyvoice_server.py 不动**(成功标准 3 自动满足);`voice_svc` 的 `/synthesize` 仅做参数校验 + 转发 + 错误翻译。

> **决策点 B(音频格式):** CosyVoice 回 24kHz WAV。当前链路 `cosyvoice_say.py:56` transcode 成 mp3 是为「HUD audio/mpeg 标签」。HUD 的 `audio.play(bytes, mime)`(`main.ts:245`)对 WAV 同样能放(浏览器原生支持 audio/wav)。**默认 `/synthesize` 直接回 audio/wav,去掉 ffmpeg 依赖与一次转码**;真机验收若发现 HUD 播 WAV 有兼容问题再加回 mp3 transcode(那是已知可逆的退路)。

**鉴权 + CORS(`voice_svc` HTTP 层):**
- 拷贝阶段 1 的 `_auth_required`/`_token_ok`/`_authorized`/`_enforce_fail_closed`(dev_server.py:68-99),env 同名 `JARVIS_GATEWAY_TOKEN`/`HOST`。token 经 `?token=` 查询参(与 WS 浏览器端无法设 header 的现实一致,dev_server.py:75 注释)。
- **CORS**:HUD 在 Tauri 下 origin = `tauri://localhost`,跨 origin fetch 需 `Access-Control-Allow-Origin`。参照 `dev_server.py:421` 注释(`/api/music` 已为 Tauri 加 CORS)。加 `CORSMiddleware`,allow_origins 含 `tauri://localhost` + `http://localhost:*`(dev 浏览器直访)。**multipart POST 会触发 preflight**(非简单请求),OPTIONS 必须放行且不要求 token。

---

## 5. 搬迁清单(STT 脱 hermes)

**搬入 `hud-app/voice_svc_stt.py`(从 hermes 拷贝,非 import):**

A. faster-whisper 加载 + 转写(源 `transcription_tools.py`):
- `_load_local_whisper_model`(:1088-1112)+ `_looks_like_cuda_lib_error`(:1076-1085)+ `_CUDA_LIB_ERROR_MARKERS`(:1064-1073)—— CUDA→CPU 回退,**整块搬**。
- `_transcribe_local` 的核心(:1136-1186):`transcribe_kwargs`(beam_size/vad_filter/condition_on_previous_text/temperature/no_speech_threshold/compression_ratio_threshold)+ 中途 CUDA 失败 evict+CPU 重试(:1160-1179)。
- 模型单例缓存(`_local_model`/`_local_model_name`,:111-112)。
- **简化**:删掉对 `hermes_cli.config._load_stt_config()` 的依赖,改成 env 配置:`STT_MODEL`(默认 `large-v3`,**注意**:hermes 默认 `base`,本服务真机用 large-v3,默认值要设对)、`STT_LANGUAGE`(默认 `zh`)、`STT_INITIAL_PROMPT`(可选,对应 git 未提交 diff `transcription_tools.py:1150-1155` 那个 code-switch 提示)。

B. 幻觉抑制 + 中文过滤(源 `voice_mode.py:824-893`):
- `WHISPER_HALLUCINATIONS` 集合(:824-873)、`_HALLUCINATION_REPEAT_RE`(:876-879)、`is_whisper_hallucination`(:882-893)—— **整块搬**。转写后命中 → 返回空串(对应 `voice_mode.py:920-922` 的 filtered 语义)。

C. 名字归一化(源未提交 diff `whisper_api.py:28-33`):
- `_JARVIS_ALIASES` + `_normalize_names` —— 搬入,**在过滤之后、返回之前**应用(注意:归一化前先判幻觉,避免归一化把"佳维斯"变成"贾维斯"后绕过过滤——但当前两者无交集,顺序按现状:transcribe→halluc filter→normalize)。

D. 音频落盘:沿用 `voice_bytes.py:23-30 _MIME_TO_SUFFIX` + `whisper_api.py:49-62` 的 tempfile 写入/清理(整块搬,zero hermes)。

> **注意 git 未提交 diff:** `whisper_api.py` 与 `transcription_tools.py` 当前工作区有未提交改动(名字归一化已在 whisper_api、initial_prompt 已在 transcription_tools)。**搬迁时以工作区现状为准**(把这两处增量也搬进 `voice_svc_stt.py`),并在收缩阶段决定这两个文件的去留(`whisper_api.py` 是 OpenAI-compatible 旁路壳,服务于「远程 hermes 当 STT」,与本 HUD 链路不同用途——**很可能保留**,不在本阶段删)。

---

## 6. 🔴 与阶段 3 同改 `rpc.ts` 的冲突 + 排序

**冲突事实:**
- 阶段 3(`impl-plan:89-94`)要改 `rpc.ts`:把 agent 回合从「WS `prompt.submit` + 监听 `message.complete` 事件」收敛到 `{text,end}` 返回,涉及 `rpc.ts:42-46,87-103,132-141` 的 reply-tracking 机制 + `submitPrompt`。
- 本阶段(5)要改 `rpc.ts`:把 `transcribe`(:123-130)/`synthesize`(:143-150)从 WS RPC 切到 fetch。
- **两者改同一文件,但改的是不相交的方法**(阶段3 动 `submitPrompt`/event 处理;阶段5 动 `transcribe`/`synthesize`)。冲突是「同文件 merge 冲突 + 测试基线漂移」,不是语义耦合。

**排序裁决:**
1. **阶段 5 不依赖阶段 3 的边界改动**(语音抽离与 `{text,end}` 正交)。但 `impl-plan` 把阶段 3 列在阶段 5 前,且阶段 3 是「核心」。
2. **推荐:阶段 5 在阶段 3 合并之后再动 `rpc.ts`**,避免两个分支同时改 `rpc.ts` 的 import 区/类成员区产生手工 merge。
3. **若必须并行:** 把阶段 5 的 fetch 客户端**完全放进新文件 `voice_http.ts`**,`rpc.ts` 里只改 `transcribe`/`synthesize` 两个方法体为「flag ? voice_http.transcribeHttp() : 原 WS 路径」——把对 `rpc.ts` 的触碰压到最小(2 个方法、约 6 行),与阶段 3 改的 `submitPrompt`/event 区物理隔开,降低 merge 冲突面。**本规格按此设计**(新逻辑全在 `voice_http.ts`)。
4. **测试基线:** 阶段 5 不碰 `session.test.ts`/`machine.test.ts`(那是阶段 3 的)。新增 `voice_http.test.ts` 独立。

**实现者必须做:** 动 `rpc.ts` 前先 `git log --oneline rpc.ts` 确认阶段 3 是否已落;若未落,只在 `voice_http.ts` 工作 + `rpc.ts` 最小双路桩,并在 PR 描述里标注「待阶段 3 合并后 rebase」。

---

## 7. TDD 测试清单(red-first)

**`tests/test_voice_svc_stt.py`(纯函数,无 GPU):**
1. `is_whisper_hallucination("谢谢观看")` → True;`is_whisper_hallucination("贾维斯你好")` → False。(断言中文过滤搬迁正确)
2. `is_whisper_hallucination("Thank you. Thank you.")` → True(repeat regex)。
3. `_normalize_names("Jarvis 你好")` → `"贾维斯 你好"`;`_normalize_names("夏威士在吗")` → `"贾维斯在吗"`。(断言名字归一化搬迁)
4. `transcribe(path, backend="baidu")` → raises `NotImplementedError`。
5. (monkeypatch faster-whisper 模型为桩)transcribe 命中幻觉 → 返回 `""`;正常文本 → 经归一化返回。

**`tests/test_voice_svc_http.py`(TestClient,STT/TTS 引擎 monkeypatch 成桩):**
6. `GET /health` → 200,含 `stt_backend`/`tts_backend`/`*_ready` 键。
7. `POST /transcribe`(multipart 桩音频,引擎桩返回 "你好") → 200 `{"text":"你好"}`。
8. `POST /transcribe` backend=baidu → 501,body 含明确文案。
9. `POST /synthesize` `{"text":"好的"}`(TTS 桩返回 wav bytes) → 200,Content-Type `audio/wav`,body=桩字节。
10. `POST /synthesize` `{"text":""}` → 400 "text required"。
11. `POST /synthesize` backend=baidu → 501。
12. **鉴权**:`HOST=0.0.0.0` 无 `JARVIS_GATEWAY_TOKEN` 启动 → `_enforce_fail_closed` SystemExit(对齐 dev_server 阶段1 测试)。
13. `HOST=0.0.0.0` + token 设置:无 `?token=` 的 `/transcribe` → 401;带正确 token → 200。
14. `HOST=127.0.0.1`(loopback):无 token 全放行(默认行为不变)。
15. **CORS**:`OPTIONS /transcribe`(Origin: tauri://localhost)→ 含 `Access-Control-Allow-Origin`,且 OPTIONS 不要求 token。

**`hud-app/hud/src/voice/voice_http.test.ts`(vitest,fetch mock):**
16. `voiceSvcBase()` 从 `window.__JARVIS_VOICE_URL__` 取覆盖;否则由 wsUrl 派生 http 基址。
17. `transcribeHttp(blob, mime)` POST multipart 到 `<base>/transcribe`,带 `?token=`(若 `window.__JARVIS_TOKEN__` 存在);返回 `result.text`。
18. `synthesizeHttp(text)` POST JSON,resp.ok=false → 返回 null(降级,对齐 rpc.ts:144-149 现有「错误回 null,前端只显文本」语义)。
19. fetch reject → 不抛、返回空串/null(对齐 `transcribe` 失败回 "")。

**Python 测试运行:** 须用项目 `.venv`(`impl-plan:22` 已记):`uv run --no-sync python -m pytest tests/test_voice_svc_stt.py tests/test_voice_svc_http.py`(anaconda base 会撞 starlette 版本)。

---

## 8. expand-contract 分步(每步可验证可回退)

**步骤 1(expand,纯加法,可独立验证):** 写 `voice_svc_stt.py` + `tests/test_voice_svc_stt.py`(red→green)。不接任何东西。验证:pytest 绿 + `grep -E 'import (tools|tui_gateway|hermes)' hud-app/voice_svc_stt.py` 无命中。回退:删文件。

**步骤 2(expand):** 写 `voice_svc.py`(HTTP 层 + 鉴权 + CORS + TTS 转发到 :8003)+ `tests/test_voice_svc_http.py`(red→green)+ `start_voice_svc.sh`。验证:pytest 绿;手动 `curl -F file=@sample.webm localhost:<port>/transcribe`(真机门,见 §9)。回退:删文件,旧 WS 链路完全不受影响。

**步骤 3(expand,前端):** 写 `voice_http.ts` + 测试(red→green)。`rpc.ts` 的 `transcribe`/`synthesize` 改为 `if (USE_HTTP_VOICE) return voiceHttp.xxx(); else <原WS路径>`,flag 默认 **false**(走旧路)。验证:flag=false 时行为与现状完全一致(回归);flag=true 时走新路。回退:flag 常 false。

**步骤 4(真机验收,翻 flag):** 真机把 `USE_HTTP_VOICE` 置 true(经 `window.__JARVIS_USE_HTTP_VOICE__` 注入或 build env),跑 §9 真机门。验收通过 → flag 默认改 true。未过 → flag 翻回 false,新代码留着不删,零损失回退。

**步骤 5(contract,独立 commit,真机验收稳定后):** 删 WS RPC 语音路径:`voice_bytes.py` 的两函数、`gateway_voice_patch.py` 的两注册、`server.py:8959/8989` 两 handler、`rpc.ts` 的旧 WS 分支 + `transcribe`/`synthesize` 的 flag 包装。`voice_bytes_vendored.py`/`ws_voice_smoke.py` 一并评估。**本规格不含步骤 5 的删除,只列清单。**

---

## 9. 真机验收门(代码验不了,前置 unknown)

> 对应 `impl-plan:52-53,122-128` 的「必须真机先验」。这些是**阶段 5 启动前置调查**,不解决不开工。

**前置 unknown(开工前查清):**
1. **`whisper_api.py`/voice 服务的真实启动环境**:`HERMES_HOME`、faster-whisper 模型缓存位置、CUDA 运行时是否齐(`libcublas`/`libcudnn`)——决定 `voice_svc` 能否真「脱 hermes」启动还是仍隐式依赖 hermes 的 env/模型目录。
2. **中心 GPU 10.8.0.2 的真实部署形态**:STT/TTS 是否都跑在中心 GPU?`voice_svc` 与 cosyvoice_server 部署在中心还是本机?HUD 直连的目标地址(loopback / LAN / WireGuard)= 决定鉴权是否真的被触发(loopback 默认放行,LAN 才需 token)。
3. **单 GPU 12G 显存**(`impl-plan:126-128`):large-v3 + CosyVoice 已近上限。若取决策点 A② 把 STT+TTS 塞一进程,需真机量显存;取 A①(双进程)则维持现状显存占用。

**真机验收门(翻 flag 后必过):**
- G1. 喊「贾维斯」→ 说一句 → HUD 经 fetch `/transcribe` 拿到转写(对比旧 WS 路径转写质量不回退:large-v3、中文、Jarvis 名字归一化都在)。
- G2. agent 回话 → HUD `/synthesize` 拿到音频并播放(CosyVoice 音色一致;WAV 直播无兼容问题——验证决策点 B)。
- G3. 连续多轮:CosyVoice `_infer_lock` 串行无 token2wav 崩溃(对应 cosyvoice_server.py:93-98 的已知事故);单字回复(如「嗯」)毒化补偿生效不崩。
- G4. 静音 / 自身回声 → `/transcribe` 回空串,HUD 正确判「没听清」(幻觉过滤 + 回声过滤 `main.ts:222-228` 仍生效)。
- G5. (若部署在 LAN)非 loopback 绑定无 token → 服务 fail-closed 拒启 / 请求 401;带 token 正常;CORS preflight 通过(Tauri origin)。

---

## 10. 风险

- **R1(显存)**:见决策点 A,默认双进程规避;真机若中心 GPU 同时跑 large-v3+CosyVoice 需量显存。
- **R2(rpc.ts 双改冲突)**:见 §6,靠「新逻辑全进 voice_http.ts + rpc.ts 最小双路桩」化解;实现者须确认阶段 3 落地顺序。
- **R3(CORS/preflight)**:Tauri origin `tauri://localhost` multipart POST 触发 preflight,OPTIONS 漏放行会静默失败;测试 15 守这条。
- **R4(WAV 播放兼容)**:决策点 B 去 mp3 transcode,真机 G2 验证;退路是加回 ffmpeg transcode(可逆)。
- **R5(脱 hermes 不彻底)**:`voice_svc_stt.py` 若漏搬某个 hermes 间接依赖(如 lazy_deps 安装路径),启动即炸;靠步骤1 的 grep 断言 + 在干净 env 启动验证。
- **R6(STT 默认模型)**:hermes 默认 `base`,本服务真机要 `large-v3`;`STT_MODEL` 默认值搬错会静默降质——测试无法发现(质量回退),靠 G1 真机对比。



---

## 元数据(workflow 抽取)

**改动文件**:
- hud-app/voice_svc.py
- hud-app/voice_svc_stt.py
- hud-app/start_voice_svc.sh
- tests/test_voice_svc_stt.py
- tests/test_voice_svc_http.py
- hud-app/hud/src/voice/voice_http.ts
- hud-app/hud/src/voice/voice_http.test.ts
- hud-app/hud/src/voice/rpc.ts
- hud-app/hud/src/main.ts
- hud-app/cosyvoice_server.py

**依赖/冲突**:
- 与阶段3同改 hud-app/hud/src/voice/rpc.ts:阶段3改 submitPrompt/message.complete 事件区(rpc.ts:42-46,87-103,132-141),阶段5改 transcribe/synthesize(rpc.ts:123-130,143-150)。同文件不相交方法,但有 merge 冲突面。排序:阶段5 在阶段3 合并后再动 rpc.ts;若并行,新逻辑全进 voice_http.ts,rpc.ts 只留最小双路桩(2方法约6行),并在PR标注待阶段3后rebase。
- 鉴权复用阶段1(已落,dev_server.py:68-99)的 JARVIS_GATEWAY_TOKEN/HOST/_authorized/_enforce_fail_closed —— 拷贝而非 import(voice_svc 须 zero-import dev_server/hermes)。
- TTS 默认转发依赖现成独立的 cosyvoice_server.py(:8003,已零依赖),不改它的 _infer_lock(cosyvoice_server.py:97)/毒化补偿(:108-114)。
- Python 测试须用项目 .venv:uv run --no-sync python -m pytest(anaconda base 撞 starlette 版本,impl-plan:22 已记)。
- 收缩步骤(删WS语音路径:voice_bytes.py/gateway_voice_patch.py/server.py:8959,8989/rpc.ts旧分支)留到本阶段真机验收后的独立commit,不在本规格执行范围。

**真机验收门**:
- 前置:查清 voice 服务真实启动环境(HERMES_HOME、faster-whisper 模型缓存位置、CUDA 运行时 libcublas/libcudnn 是否齐),确认 voice_svc 能否真正脱 hermes 启动(impl-plan:122-123)
- 前置:查清中心 GPU 10.8.0.2 真实部署形态——STT/TTS 跑中心还是本机、HUD 直连目标地址(loopback/LAN/WireGuard),决定鉴权是否真被触发(impl-plan:124)
- 前置:单 GPU 12G 显存量测——large-v3 + CosyVoice 近上限;决策点A取双进程则维持现状,取单进程需实测(impl-plan:126-128)
- G1:喊贾维斯说话→fetch /transcribe 转写质量不回退(large-v3/中文/Jarvis名字归一化都在),对比旧WS路径
- G2:agent回话→/synthesize 拿音频并播放,CosyVoice音色一致,验证决策点B(HUD直播WAV无兼容问题)
- G3:连续多轮 _infer_lock 串行无 token2wav 崩溃;单字回复毒化补偿生效不崩(cosyvoice_server.py:93-114)
- G4:静音/自身回声→/transcribe 回空串,HUD 正确判没听清(幻觉过滤+回声过滤 main.ts:222-228 仍生效)
- G5:LAN部署时非loopback无token fail-closed拒启/401,带token正常,CORS preflight(Tauri origin tauri://localhost)通过

**风险**:
- 显存:large-v3+CosyVoice 单12G GPU 近上限;默认取双进程(voice_svc转发到独立cosyvoice_server:8003)规避,单进程方案需真机量显存
- rpc.ts 与阶段3 双改同文件:虽方法不相交但有merge冲突面;靠新逻辑全进 voice_http.ts + rpc.ts 最小双路桩化解,须确认阶段3落地顺序
- CORS preflight:Tauri origin tauri://localhost 的 multipart POST 触发 preflight,OPTIONS 漏放行会静默失败(测试15守)
- 去mp3-transcode直回WAV:浏览器对audio/wav兼容性需真机G2验证;退路加回ffmpeg transcode(可逆)
- 脱hermes不彻底:voice_svc_stt.py 漏搬某个hermes间接依赖(如lazy_deps)启动即炸;靠步骤1 grep断言+干净env启动验证
- STT默认模型回退:hermes默认base、本服务需large-v3,STT_MODEL默认值搬错会静默降质,代码测不出,靠G1真机对比
- 工作区有未提交diff(whisper_api.py名字归一化、transcription_tools.py initial_prompt):搬迁须以工作区现状为准,把这两处增量也搬进voice_svc_stt.py


---

## workflow 对抗 critic(待 Codex 复核合并)

**verdict**: 不能直接执行,需先补三处 blocker/high。核心骨架是对的(expand-contract + flag 默认false 零风险回退、新逻辑隔离进 voice_http.ts/voice_svc_stt.py、双进程转发保留 cosyvoice 事故约束、TDD red-first),Simplicity 把控不错(明确 YAGNI 不做 baidu/不重构6-provider/双进程不抢GPU),真机门和前置 unknown 识别到位。但有四个会让实现者直接翻车的硬伤:(1)BLOCKER——拷贝 dev_server 鉴权 middleware 会失效,因为它只守 /api/ 前缀而 voice_svc 用裸路径,鉴权会静默全放行、测试13假绿;(2)HIGH——『main.ts 理想零改动』与现有 base64 链路(finishRecordingToText 先 blobToBase64、speak 用 base64ToBytes 取 .audio)直接冲突,去-base64 收益和零改动不可兼得,spec 自相矛盾必须挑明;(3)HIGH——脱hermes 仅靠顶层 grep 不够,工作区新增的 _load_stt_config().initial_prompt 必须改写为 env 否则拖回 hermes,需补『干净 env 真 import』硬门;(4)HIGH——voiceSvcBase 派生公式把『语音服务与网关同址』当已知,但前置 unknown 2(中心GPU部署形态)未定前不成立,应以显式注入为主、wsUrl 派生为 fallback。外加 grounding 错误:§5.D/§3 说的 whisper_api.py:49-62 _MIME_TO_SUFFIX 不存在(那里是 splitext(filename),mime 映射在 voice_bytes.py),实现者照 spec 找会扑空。修掉这 4+1 项后可执行;其余为 medium/low 收尾项。

- **[blocker]** 鉴权 middleware 拷贝即失效:阶段1 dev_server 的 _auth_mw 只守 `request.url.path.startswith("/api/")`(已在 dev_server.py:104 验证)。voice_svc 的契约端点是裸 `/transcribe` `/synthesize` `/health`,前缀不是 /api/。若实现者『拷贝阶段1鉴权助手』连 middleware 一起照搬,所有语音端点将无鉴权放行——成功标准5(非loopback fail-closed)和测试13直接假绿。这是 blocker:spec 反复强调『拷贝 dev_server 思路』但没指出 path 前缀必须改写,会被原样抄。
  - fix: 在 §4 鉴权小节明确:拷贝的是 _auth_required/_token_ok/_authorized/_enforce_fail_closed 四个纯函数(它们与 path 无关),middleware 必须重写为守 voice_svc 自己的端点(或给端点统一加 /v1 前缀再守前缀,或在每个 handler 里调 _authorized)。测试13/15 必须断言裸路径 /transcribe 被守、/health 是否要守需明确(健康检查通常豁免——spec 没说 health 要不要鉴权,需定)。
- **[high]** main.ts『理想零改动』是错的——与现有 base64 链路硬冲突。已验证 finishRecordingToText(main.ts:213-216)先 `blobToBase64(blob)` 再 `rpc.transcribe(b64, mime)`,且 speak(main.ts:243-245)做 `base64ToBytes(syn.audio)` 取 JSON 的 .audio 字段。spec §3 的卖点是 multipart 传 Blob(不再 base64)、/synthesize 回原始 arrayBuffer(不再 base64 JSON)。要兑现这两个收益,rpc.transcribe 的签名必须从 (b64:string) 变成收 Blob、synthesize 返回从 {audio,mime} 变成 ArrayBuffer——main.ts 的两个调用点都得改。spec 自己说『main.ts:216,243 不改语义、理想零改动』自相矛盾。
  - fix: 二选一并写进 spec:(a)voice_http.ts 内部把 Blob 直接 FormData 上传、把 arrayBuffer 包成 main.ts 期望的旧形状返回(rpc 接口不变、main.ts 真零改),代价是 transcribe 仍要 main.ts 先 blobToBase64 再被 voice_http 解回 Blob——啰嗦但隔离;(b)改 main.ts 两个调用点直接传 Blob/收 bytes,兑现 spec 的去-base64 收益但 main.ts 非零改。spec 必须挑明,别留『理想零改动』这种会被实现者当真的话。
- **[medium]** grounding 错误:§5.D 与契约都说『沿用 whisper_api.py:49-62 的 _MIME_TO_SUFFIX』,但 whisper_api.py 根本没有 _MIME_TO_SUFFIX——它用 `os.path.splitext(file.filename)[1]` 取后缀(已验证 whisper_api.py:49-50)。_MIME_TO_SUFFIX 只在 tui_gateway/voice_bytes.py:23。契约 §3 说『mime 由 Content-Type/filename 后缀推断,沿用 _MIME_TO_SUFFIX』把两套不兼容的取后缀策略混为一谈。
  - fix: 明确选一种:浏览器 FormData 上传带 filename,直接学 whisper_api 用 splitext(filename) 最简单(zero 依赖、已验证可用),不必搬 voice_bytes 的 mime 映射表。把 §5.D/§3 里『沿用 whisper_api.py:49-62 _MIME_TO_SUFFIX』改成『沿用 whisper_api.py:49-62 的 splitext(filename) 后缀推断』。
- **[medium]** 测试3 的断言与实际 regex 不符,red-first 会写错。spec 测试3 要 `_normalize_names("夏威士在吗")→"贾维斯在吗"`,而工作区实际 regex(whisper_api.py:30)是 `(?i)jarvis|夏威士|加维斯|甲微事|贾伟斯|佳维斯|家维斯|加伟斯`——它含『夏威士』『佳维斯』但 spec §5.C 的注释举例『把佳维斯变成贾维斯后绕过过滤』,而测试3只列了『夏威士』『Jarvis』,漏验『佳维斯/加维斯』等其余别名。更要紧:spec §7 测试1 说 is_whisper_hallucination 做中文过滤,但已验证 voice_mode 的过滤是『集合精确匹配+repeat regex』,不是泛中文过滤;『谢谢观看』必须确实在 WHISPER_HALLUCINATIONS 集合里才 True——需核对集合内容,否则测试1 假设落空。
  - fix: 测试用例直接以工作区 whisper_api.py:30 的真实别名集合为准逐个断言;测试1 落地前先 grep WHISPER_HALLUCINATIONS 集合确认『谢谢观看』在内(在 voice_mode.py:824-873)。把 spec 措辞『中文过滤』改成准确的『已知幻觉短语集合匹配』,避免实现者误以为要写语言检测。
- **[medium]** 决策点A①(双进程转发到 cosyvoice_server:8003)把成功标准3(_infer_lock+毒化补偿保留)说成『自动满足』,但 voice_svc 若做参数校验会重复/冲突。已验证 cosyvoice_server.py:101-115:空文本/0可发音字符回 400、单字符 text+text 毒化补偿都在 /tts 内部。spec §4 说 voice_svc 的 /synthesize『做参数校验』,契约 §3 又要 voice_svc 对空文本回 400 『text required』。若 voice_svc 也判空,与下游 400 语义重叠尚可;但毒化补偿(单字 text+text)绝不能在 voice_svc 重复做(会变 text*4),spec 没写明『毒化补偿只在下游、voice_svc 不得复制』。
  - fix: §4 明确:取①时 voice_svc /synthesize 只校验 text 非空(回 400)+ 转发 + 错误翻译,严禁复制单字毒化补偿/可发音字符计数(那是下游唯一职责)。否则两层都加倍单字会双倍毒化补偿。
- **[high]** 『脱 hermes』grep 断言不充分,faster-whisper 间接依赖未排查。R5 提到 lazy_deps,但 spec 没要求实际在干净环境跑一次 import 验证,只 grep 顶层 `import (tools|tui_gateway|hermes)`。_transcribe_local/_load_local_whisper_model(transcription_tools.py:1064-1186)很可能引用模块级常量(_CUDA_LIB_ERROR_MARKERS 等)或 logger、_load_stt_config——spec §5.A 说删 _load_stt_config 依赖改 env,但 transcription_tools 工作区 diff 刚加了 `_load_stt_config().get("local",{}).get("initial_prompt")`(已验证),搬迁时这块必须改写成 env,否则又拖回 hermes config。grep 抓不到 from x import y as 别名或函数内 import。
  - fix: 步骤1 验证补一条硬门:在剥离 hermes 的 venv/临时目录里 `python -c 'import voice_svc_stt'` 必须成功(不只是 grep)。明确列出搬迁时必须改写为 env 的每一处 _load_stt_config 调用(含工作区新增的 initial_prompt 那行)。grep 模式补 `from (tools|tui_gateway|hermes)` 和函数内 import。
- **[high]** 真机门是『前置 unknown 不解决不开工』,但 spec 同时给了完整步骤1-3 的纯加法实现且默认 flag=false 零风险。这造成矛盾指令:到底是『查清部署形态再开工』还是『先写隔离代码』?前置unknown 2(中心GPU部署形态/直连目标地址)若答案是『HUD 直连中心 GPU 的 LAN 地址』,则 voiceSvcBase 派生逻辑(spec 只说『类似 wsUrl 派生』)和 CORS allow_origins 都依赖该答案,但 spec 把这块当已知在写。voice_http.test.ts 测试16 假设 base 由 wsUrl 派生 http——若语音服务部署地址≠网关地址(不同 host/port),派生公式根本不成立。
  - fix: 明确分层:步骤1-3(纯加法隔离代码 + 单测)不阻塞、可先做;前置 unknown 只阻塞步骤4(翻 flag 真机)。但 voiceSvcBase 的派生必须把『语音服务可能与网关不同址』作为一等情况:优先 window.__JARVIS_VOICE_URL__ 显式注入(spec 测试16 已有此项),派生 wsUrl 只作 fallback 且仅当确认同址。在前置 unknown 2 答案落定前,不要把派生公式冻进契约。
- **[low]** CORS:credentials 与 allow_origins 通配的组合陷阱未提。spec 说 allow_origins 含 `http://localhost:*`——CORSMiddleware 的 allow_origins 不支持端口通配 glob(只能精确列表或 `*` 或正则 allow_origin_regex)。token 经 ?token= 查询参不走 cookie,所以不需要 allow_credentials,但实现者若顺手开 allow_credentials=True 又用 `*` 会被浏览器拒。
  - fix: §4 明确用 allow_origin_regex 匹配 `tauri://localhost` 与 `http://localhost(:\d+)?`(端口通配必须用 regex,不能写 localhost:*);allow_credentials 保持 False(token 走 query 非 cookie)。
- **[low]** 步骤排序与 deps 自相矛盾且把决策权甩给实现者。§6 推荐『阶段5在阶段3合并后再动 rpc.ts』,但又给『若并行』方案;同时 §6 末句要求实现者自己 `git log rpc.ts` 判断阶段3是否落地。spec 评审本应裁决顺序,而非把『确认阶段3落地顺序』作为 R2 风险留给实现者。当前分支是 feat/voice-hud-agent-orchestration,无法从 spec 判断阶段3 状态。
  - fix: 评审建议:既然 §6 已把新逻辑全隔离进 voice_http.ts、rpc.ts 仅 2 方法约6行双路桩,merge 冲突面已极小,直接按『并行安全』路线走,删掉『等阶段3合并再动』的犹豫表述,省得实现者纠结。一句话定调即可。
- **[low]** /synthesize 错误降级语义不闭环。测试18 要 resp.ok=false→返回 null(对齐旧 rpc synthesize 错误回 null)。但下游 cosyvoice_server 对空/0可发音字符回 400 空 body(已验证 cosyvoice_server.py:103),voice_svc 转发时把下游 400 翻成什么?契约 §3 voice_svc 自己空文本回 400『text required』,但下游因『全标点』回的 400 没有该文案。前端 synthesizeHttp 对 400 该当成 null 降级(不播音)还是报错?未定。
  - fix: §4 明确转发错误翻译表:下游 4xx/5xx → voice_svc 5xx{error} 或透传;前端 synthesizeHttp 对任何非 200 一律返回 null 静默降级(对齐 speak() 现有『syn 为 null 就不播』,main.ts:244)。

---

## Codex 复核(已接受,2026-06-13)

**BLOCKER — 鉴权未覆盖新服务**:Phase 1 middleware 只守 `/api/*`(`dev_server.py` 我亲手写的 `startswith("/api/")`)。独立服务的裸 `/transcribe`/`/synthesize` **不在 `/api/` 下**,直接复用会漏。新服务必须自带鉴权门(复用 token 机制但守自己的路由)。

**接受的修正**:
- **base64 契约**(MAJOR):`main.ts:214-216` 录音 `blobToBase64` 后送 STT,`main.ts:243-245` TTS 期望 base64 `{audio}`。改 fetch 时必须定清 adapter 形状(multipart vs base64),不是"main.ts 零改动"。
- **STT 脱 hermes 验证**(MAJOR):不能只 grep;`transcription_tools.py:1132/1153` 读 hermes config。必须做**真正 hermes-free 的 import/run** 验证。
- **`_MIME_TO_SUFFIX` 引用错**(MAJOR):它在 `tui_gateway/voice_bytes.py:21-30`,不在 `whisper_api`(后者用 `os.path.splitext`,`whisper_api.py:49-52`);修正引用与策略。
- 新服务需**自带 CORS/preflight**(Phase 1 只给 `/api/music` 配了 CORS)。
- `/synthesize` 错误映射:CosyVoice 对空/不可读文本返回 400(`cosyvoice_server.py:101-112`),需定转发/映射;`_infer_lock` 串行 + 短文本补偿由 `voice_svc` 转发、勿重复加。
- 中心 GPU 形态:改"未文档化"为"**核对过时文档**"(`decisions/0005` 已部分记载)。
- OK(已确认):Phase3/5 在 `rpc.ts` 改的是**不相交方法**——把 Phase5 逻辑挪到新 `voice_http.ts`、`rpc.ts` 只留薄 wrapper 即可,排序成立;baidu interface-only 范围清晰;真机 unknown(`whisper_api` 启动环境/`HERMES_HOME`)正确列为前置。
