# 设计:贾维斯语音 HUD

状态:**已成稿,待用户复核。** 日期:2026-06-11。

## 1. 目标与成功标准
一个 Windows 桌面悬浮助手:
1. 作为发光的贾维斯风格 HUD 常驻置顶,空闲时呼吸/待机。
2. 喊名字"贾维斯"唤醒(Phase 0/1 开发期用热键/点击兜底)。
3. 采集你的语音、转写,走**正常的 hermes agent 回合**(与 CLI/网关同一套 agent、工具、记忆 ——
   语音只是新的输入输出皮肤)。
4. 用 TTS 把回复说回来,HUD 与音频同步动效。

**成功标准:** 在 Windows 上,喊一声"贾维斯",问"今天日历上有啥",听到 hermes 用合成语音作答,
你说话时环随声起伏,它回答时环随 TTS 脉动。(日历只是任意一种 agent 能力的举例。)

## 2. 架构 —— 三层解耦

```
┌─────────────────────────────────────────────────────────┐
│  hud-shell/  (Tauri v2, Rust)   ← Windows 原生窗口       │
│   无边框 · 透明 · 置顶 · 托盘 · 热词监听                 │
│   加载 ▼                                                 │
│  hud-app/   (web: WebGL HUD + Web Audio)                 │
│   • 渲染贾维斯 HUD(idle/listen/think/speak)            │
│   • 采集麦克风(MediaRecorder)+ VAD                     │
│   • 播放 TTS 音频 + 驱动"说话"动效                       │
│   • 持有语音状态机                                       │
└───────────────┬─────────────────────────────────────────┘
                │  JSON-RPC over WebSocket(复用现有传输)
┌───────────────▼─────────────────────────────────────────┐
│  hermes  (Python, WSL2)                                  │
│   tui_gateway/server.py                                  │
│   • 新增 voice.transcribe(音频字节)→ 文本              │
│   • 新增 voice.synthesize(文本)→ 音频字节              │
│   • 现有 agent 回合 RPC(chat)—— 不改                  │
│   复用 tools/transcription_tools.py + tools/tts_tool.py  │
└─────────────────────────────────────────────────────────┘
```

三层只通过明确契约通信:
- `hud-app` **只**通过 WS RPC 契约(§4)认识 hermes,内部不含任何 hermes 代码。
- `hud-shell` 是薄壳:窗口/托盘/热词配置;它加载 `hud-app` 并把"唤醒"事件抛给它,不含语音逻辑。
- hermes 仅增加**两个**新 RPC 方法和一个极小的适配模块;agent 主循环、STT、TTS 引擎一律不动。

### 为什么音频放在前端
现有 `voice.record`/`voice.tts` RPC 用 `sounddevice` 在 Python 主机上采集/播放。但 Windows 目标
上 hermes 跑在 WSL2 里,主机音频穿透不可靠,真正的麦克风/扬声器在 Windows 原生侧 —— 正是
`hud-app` 运行的地方。所以 HUD 自己采集和播放音频,服务端只在字节上跑 STT/TTS **引擎**。
完整理由见 [decisions/0001-audio-capture-location.md](decisions/0001-audio-capture-location.md)。

## 3. 语音状态机(由 hud-app 持有)

```
        ┌──────── 喊"贾维斯" / 热键 / 点击 ───────┐
        ▼                                          │
   ┌─────────┐  检测到   ┌───────────┐  停止(VAD/ ┌────────────┐
   │  IDLE   │──语音────▶│ LISTENING │──手动)────▶│ TRANSCRIBE │
   │(呼吸)  │           │ (声纹)   │            │  (旋转)   │
   └─────────┘◀──────────┴───────────┘            └─────┬──────┘
        ▲                                                │ 文本
        │                                        ┌───────▼──────┐
        │                                        │  THINKING    │
        │   播放结束                             │ (agent 回合) │
        │                                        └───────┬──────┘
   ┌────┴─────┐   音频字节                               │ 回复文本
   │ SPEAKING │◀────── voice.synthesize ◀────────────────┘
   │ (脉动)  │
   └──────────┘
```

每个状态对应一种 HUD 动效。TTS↔麦克风回授问题(agent 听到自己的声音)在结构上规避:SPEAKING
期间关麦,只有回到 IDLE/LISTENING 才重新开麦(与 `hermes_cli/voice.py:speak_text` 里已有的守卫一致)。

## 4. RPC 契约(`tui_gateway/server.py` 新增方法)

| 方法 | 入参 | 返回 | 委托给 |
|---|---|---|---|
| `voice.transcribe` | `{ audio: <base64 或二进制帧>, mime: "audio/webm" }` | `{ text: str }` | `transcription_tools.transcribe_recording`(先把字节写临时文件,必要时解码为 WAV) |
| `voice.synthesize` | `{ text: str, voice?: str }` | `{ audio: <base64/二进制>, mime: "audio/mp3" }` | `tts_tool.text_to_speech_tool`(写临时文件后读回字节) |

实现放进一个新的薄模块(如 `tui_gateway/voice_bytes.py`,或扩展 `hermes_cli/voice.py`),让 RPC
处理函数保持声明式。复用 `is_whisper_hallucination` 丢弃空/垃圾转写。正常 agent 回合用**现有**
chat RPC —— 不新增方法;HUD 把转写文本当作普通输入消息发出,消费现有的流式回复事件。

待定:音频走 JSON 里的 base64 还是二进制 WS 帧 —— 见 open-questions。

## 5. HUD 视觉(hud-app)
- 渲染:WebGL,用小库(候选:`three.js` 或 `regl`/裸 shader)。发光同心环 + 粒子场 + 由 Web Audio
  `AnalyserNode` 驱动的音频反应声纹(LISTENING 时对麦克风做 FFT,SPEAKING 时对 TTS 输出做 FFT)。
- 四个视觉状态(§3)。配色/形象可配,默认贾维斯青金。
- 透明背景,使 Tauri 窗口只显示 HUD,叠在桌面之上。
- 决策细节:[decisions/0002-shell-and-visuals.md](decisions/0002-shell-and-visuals.md)。

## 6. 外壳(hud-shell, Tauri v2)
- 无边框、透明、置顶、可拖动、小尺寸(如 320×320)窗口;系统托盘图标用于显示/隐藏/退出;一个
  全局热键(默认可配)用于开发期把"唤醒"事件抛给 hud-app(正式交互是喊名字)。
- 产出小体积 Windows `.exe`(WebView2)。从 Linux 开发机经 **GitHub Actions** 出 Windows 包
  (本地交叉编译 Tauri 很折腾,CI 是受支持的路径)。
- Phase 1 让 hud-app 跑在普通浏览器里(无壳),先在 Linux 上跑通回路,再做 Windows 打包。

## 7. 唤醒词 —— 喊它名字(Phase 3,已确认)
唤醒方式是**喊出助手的名字**([decisions/0003-activation-wake-word.md](decisions/0003-activation-wake-word.md));
热键/点击只是热词模型就绪前的开发期兜底。一个常驻本地监听器盯着麦克风等名字,触发 IDLE→LISTENING。
名字 = **"贾维斯"**,引擎 = **openWakeWord**(用合成 TTS 语音离线训练一个中文自定义热词;本地、免费)。
待定:监听器跑在哪(Tauri Rust 侧 vs 浏览器 WASM,open-question 2)—— 倾向 Rust,这样 WebView 隐藏
也能持续监听。Phase 0–2 仍先用开发期热键跑通 HUD + 语音回路,让唤醒词落在一条已经能用的管线上。

## 8. 错误处理
| 故障 | 行为 |
|---|---|
| 麦克风权限被拒 | HUD 显示错误/锁定态;给一行提示 |
| 转写为空 / 幻觉 | 忽略,回到 IDLE(复用 `is_whisper_hallucination`) |
| WS 断开 | HUD 变暗;指数退避自动重连;不排队 |
| `voice.synthesize` 失败 | 仍在 HUD 显示回复文本;跳过音频,回到 IDLE |
| agent 回合报错 | 在 HUD 文本区显示错误;回到 IDLE |

## 9. 测试策略
- **hud-app**:用模拟 Web Audio 单测状态机迁移和 VAD 触发;视觉状态人工检查。
- **server**:用一个 fixture WAV 和一段短文本单测 `voice.transcribe` / `voice.synthesize` ——
  断言它们调用现有引擎并返回文本/字节;断言幻觉过滤丢弃已知坏转写。
- **集成**:起网关 + 在 Linux 浏览器打开 hud-app,做完整的
  说话→转写→agent→合成→播放回路(这是 Phase 0/1 的验收门)。
- **打包**:Windows 包经 CI 出;在真实 Windows 目标上人工冒烟。

## 10. 不在范围内(暂时 YAGNI)
- 全双工流式 / 抢断打断(Google Meet realtime 路径保持独立)。
- 声音克隆引擎(GPT-SoVITS / CosyVoice)—— hermes 已有 10+ 家 TTS;仅在用户明确要克隆音色时再加。
- macOS/Linux 桌面打包(Windows 优先;web 层天然可移植)。
- 全息/硬件助手、技能市场等(LumiOS 里我们不抄的范围)。
