# 路线图:贾维斯语音 HUD

> 🚀 **NEW SESSION 入口**:先读最新交接 [HANDOFF-2026-06-12-phase3免按住与全屏overlay.md](HANDOFF-2026-06-12-phase3免按住与全屏overlay.md)
> ——**Phase 3 免按住已在家里 Linux 真机验收**(双语唤醒"贾维斯/Jarvis"+连续对话+"退下"隐身,全屏 overlay 形态);
> 2c M1+M2+M3 此前已过(Windows 小球文字+语音);下一步 M4 自启/打包 / 免按住移植 Windows / 2b(等 Pico)。
> 红线:杀残留进程用 `fuser -k <port>/tcp` 别 `pkill -f`;Windows 远程一律绝对路径+robocopy;在 main 上提交先确认。

持久的分期状态。每个阶段实现的架构见 [design.md](design.md)。

## 已完成
- **Phase 0 —— 语音回路(echo 模式)真机验收通过**(2026-06-11)。代码:`voice_bytes` 适配 +
  `voice.transcribe`/`voice.synthesize` 两个 RPC + 浏览器 harness + dev_server,8 单测全绿,两轮
  subagent 审查通过。**真机端到端**:笔记本(WG `10.8.0.3`)经 WireGuard + https(自签证书)连中心
  `10.8.0.2:40445`,按住 echo 说中文→faster-whisper 转写→**本地 Piper** 合成→浏览器播放,**听到念回**。
  - 环境决定:TTS 从 edge-tts(连微软云,时好时坏)换成**纯本地 Piper**(`zh_CN-huayan-medium`),稳定。
  - 远程方案:WG 够到中心 + https 自签证书,满足浏览器麦克风安全上下文要求。

## 已完成(续)
- **Phase 1 —— 贾维斯环形 HUD 前端落地**(2026-06-11):`hud-app/hud/` Vite+TS 工程,Canvas2D 画
  旋转弧环 + 中心声纹核 + 四状态音频动效;语音 TS 模块(rpc/audio/machine);dev_server 托管 dist。
- **完整语音对话链路定稿(经一整天 TTS/STT/前端调稳)**(2026-06-11):
  - **STT** = faster-whisper `large-v3` + 强制 `zh`,GPU,warm ~0.6s;**加 VAD + `condition_on_previous_text=False`
    + `temperature=0` 抑制幻觉**(原会凭空吐"欢迎关注明镜");中文幻觉词加进过滤名单。
  - **LLM** = **MiniMax-M3 + 关思考**(`custom_providers[].extra_body` 透传 `thinking:{type:disabled}`;
    M2.x 关不掉只有 M3 行),warm ~2.5s;SOUL 人设收紧为"短句、禁顿号列举"。
  - **TTS** = **CosyVoice3-0.5B + 昊然参考音克隆**(从 CosyVoice2 升级——v2 小模型长句/顿号/数字会
    乱码/截断/泄漏参考文本;v3 RL 后训练治稳)。**关键**:v3 参考文本必须 `<|endofprompt|>` 格式、
    用非缓存 zero-shot 路径。启动脚本 `hud-app/start_cosyvoice.sh`。
  - **前端修复**:`analyser` 曾连扬声器致麦克风声学反馈污染"第二轮起"录音 → 改为 analyser 只取数、
    TTS 单独连 destination。
  - 备选 TTS 桥接都在(各有取舍):`gptsovits`/`f5`/`indextts`/`voxcpm`/`piper`;参考音 `hud-app/voices/haoran_ref.wav`。
  - 用照妖镜(合成→ASR 转写回比对)逐句验过稳定性。完整踩坑见笔记 `mynotebook/语音助手-贾维斯/2026-06-11-语音HUD-TTS-STT-WebAudio踩坑总结.md`。
- **代码已合并到 `main`**(2026-06-11);备份 tag `pre-hermes-upgrade` + 分支 `backup-voice-hud-phase0`。

## 进行中
- **Phase 2b**(等硬件 Pico 2 到货):clawtouch GUI 自动化。
- _Phase 0/1 + 语音链路定稿 + **Phase 2a(Windows 原生 hermes + 远程语音 + 操作本机)** 均已完成。_

> Phase 0(语音字节 RPC,见 [impl-plan-phase0.md](impl-plan-phase0.md))与 Phase 1(环形 HUD 前端,
> 见 [impl-plan-phase1.md](impl-plan-phase1.md))已完成,移入"已完成"。下面是尚未做的阶段。

## 下一步
### Phase 2 —— agent 落地 Windows + 操控本机(架构见 [decisions/0005](decisions/0005-windows-native-agent-deployment.md))
**方向变更**:不再是"Windows 只做瘦 HUD",而是**贾维斯要操作这台 Windows 的文件和界面**,所以
**hermes 原生装 Windows**(已确认支持,无需 WSL),STT/TTS 留 Linux 中心当 HTTP API,GUI 自动化用
clawtouch(Pico HID + 本地 stdio MCP)。目标机已探明:Win11 24H2、原生 Python 有、WSL 没装、局域网通。
- **2a 文件/命令档** —— ✅ **完成**:Windows 装 hermes v0.16.0 + 配模型/STT/TTS 指向中心 + NO_PROXY 直连 →
  四项端到端实测全过(LLM/TTS/STT/读写本机文件)。原生版 2026-06-11 跑通;**2026-06-12 迁到 D 盘改源码+uv 安装**
  (`D:\hermes-agent-main` + `D:\hermes-home`,C 盘清空)。详见 [impl-plan-phase2a.md](impl-plan-phase2a.md)。
- **2b GUI 档**(需硬件 Pico 2):Windows 装 `clawtouch-mcp` + 刷 `clawtouch-hid`,hermes 本地 MCP 接入,
  `clawtouch-skills` 进 skills → 贾维斯能看屏 + 点击操作 Windows。
- **2c 视觉壳**:Tauri 无边框置顶悬浮窗(原 Phase 2),本地连 Windows hermes。详见 [impl-plan-phase2c.md](impl-plan-phase2c.md)。
  - **M1 ✅ 完成(2026-06-12,真机验收 4/4)**:`hud-app/shell/` Tauri 2 壳复用 `hud/dist`(前端零改动,
    透明+拖拽由 `initialization_script` 运行期注入);Windows `D:\hermes-dev\hud-app` 本地 `tauri dev`
    出无边框/透明/置顶/可拖/托盘退的悬浮小球(本机工具链编译,无需 GitHub Actions)。
    分支 `feat/voice-hud-2c-m1`(790b89a + e5100e4)。踩坑:① time 0.3.48(当天发布)破坏 cookie 0.18.1
    → Cargo.lock pin 0.3.47;② 无边框拖动需 capability `core:window:allow-start-dragging`,缺了静默失败。
  - **M2 ✅ + M3 ✅ 完成(2026-06-12,真机验收)**:输入框文字往返 + 按住小球全语音回路
    (远程 STT/TTS 经本机网关)。关键坑:上游 hermes 缺 voice.* RPC(启动补丁注册)、
    tts_tool command 型走 cmd 不走 Git Bash(桥接改纯 cmd)。详见 [impl-plan-phase2c.md](impl-plan-phase2c.md)。
  - **M4(剩余)**:`tauri build` 出 `.exe` + 自启动 + 贾维斯图标。
- **验收门:** 在 Windows 上喊话 → 远程转写 → MiniMax → 远程合成念回;且能让贾维斯读写本机文件、操作界面。

### Phase 3 —— 唤醒词(喊它名字)—— ✅ 完成(2026-06-12,家里 Linux 真机验收)
喊出助手名字唤醒是核心交互(decision 0003)。**实现与原设想的差异**:引擎从 openWakeWord 改为
**sherpa-onnx KWS 双模型**(中文 wenetspeech 拼音热词 + 英文 gigaspeech BPE 热词,均零训练,openWakeWord 已否决);
监听器是独立 Python 进程(`hud-app/kws_listener.py`)挂网关旁,非 Tauri Rust 侧。
- 链路:KWS 检出 →POST `/api/wake` → 网关 `/api/events` WS 推送 → HUD 现身+打招呼 → 连续对话(静音端点)→
  "退下/再见/拜拜"隐身;busy 抑制+回声过滤+静音窗丢弃防自触发。
- 全屏 overlay 形态(`JARVIS_OVERLAY=1`:铺满+鼠标穿透+深色半透底+待机隐身);Windows 小球形态不受影响。
- **验收门已过:** 用户实喊"贾维斯"三连中,完整多轮对话,"退下"退场,全程免手动。
- 详见 [HANDOFF-2026-06-12-phase3免按住与全屏overlay.md](HANDOFF-2026-06-12-phase3免按住与全屏overlay.md)。
- **剩余移植项**:Windows 小球免按住(挂到 Phase 2 M4 之后)。

### Phase 4 —— 在线音乐播放 + HUD 跟跳(计划成稿,待实施;架构 [decisions/0006](decisions/0006-music-playback-in-webview.md))
语音"帮我放首歌"→ 贾维斯放在线流(YouTube,v1;Spotify 延后),**声纹核跟着歌曲跳**。两台都要。
- **关键架构**:音乐在 **HUD webview 内播**(走与 TTS 相同的 `<audio>`→analyser 路径,声纹核才跟跳);
  网关 `/api/music?q=` 用 yt-dlp 解析 `bestaudio[ext=m4a]` 并**同源代理**(跨域会让 analyser 哑跳)。否决 mpv/原生进程。
- 里程碑:**M1 网关代理 ✅** → **M2 前端播放+触发 ✅(2026-06-12,中心 Chrome smoke:放/停端到端通,同源不 tainted)** →
  **M3 声纹核音乐模式 ✅(2026-06-12,Chrome 像素验收:放歌切品红+核亮度逐帧 CV 8.5%)** → M4 停/KWS 抑制+真机验收。
  - 触发用**前端意图识别**(`parseMusicIntent`),非原计划的 LLM 工具下发(后端工具不能在 webview 出声 + SOUL prompt 不在 repo);详见 impl-plan M2。
- 详见 [impl-plan-music-playback.md](impl-plan-music-playback.md)。未决:持续音乐会否淹没/误触 KWS(真机专测)。

## 延后
- 声音克隆 TTS(GPT-SoVITS / CosyVoice)—— 仅当用户想要克隆音色时再做。
- macOS/Linux 桌面打包。
- 流式 / 抢断打断。
