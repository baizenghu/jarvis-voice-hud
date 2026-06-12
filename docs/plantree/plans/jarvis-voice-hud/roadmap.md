# 路线图:贾维斯语音 HUD

持久的分期状态。每个阶段实现的架构见 [design.md](design.md)。

## 已完成
- **Phase 0 —— 语音回路(echo 模式)真机验收通过**(2026-06-11)。代码:`voice_bytes` 适配 +
  `voice.transcribe`/`voice.synthesize` 两个 RPC + 浏览器 harness + dev_server,8 单测全绿,两轮
  subagent 审查通过。**真机端到端**:笔记本(WG `10.8.0.3`)经 WireGuard + https(自签证书)连中心
  `10.8.0.2:40445`,按住 echo 说中文→faster-whisper 转写→**本地 Piper** 合成→浏览器播放,**听到念回**。
  - 环境决定:TTS 从 edge-tts(连微软云,时好时坏)换成**纯本地 Piper**(`zh_CN-huayan-medium`),稳定。
  - 远程方案:WG 够到中心 + https 满足浏览器麦克风安全上下文要求(见 decision 0005)。

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
- _(无 —— Phase 0/1 + 语音链路定稿均完成并合并 main;下一步是延后的 Phase 2/3)_

> Phase 0(语音字节 RPC,见 [impl-plan-phase0.md](impl-plan-phase0.md))与 Phase 1(环形 HUD 前端,
> 见 [impl-plan-phase1.md](impl-plan-phase1.md))已完成,移入"已完成"。下面是尚未做的阶段。

## 下一步
### Phase 2 —— Tauri 外壳(`hud-shell/`)+ Windows 打包
- 无边框、透明、置顶、可拖动窗口;托盘;全局热键(开发期兜底)。
- GitHub Actions 工作流构建 Windows `.exe`。
- **验收门:** 悬浮 HUD 助手在真实 Windows 目标上运行。

### Phase 3 —— 唤醒词(喊它名字)—— 已确认
喊出助手名字唤醒是核心交互(decision 0003),非可选项。
- 引擎与名字已定(open-questions 已解决):**openWakeWord** + **"贾维斯"**(训练自定义中文热词)。
- 跑一个常驻监听器(倾向 Tauri Rust 侧),触发 IDLE→LISTENING。
- 取代开发期的热键/点击成为主触发方式。
- **验收门:** 待机时喊"贾维斯"即唤醒 HUD 并开始聆听,全程免手动。

## 延后
- 声音克隆 TTS(GPT-SoVITS / CosyVoice)—— 仅当用户想要克隆音色时再做。
- macOS/Linux 桌面打包。
- 流式 / 抢断打断。
