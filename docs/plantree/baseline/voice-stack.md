# 基础上下文:现有语音/音频子系统

证据于 2026-06-11 通过代码审查收集。这是在贾维斯 HUD 工作开始前,hermes 已经具备的能力 ——
HUD 计划复用这些部件,而非重建。

## 当前已有
| 能力 | 位置 | 备注 |
|---|---|---|
| 音频采集 + VAD | `tools/voice_mode.py`(`create_audio_recorder`、静音回调) | 基于 `sounddevice`,运行在 **Python 主机**上 |
| STT(转写一个 WAV) | `tools/transcription_tools.py` → `transcribe_recording(wav_path)` | faster-whisper(本地默认)、OpenAI、Groq、Mistral、xAI |
| TTS(文本 → 音频文件) | `tools/tts_tool.py` → `text_to_speech_tool(text, output_path)` | Edge(默认)、ElevenLabs、OpenAI、MiniMax、Piper、Gemini、xAI、NeuTTS、KittenTTS |
| 进程级语音 API | `hermes_cli/voice.py` | 封装上述能力:推话即录 + 连续 VAD 循环 + `speak_text`;处理 TTS↔麦克风回授 |
| CLI 语音模式 | `cli.py`(`_voice_*`) | Ctrl+B 推话即录 |
| TUI 网关语音 RPC | `tui_gateway/server.py:5103-5239` | `voice.toggle`、`voice.record`、`voice.tts`;通过 WS 发 `voice.transcript` / `voice.status` 事件 |
| 实时(仅参考) | `plugins/google_meet/realtime/openai_client.py` | OpenAI Realtime API 全双工 —— 唯一的流式语音先例 |

## HUD 计划的关键约束
现有 `voice.record` / `voice.tts` RPC 是在 **Python 主机上用 sounddevice 采集和播放**音频的。
hermes 不原生支持 Windows(跑在 WSL2 里),而 WSL2 的主机音频设备穿透不可靠,用户真正的
麦克风/扬声器在 Windows 原生侧。因此 HUD **在前端**采集和播放音频(Web Audio,Windows 原生),
只通过新的字节型 RPC 复用主机侧的 STT/TTS **引擎**(`transcribe_recording`、
`text_to_speech_tool`)。见
[../plans/jarvis-voice-hud/decisions/0001-audio-capture-location.md](../plans/jarvis-voice-hud/decisions/0001-audio-capture-location.md)。

## 配置项(参考)
- `.env`:`VOICE_TOOLS_OPENAI_KEY`、`GROQ_API_KEY`、`ELEVENLABS_API_KEY`、`MISTRAL_API_KEY`、`HERMES_VOICE`、`HERMES_VOICE_TTS`
- `cli-config.yaml`:`stt.*`、`tts.*`、`voice.*`(silence_threshold、silence_duration、record_key)

## 待盘点(尚未审查 —— 需要时再补)
- `ui-tui/` 前端结构,以及它如何消费 WS RPC / `voice.*` 事件
- `tui_gateway/ws.py` 传输细节(是否支持二进制帧以传音频字节)
