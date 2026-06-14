---
title: HANDOFF 2026-06-14 — agent 解耦 phase0-4 落地 + STT(turbo/百度)整治
date: 2026-06-14
supersedes: HANDOFF-2026-06-13-agent-orchestration.md
branch: feat/voice-hud-agent-orchestration
---

# HANDOFF 2026-06-14 — agent 解耦(phase 0–4)+ STT 提速/抗噪

## ① 一句话现状
**贾维斯 agent 解耦(决策 0007:agent=文本进 `{text,end}` 出黑盒)phase 0–4 全部实现+提交+真机验过;STT 换 whisper large-v3-turbo(快、抗噪,真机"哇塞");百度 STT 作可选 backend。** 全在分支 `feat/voice-hud-agent-orchestration`,**未 push**。下一步=用户约定的「STT 独立化(脱 hermes,像 cosyvoice)」后续整改。

## ② git + 持久状态
- 分支 `feat/voice-hud-agent-orchestration`,HEAD `0af5125`。**无 git remote → 全未 push**。
  - 叠在 `6f1c8ac` 之上:`716fc87` docs、**`01011ce` p5-step1 STT 引擎**、docs、**`05160a8` p5-step2 voice_svc 服务**、docs、**`21e6531` p5-step3 HUD fetch 直连**、docs、**`0af5125` p5 Tauri 壳注入开关(真机验过)**。
- 关键 commit:`08f7e72`(决策0007+计划+规格)`3a1b4cc`(p0)`64f6c6b`(p1鉴权)`a3f4f97`(p2 sanitizer)`b5b1c96`+`21f4eff`(p3 expand+contract)`b3f77ec`(webview音乐退役)`766549c`(p4静默超时)`67e7444`(百度STT backend)`ac177e2`(百度噪声过滤)`d7e0f88`(回声过滤修)`6f1c8ac`(docs)。
- **3 个 pre-existing 改动全程没碰**(非本人):`hud-app/kws_listener.py`、`hud-app/whisper_api.py`、`tools/transcription_tools.py`。
- **部署态(不在 git,机器重启需重做)**:中心 `~/.hermes-stt/config.yaml` `model:`→ 本地 turbo 路径;turbo 模型在 `~/.cache/whisper-models/faster-whisper-large-v3-turbo`(魔搭下);`.venv` 装了 `modelscope`;0.3 `~/.jarvis-secrets`(百度密钥,600,`STT_BACKEND=baidu` 已注释=用 whisper);whisper_api 手动起的(见⑥)。
- **🆕 phase5 部署态(重启需重做,token 不在 git)**:**中心 voice_svc 跑 8011**——`HOST=0.0.0.0 PORT=8011 JARVIS_GATEWAY_TOKEN=<tok> setsid nohup bash hud-app/start_voice_svc.sh >/tmp/voice_svc.log 2>&1 &`(token 见 `/tmp/voice_svc_token.txt`,杀按端口 `fuser -k -9 8011/tcp`)。0.3 `~/.jarvis-secrets` 末尾有 `JARVIS_USE_HTTP_VOICE=1`/`JARVIS_VOICE_URL=http://10.8.0.2:8011`/`JARVIS_TOKEN=<tok>`(同一 token)。**HUD 现在喊话走中心 voice_svc,不再经网关 WS STT。** whisper_api:8010 仍在跑(Windows hermes 用,且是回退兜底)。

## ③ 本 session 成果(带证据)
- **agent 解耦 phase 0–4 完成**:契约边界 = 文本进 `{text,end}` 出;`end_session` 由"广播事件"改成 message.complete 的 `payload.end`(机制=复用 hermes `tools.approval` session-key contextvar);前端 `runSession` 只认 `reply.end` 退场 + 静默超时(`IDLE_TIMEOUT_MS=30s`)退场;入站鉴权门(非 loopback 强制 token);TTS sanitizer(复用 `hermes_cli/voice.py` 抽 `tools/tts_sanitize.py`)。**每阶段 Codex 审过 + 复核**;后端 67 passed、前端 vitest 21、tsc/build 0;**phase3/4 真机 0.3 验过**(退下即退/静默退/不误退)。
- **放歌归 agent skill**:退役 webview 内播(`audio.playMusic`/`/api/music`/`MUSIC_UPSTREAM` 删,`b3f77ec`);真实放歌=play-music skill→`gequbao_play.py`。决策 0006 标 superseded。
- **STT 提速**:`large-v3`→`large-v3-turbo`(魔搭下、中心 config 指本地路径),真机明显快、抗噪保留。
- **STT 百度 backend**(`tools/baidu_stt.py` + `transcribe_bytes` 的 `STT_BACKEND` 选择器,`67e7444`):云 ASR、绕开 GPU,可一键回退。
- **两个真机 bug 修复**:百度答后误识别"嗩。"(加语气词噪声过滤 `ac177e2`);whisper 回声过滤误杀真命令(收紧成"≥85% 整句一致才判回声" `d7e0f88`)。

## ④ backlog(ROI 排序)+ 已关闭决策(负面清单)
**下一步(按 ROI):**
1. **STT 独立化**(用户约定的后续整改,详见 `impl-plan-agent-decoupling.md` phase 5 + `specs/phase5-voice-service.md`):重写成零 hermes 依赖的自包含 STT 服务(直接 faster-whisper turbo),**完整搬过质量门**(VAD、`is_whisper_hallucination`+中文幻觉名单、`_JARVIS_ALIASES`;语气词过滤是 baidu_stt 专属、whisper 路径靠 VAD),保留契约,`STT_BACKEND` 选择器收进服务。**expand-contract,flag 默认 false 零风险回退。**
   - **✅ step1(`01011ce`)**:`hud-app/voice_svc_stt.py`(引擎,A/B/C/D 全搬,配置改 env STT_MODEL/STT_LANGUAGE/STT_INITIAL_PROMPT)+ `tests/test_voice_svc_stt.py`。验:pytest 6 passed;grep 无 hermes import;import 零拉入 hermes 模块;faster_whisper 懒加载。
   - **✅ step2(`05160a8`)**:`hud-app/voice_svc.py`(HTTP `/health`/`/transcribe`/`/synthesize` + 鉴权守裸路径 + CORS regex + TTS 转发 cosyvoice:8003 直回 WAV 不重复毒化补偿)+ `tests/test_voice_svc_http.py`(11 passed)+ `start_voice_svc.sh`(STT_MODEL 显式指 turbo 路径)。验:全量 86 passed;voice_svc grep 无 hermes + import 零拉入。**端口选 8011**(避开 whisper_api 8010)。
   - **✅ step3(`21e6531`)**:前端 `voice_http.ts`(+11 测)+ `rpc.ts` 双路桩。flag 默认 false=旧 WS 路径零变化。验:vitest 32 passed、tsc 干净、vite build 正常。phase3 已先落 rpc.ts(`b5b1c96`),双改冲突不存在。
   - **✅ step4 真机翻 flag 通过(`0af5125`,2026-06-14 喊话验)**:
     - **前置 unknown 已解**:GPU 在中心(10.8.0.2),0.3 无 GPU;今天 HUD STT 实际路径=HUD(0.3)→WS→网关(0.3 loopback)→voice_bytes→`provider:openai 10.8.0.2:8010/v1`→中心 whisper_api → 即 STT 早就在中心跑。**所以 voice_svc 部署中心** 10.8.0.2:8011(用 GPU+loopback 转发 cosyvoice:8003),HUD 跨 WG 连 → 非 loopback → 需 token。
     - **部署**:中心起 `HOST=0.0.0.0 PORT=8011 JARVIS_GATEWAY_TOKEN=<tok> bash hud-app/start_voice_svc.sh`;`main.rs` INIT_SCRIPT 改读 env 三全局;0.3 `~/.jarvis-secrets` 加 `JARVIS_USE_HTTP_VOICE=1`/`JARVIS_VOICE_URL=http://10.8.0.2:8011`/`JARVIS_TOKEN=<tok>`;rsync 全量 hud/src+main.rs;`start_jarvis.sh` 重启(tauri 重编拾取)。
     - **证据**:G1 转写「你好,我是贾维斯。」名字归一化在、G2 WAV webview 直播 OK、G3 连续多轮无崩、G4 静音判没听清、G5 鉴权 401/200。判别器:旧路 whisper_api:8010 `[stt]` 计数全程停 40=确实走新路。GPU 双 whisper+cosyvoice 共存 9.3/12G 不 OOM。
     - **⚠️ flag 代码默认仍 false**(`voice_http.ts`);0.3 靠 secrets 注入启用。**别把代码默认改 true**——未注入 `__JARVIS_VOICE_URL__` 的 HUD 会把 voiceSvcBase 派生成网关地址(错)。改默认留到 step5 删 WS 路径时。**回退**:注释 0.3 secrets 三行 + 重启 HUD。
   - **🔜 step5 contract**(可选,真机稳定一阵后独立 commit):删 WS 语音路径(`voice_bytes.py` 两函数、`gateway_voice_patch.py` 两注册、`server.py:8959/8989`、`rpc.ts` 旧分支 + flag 包装),顺带清 main.ts base64 往返,再把 flag 默认改 true。**本次未做,旧路径完整保留可回退。**
2. 给中心 whisper_api 写一键启动脚本(现在手动,见⑥)。
3. push 分支 / 决定 3 个 pre-existing 文件去留 / `ws_tool_smoke.py`(失效 dev 脚本)删否。
4. phase 6(抢话打断/流式/进度/agent 主动说话)——需先解 AEC double-talk。

**已关闭决策(别重开):**
- ❌ **in-process agent 大脑**(monkeypatch 工具+WakeHub 广播)→ 0007 取代,不可换 agent。别走回。
- ❌ **webview 内播音乐**(0006)→ 退役;放歌=agent skill(gequbao)。别复活 `/api/music`/`audio.playMusic`。
- ❌ **百度做默认 STT** → 噪声/放歌乱识别(百度啥都转成字,无 VAD)。whisper turbo 是默认;百度仅可选 backend。
- ❌ **STT 留 large-v3** → 慢。用 turbo。
- ❌ **HF 直连下模型** → 国内 LFS 卡在 0。用魔搭(`pengzhendong/faster-whisper-large-v3-turbo`)/本地路径。
- ❌ **MCP/OpenClaw 当 agent 换 brain**(调研结论:架构倒置,wf_06743372 报告)→ 暂缓。
- ❌ **能力清单由②发布③透传的"运行期倒置注入"** → 过重;只做"边界=`{text,end}`"。

## ⑤ 重启 verify(先跑这些核对现实,别信文档)
```bash
# A. 代码状态(中心/开发机 10.8.0.2,repo=~/hermes-agent)
cd ~/hermes-agent && git log --oneline -1        # 期望 6f1c8ac;不符=分支/checkout 不对
git status --short                                # 期望仅 3 个 pre-existing(kws_listener/whisper_api/transcription_tools)
# B. 测试绿(必须用项目 .venv,别用 anaconda base!)
uv run --no-sync python -m pytest tests/test_voice_hud_*.py tests/test_baidu_stt.py tests/test_tts_sanitize.py tests/tui_gateway/test_voice_bytes.py tests/test_wake_hub.py -q   # 期望 all passed;报 FastAPI Router on_startup 错=用错了 anaconda
cd hud-app/hud && node_modules/.bin/vitest run   # 期望 21 passed
# C. 中心 STT 活着 + 是 turbo
grep model ~/.hermes-stt/config.yaml             # 期望 = .../faster-whisper-large-v3-turbo;若是 large-v3=turbo 没生效
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8010/v1/audio/transcriptions -F file=@/tmp/warm.wav  # 期望 200;连不上=whisper_api 没起(见⑥重启命令)
# C2. phase5:中心 voice_svc 8011 活(HUD 喊话现在走它;没起=HUD 转写全失败"没听清")
curl -s http://127.0.0.1:8011/health   # 期望 {"ok":true,...tts_ready:true};连不上=重起(见②phase5 部署态)
# D. 0.3 家里栈(HUD/麦/KWS 在那台,WG 10.8.0.3)
ssh baizh@10.8.0.3 'curl -sf http://127.0.0.1:8765/ && echo GW_UP; pgrep -f kws_listener>/dev/null && echo KWS_UP'  # 都 UP 才能喊话
ssh baizh@10.8.0.3 'curl -s -X POST http://127.0.0.1:8765/api/wake'  # clients:1=HUD 已连;clients:0=HUD 没连(多半前端 build 失败,见⑥同步坑)
```

## ⑥ 环境约束与 gotcha(不知道就咬人)
- **拓扑**:中心=10.8.0.2(本机/开发,GPU,跑 whisper_api STT 8010 + cosyvoice TTS 8003);家里=0.3(WG 10.8.0.3,跑 HUD+网关 8765+KWS,有麦/桌面)。**喊话验收只能在 0.3**。0.3 是**非 git 副本**,靠 `rsync` 同步(无 remote)。
- **🔴 同步到 0.3 必带 `hud/src` 全量含 `*.test.ts`**:0.3 的 `tauri:dev` beforeDevCommand 跑 `tsc --noEmit && vite build`,`tsc` **会类型检查测试文件**;漏同步改过的 `session.test.ts` → tsc 报错 → build 失败 → HUD 跑旧/坏 dist → 不连 `/api/events` → **不唤醒**(踩过整轮)。
- **🔴 跑 pytest 用 `uv run --no-sync`(项目 .venv)**,别用 anaconda base(FastAPI/starlette 不兼容,报 `Router.__init__() got unexpected keyword 'on_startup'`)。
- **🔴 杀进程别 `pkill -f whisper_api`**(命令行含该串会杀脚本自己)→ **按端口**:`fuser -k -9 8010/tcp`。whisper_api 就绪检查别用 `curl -sf /`(无 `/` 路由→404→-f 误判 down)→ 用 `/v1/audio/transcriptions` 或不带 `-f`。
- **whisper_api 启动命令不在任何脚本**(重启需手动):`cd ~/hermes-agent && HERMES_HOME=/home/baizh/.hermes-stt setsid nohup .venv/bin/python hud-app/whisper_api.py > /tmp/whisper_api.log 2>&1 < /dev/null &`(turbo 走本地路径,无需 HF/网络)。
- **ssh 起 0.3 全栈(含 GUI)**:`ssh baizh@10.8.0.3 'export DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority; cd ~/hermes-agent; setsid nohup bash hud-app/start_jarvis.sh >/tmp/restart_jarvis.log 2>&1 </dev/null &'`(缺 XAUTHORITY 则 tauri 窗口连不上 :0)。
- **百度 STT 切换**:0.3 `~/.jarvis-secrets` 取消注释 `export STT_BACKEND=baidu` → 重启网关。可能需关梯子(百度国内云)。密钥已在 600 文件 + 对话历史(介意可百度控制台重置)。
- **魔搭下模型**:`.venv/bin/modelscope download --model pengzhendong/faster-whisper-large-v3-turbo --local_dir <dir>`(国内快;HF 直连卡)。
- GPU 12G 近满(turbo 更省);CosyVoice 非线程安全有 `_infer_lock` 串行;`HERMES_VOICE_TTS` 须保持 off(否则网关 auto-TTS 与 HUD 双念)。

---

## 重启开场白(粘到新会话第一条)
```
项目 ~/hermes-agent(jarvis-voice-hud)。读 docs/plantree/plans/jarvis-voice-hud/HANDOFF-2026-06-14-agent-decoupling-stt.md + roadmap.md 顶部入口。
上个 session:agent 解耦 phase0-4 落地+STT 换 turbo(真机验过),全在分支 feat/voice-hud-agent-orchestration(HEAD 6f1c8ac,未 push)。
⚠️ 中心(本机 10.8.0.2)跑 whisper_api STT;家里 0.3(WG 10.8.0.3)跑 HUD/麦,是非 git 副本靠 rsync;喊话验收只能在 0.3。
现在做:STT 独立化(脱 hermes,像 cosyvoice;搬全质量门;并存验证再切——见 impl-plan-agent-decoupling.md phase5)。
纪律不变:push 等我指令;在 main 提交先确认;改 0.3 先 rsync 全量 hud/src(含 *.test.ts);跑 pytest 用 uv run --no-sync 别用 anaconda;杀进程按端口别 pkill -f。
重启 verify:cd ~/hermes-agent && git log --oneline -1(期望 6f1c8ac)；grep model ~/.hermes-stt/config.yaml(期望 turbo)；ssh baizh@10.8.0.3 'curl -sf http://127.0.0.1:8765/ && echo GW_UP'。
```
