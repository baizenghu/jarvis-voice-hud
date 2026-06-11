# Phase 1 实施计划 —— 贾维斯环形 HUD 前端

**Goal:** 把测试用的 `voice-harness.html` 升级成真正的科幻 HUD 前端:经典环形 HUD(青/金辉光),
四个状态(idle/listening/thinking/speaking)有音频驱动动效;复用已跑通的语音回路 RPC。

**Architecture:** `hud-app/hud/` 一个 Vite + TypeScript 工程,Canvas2D 渲染环形 HUD(v1 用 Canvas2D,
发光靠 shadowBlur/径向渐变;后续要更炫再换 WebGL 粒子)。构建出静态 `dist/`,由现有 `hud-app/dev_server.py`
(https + `/api/ws`,WG 远程麦克风可用)托管。语音回路逻辑从 `voice-harness.html` 移植成 TS 模块。

**Tech Stack:** Vite 5、TypeScript、Canvas2D、Web Audio(MediaRecorder + AnalyserNode)、flat-config ESLint。

## 视觉规格(用户选定)
经典环形 HUD:多层同心**弧环各自旋转** + 中心**声纹反应核** + 外圈**刻度 tick**;青(#22d3ee 系)为主、
金(#ffce54 系)点缀;透明背景(为后续 Tauri 悬浮窗)。
- **idle**:弧环缓慢旋转、整体轻微呼吸(明暗脉动)。
- **listening**:中心核 + 外环随**麦克风** AnalyserNode 实时起伏,色调偏青、转速略升。
- **thinking**:弧环加速旋转、出现"加载"扫描感,中心核收束(等 LLM)。
- **speaking**:中心核 + 环随 **TTS 输出** AnalyserNode 脉动,色调带金。

## 文件结构(`hud-app/hud/`)
- `package.json` / `tsconfig.json` / `vite.config.ts` / `eslint.config.mjs`(flat config,规则见 [topics/frontend-lint.md](topics/frontend-lint.md))/ `.gitignore`(忽略 `node_modules`、`dist`)
- `index.html` —— 挂载点 + 全屏 canvas
- `src/main.ts` —— 入口:接线 audio→state→renderer,绑定唤醒(点击/按住,开发期)
- `src/voice/rpc.ts` —— WS JSON-RPC 客户端(连 `wss?://host/api/ws`,跟随页面协议;`session.create`/`prompt.submit`/`voice.transcribe`/`voice.synthesize`;监听 `message.complete`)
- `src/voice/audio.ts` —— 麦克风采集(MediaRecorder webm/ogg)+ 两个 AnalyserNode(录音时接 mic 流、播放时接 TTS audio),暴露 `getLevel()`/频谱给渲染器
- `src/voice/machine.ts` —— 状态机 idle→listening→transcribing→thinking→speaking→idle,事件回调驱动 HUD
- `src/hud/ring-hud.ts` —— Canvas2D 渲染器:弧环/刻度/中心核,按当前 state + audio level 动画(requestAnimationFrame)
- `src/styles.css`

## dev_server 改动(`hud-app/dev_server.py`)
- 新增挂载:把 `hud-app/hud/dist/` 作为静态站点服务于 `/`(`StaticFiles(directory=.../hud/dist, html=True)`),
  `/api/ws` 保持不变;旧 `voice-harness.html` 移到 `/harness` 作回退。dist 不存在时回退到 harness 并打印提示。

## 任务拆分
1. **脚手架**:`hud-app/hud/` 初始化 Vite+TS(`npm create`/手写),加 eslint flat config + 约定规则;`npm run build` 能产出 `dist/`。一个最小红底页验证构建+托管链路(dev_server 服务 dist,浏览器能开)。
2. **语音 TS 模块**(rpc/audio/machine):移植 harness 的回路逻辑为 typed 模块;给 machine/audio 写可单测的纯逻辑单测(状态迁移、mime 选择),Web Audio/WS 用 mock。
3. **环形 HUD 渲染器**:Canvas2D 画三层旋转弧环 + tick + 中心核 + 辉光;四状态动画;接 audio level 实时反应。人工眼测。
4. **接线 + dev_server 托管 + 真机验收**:main.ts 串起来;改 dev_server 服务 dist;构建后用户在 `https://10.8.0.2:40445/` 实测整套(说话→HUD 动效→昊然嗓回复)。

## 完成定义
- 浏览器打开是环形 HUD(非测试页);点击/按住说话,HUD 在 listening/thinking/speaking 间切换且有音频驱动动效;
  完整对话回路(STT large-v3 → MiniMax → CosyVoice 昊然)在 HUD 上跑通,WG 远程可用。
- `npm run build` 干净;eslint 通过;语音模块单测通过。

## 暂不做(留后续)
- WebGL 粒子/更高级辉光(v1 先 Canvas2D)。
- 唤醒词(Phase 3)、Tauri 悬浮窗(Phase 2)。
