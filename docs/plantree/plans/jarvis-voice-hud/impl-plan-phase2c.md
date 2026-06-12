# Phase 2c 实施计划 —— Tauri 悬浮 HUD(视觉壳 → 接本机 hermes)

架构见 [decisions/0005](decisions/0005-windows-native-agent-deployment.md) 与 [roadmap](roadmap.md) Phase 2。
分里程碑推进:M1 壳 → M2 文字往返 → M3 全语音 → M4 打包。

## 拓扑
```
Windows(192.168.0.3):
  Tauri 悬浮小球(D:\hermes-dev\hud-app\shell,复用 hud/dist 前端)
      │ ws://127.0.0.1:8765/api/ws
  hermes 网关(dev_server.py,用 D:\hermes-agent-main venv,HERMES_HOME=D:\hermes-home)
      │ MiniMax-M3(关思考)+ SOUL 贾维斯人设
      └ M3 起:voice.transcribe → 中心 :8010;voice.synthesize → 中心 :8003
```

## M1 —— ✅ 完成(2026-06-12,真机验收 4/4)
- `hud-app/shell/`:Tauri 2 壳,无边框/透明/置顶/可拖/托盘退,复用 `hud/dist`(前端零改动,
  透明+拖拽由 `main.rs` `initialization_script` 运行期注入)。
- 工作流验证:Linux 写 → tar-over-ssh 推 `D:\hermes-dev\hud-app` → Windows 本机 `npm run tauri:dev`。
- 证据:分支 `feat/voice-hud-2c-m1` commit `790b89a`(壳)+ `e5100e4`(拖动修复);用户真机确认
  透明/置顶/拖动/托盘退四条全过。Linux `cargo check` 过、hud 单测 11/11 绿。
- 踩坑(已解决,值得留档):
  - **time 0.3.48(2026-06-12 当天发布)破坏 cookie 0.18.1**(E0119 冲突,cookie 是 tauri 全平台依赖)
    → Cargo.lock pin `time 0.3.47`(`cargo update -p time --precise 0.3.47`)。
  - **无边框拖动需 capability**:`data-tauri-drag-region` 要 `core:window:allow-start-dragging` 权限,
    缺了**静默失败**(不报错、就是拖不动)→ `src-tauri/capabilities/default.json`。
  - 仓库 `.gitignore` 全局忽略 `docs/superpowers/*`,spec/plan 留本地不进 git。

## M2 —— ✅ 完成(2026-06-12,真机验收过):接本机 hermes,文字往返
**目标**:小球旁有输入框,回车 → `prompt.submit` → MiniMax 回复显示在 HUD 上;小球状态动效随
thinking/回复切换。不碰麦克风/STT/TTS。

**网关(已验证可行)**:Windows venv 已有 fastapi/uvicorn/tui_gateway(实测 import OK)→ 直接跑现成
`hud-app/dev_server.py`(只用 `/api/ws`,Tauri 自己托管前端):
```
set HERMES_HOME=D:\hermes-home
D:\hermes-agent-main\venv\Scripts\python.exe D:\hermes-dev\hud-app\dev_server.py   (HOST=127.0.0.1 PORT=8765)
```
不用 `hermes dashboard`(要 build 整个 web UI,重)。

**改动面**(M2 允许动 hud 前端,M1 的"零改动"约束解除):
1. `shell/tauri.conf.json` CSP:`connect-src` 加 `ws://127.0.0.1:* ws://localhost:*`。
2. `hud/src/voice/rpc.ts` `wsUrl()`:支持 `window.__JARVIS_WS_URL__` 覆盖(Tauri 协议下 `location.host`
   是 `tauri.localhost` 无端口,原推导失效——codex 审查已预警);shell 的 init script 注入
   `window.__JARVIS_WS_URL__='ws://127.0.0.1:8765/api/ws'`。浏览器路径行为不变。
3. `hud` 加文字输入框(overlay 区):回车发 `submitPrompt`,回复写 `#reply`;
   z-index 高于 M1 的全窗拖拽层(拖拽层 z-index 降到普通值,输入框更高)。
4. 状态机:文字轮驱动 `thinking → speaking(跳过)→ idle` 或直接 RESET——实现时按 machine.ts
   既有转移最小适配,不改状态图。

**验收门**:Windows 上小球 + 网关同跑,输入框打字回车 → 贾维斯人设回复显示、小球动效切换;
断网关时输入有错误提示不崩。

**风险**:`/api/ws` 的 `prompt.submit`/`message.complete` 在 Windows hermes 上没实测过(Phase 2a 只验了
`hermes -z`)——M2 第一步先用 wscat/python 脚本裸测网关,再动前端。

## M3 —— ✅ 完成(2026-06-12,真机验收过):全语音回路
按住小球说话 → `voice.transcribe` → prompt → `voice.synthesize` → 播放,真机全通(commit `11528dc`,M2 为 `30e90f5`)。
实现要点与踩坑:
- **上游 hermes 缺 `voice.*` RPC**(fork 才有)→ `gateway_voice_patch.py` + `voice_bytes_vendored.py`
  在 dev_server 启动时注册(fork 上 no-op),不动 D 盘上游源码。
- **重大发现:hermes `tts_tool` 的 command 型 provider 走 cmd(`shell=True`),不走 Git Bash**——
  Phase 2a 的 bash env 语法 TTS 配置从未真正通过 tts_tool 跑通(当时是手动 Git Bash 验的)。
  修复:`cosyvoice_say.py` 自带 ProxyHandler({}) 绕代理 + 第 3 参数传 API 地址,
  `D:\hermes-home\config.yaml` 的 command 改纯 cmd 语法;`HERMES_GIT_BASH_PATH` 只服务 agent shell 工具。
- 拖拽区从全窗改顶部 48px 窄条,中心区留给按住说话。
- 网关裸测脚本:`ws_smoke.py`(文字)、`ws_voice_smoke.py`(合成→转写照妖镜),先裸测再动前端。
- 中心 whisper :8010 需在跑(`HOST=0.0.0.0 PORT=8010 nohup .venv/bin/python hud-app/whisper_api.py &`)。

## M4 —— 打包(未开始)
`tauri build` 出 `.exe`(bundle.active 改回 true,target nsis/msi)+ 开机自启;贾维斯专属图标。
