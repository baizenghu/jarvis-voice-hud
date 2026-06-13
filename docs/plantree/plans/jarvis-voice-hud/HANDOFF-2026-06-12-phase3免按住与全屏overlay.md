---
title: HANDOFF 2026-06-12(深夜)— Phase 3 免按住真机验收 + 家里 Tauri 立起 + 全屏 overlay 形态
date: 2026-06-12
status: 家里 Linux 全链路语音免按住可用(双语唤醒/连续对话/退下隐身);代码已提交 main
supersedes: HANDOFF-2026-06-12-2c悬浮小球三里程碑.md
---

# ① 一句话现状

家里 Linux(10.8.0.3)上贾维斯已是**全屏科幻 overlay 形态 + 完全免按住**:喊"贾维斯/Jarvis"(双语 KWS)
→ HUD 现身并打招呼 → 连续多轮语音对话(回声/幻觉双重过滤)→ 说"退下"答一句后隐身。真机验收过
(用户实喊触发 3 连中 + 完整对话 + 退下)。本篇对应代码已合 main。

# ② git + 持久状态

- repo `/home/baizh/hermes-agent`,分支 **main**(本 HANDOFF 与当日代码同一提交,见 git log 当日 feat(voice-hud) 提交)。
- 家里(10.8.0.3)新增持久物:
  - `~/.cargo`(rustup stable 1.96)+ apt:libwebkit2gtk-4.1-dev/libgtk-3-dev/libayatana-appindicator3-dev/librsvg2-dev/libssl-dev/pkg-config/libxdo-dev/libportaudio2
  - `~/kws-model`(中文 wenetspeech KWS 3.3M)+ `~/kws-model-en`(英文 gigaspeech KWS 3.3M)
  - venv 增装:sherpa-onnx、sounddevice、numpy
- 中心新增:.venv 增装 sherpa-onnx/sentencepiece(调试用);whisper_api 重启载入新幻觉名单。
- 家里三进程(均 nohup,**重启不自启,见 ④M4**):
  - 网关:`HERMES_YOLO_MODE=1 HERMES_HOME=~/hermes-home HOST=127.0.0.1 PORT=8765 … dev_server.py`(YOLO=语音免审批)
  - KWS:`KWS_MODEL_DIR=~/kws-model KWS_EN_MODEL_DIR=~/kws-model-en … kws_listener.py`(日志 /tmp/kws_listener.log)
  - 小球:`cd ~/hermes-agent/hud-app/shell && DISPLAY=:0 JARVIS_OVERLAY=1 PATH=$HOME/.cargo/bin:$PATH npm run tauri:dev`

# ③ 本 session 成果(均有验证)

1. **家里 Tauri 立起**(原计划①):rustup+系统库装好后零改码编译过;透明=真 ARGB(Depth 32)、托盘注册成功。
2. **Phase 3 免按住全链路**(原计划②,真机验收:用户实喊"贾维斯"3 连中、完整对话、退下):
   - `hud-app/kws_listener.py`:sherpa-onnx **双模型**(中文拼音热词 `j iǎ w éi s ī` + 英文 BPE `▁JA R VI S`),
     检出→POST `/api/wake`;离线照妖镜(CosyVoice 合成正/负例)中心+家里双过。
   - `dev_server.py`:`/api/wake` + `/api/events` WS;busy 抑制 + 1s 冷却(防 TTS 回声唤醒);WakeHub 单测绿(tests/test_wake_hub.py)。
   - 前端 `main.ts`:唤醒→现身→**先打招呼**→连续对话循环(开口等待 5s/尾静音 1.2s/上限 15s)→"退下/再见/拜拜"隐身;
     回声双保险(轮间 800ms 沉降 + 转写与上句回复子串比对);**纯静音窗直接丢弃不送 whisper**(治幻觉之本)。
3. **WebKitGTK 两层适配**(Linux 特有,Windows 不受影响):Rust 壳显式放行麦克风权限 + enable-media-stream;
   MediaRecorder 无 webm/ogg 编码器 → Web Audio PCM 抓流自编 WAV 兜底(encodeWav 单测绿,前端 12/12)。
4. **全屏 overlay 形态**:`JARVIS_OVERLAY=1` → 铺满屏 + 鼠标穿透 + 半透明深色底 + 待机 hide/唤醒 show
   (withGlobalTauri + window allow-show/hide);不设该 env = 原 320 小球(Windows 形态不变)。
5. **STT 幻觉治理**:whisper 幻觉名单增"中文字幕/词曲:李宗盛"等署名串 + 中文标点 rstrip 兼容(内联用例过);根因是静音窗送转写,已在前端治本。
6. **rpc.ts WS 自动重连**(网关重启后语音通道自愈)。
7. 麦克风增益修复:家里内置麦 Capture 100%+30dB 噪声淹没语音 → **Capture 50% + Internal Mic Boost 2 档**(amixer,重启会丢,见 ⑥)。

# ④ 下一步 backlog(按 ROI)

1. **M4 落地家里(优先级提升)**:三进程 systemd 自启 + amixer 增益持久化(重启后增益/进程全丢,目前手工拉);
   之后再做 Windows `tauri build` .exe。
2. **免按住移植 Windows 小球**:kws_listener 跑 Windows(sounddevice 支持)+ 网关旁挂;小球形态(无 overlay env)。
3. **对话体验微调备选**(用户未提的不做):打断(说话打断 TTS)、对话窗口超时配置、唤醒灵敏度阈值调整。
4. **2b clawtouch**(等 Pico 2 到货)。

已关闭的决策(别再提议):
- 上篇 HANDOFF ④ 全部仍有效(openWakeWord 否决/GitHub Actions 否决/shell 包壳否决等)。
- **英文唤醒用拼音近似热词** 已否决——中文声学模型对英语发音全军覆没(阈值 0.08 都不中),正解是双模型并行。
- **语音内审批环节** 暂否决——家里信任环境直接 HERMES_YOLO_MODE=1,审批 UI 工程量大且无需求。
- **pkill -f 杀进程** 再次验证会自杀 ssh 会话(命令文本含目标串时连 `[k]` 转义都救不了)——
  杀端口用 `fuser -k <port>/tcp`,杀脚本用 `for p in $(pgrep -f X); do [ "$p" != "$$" ] && kill $p; done`。

# ⑤ 重启 verify

```bash
cd /home/baizh/hermes-agent && git log --oneline -2   # 预期含当日 feat(voice-hud) Phase3 提交;没有→工作没提交,先看 git status
curl -s --max-time 4 http://127.0.0.1:8010/health      # {"ok":true} 中心 whisper;失败→重启命令见上篇⑥
curl -s --max-time 4 http://127.0.0.1:8003/health      # {"ok":true,...} cosyvoice;失败→bash hud-app/start_cosyvoice.sh
SSHPASS=baizh sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null baizh@10.8.0.3 '
  curl -s --max-time 4 -X POST http://127.0.0.1:8765/api/wake;     # {"ok":true,"clients":1}=网关+小球都活;clients:0=小球没起;连不上=网关没起
  pgrep -f kws_listener >/dev/null && echo KWS_UP;                  # 没输出=监听没起(家里重启后三进程都要手工拉,命令见②)
  head -1 /tmp/kws_listener.log'                                    # 预期 "2 models";"只跑中文"=英文模型目录丢了
# 家里离线照妖镜(测试音频在中心 /tmp/kws/,家里 /tmp 重启会清):
# KWS_MODEL_DIR=~/kws-model KWS_EN_MODEL_DIR=~/kws-model-en ~/hermes-agent/.venv/bin/python ~/hermes-agent/hud-app/kws_listener.py /tmp/pos16.wav
```

# ⑥ 环境约束与 gotcha(新增;旧约束见上篇⑥,GPU 12G 红线不变)

- **家里三进程 + amixer 增益都不持久**:重启后按 ② 的命令重拉,增益重设 `amixer -c0 set Capture 50%; amixer -c0 set "Internal Mic Boost" 2`
  (设错=KWS/STT 全聋,症状是"录到很响但 whisper 转写为空"——本底噪声淹没)。
- **tauri:dev 的 beforeDevCommand 会在家里重建 hud/dist**:tar 推送必须**连 `hud/src` 一起推**,只推 dist 会被旧 src 覆盖回去。
- **WebKitGTK 限制**(Linux 桌面壳特有):麦克风权限要宿主 allow(已写进 main.rs);MediaRecorder 没有 webm/ogg(已 WAV 兜底)。
- **xwd/RustDesk 截屏看不到 ARGB 透明**(显示成黑块)——判断真透明看 `xwininfo` Depth 32,别信截图。
- **KWS 触发后对话期间唤醒被网关 busy 抑制**,无需停监听进程;前端 busy/idle 经 /api/events 上报。
- 测试音频复刻:`printf '贾维斯' > t.txt && .venv/bin/python hud-app/cosyvoice_say.py t.txt o.wav && ffmpeg -i o.wav -ar 16000 -ac 1 o16.wav`。

---

## 重启开场白(新 session 第一条消息粘这段)

```
项目 ~/hermes-agent(贾维斯语音 HUD)。读 docs/plantree/plans/jarvis-voice-hud/HANDOFF-2026-06-12-phase3免按住与全屏overlay.md + roadmap.md。
上个 session:Phase 3 免按住在家里 Linux 真机验收过(双语唤醒"贾维斯/Jarvis"+连续对话+"退下"隐身),
全屏 overlay 形态(JARVIS_OVERLAY=1),WebKitGTK 麦克风权限/WAV 兜底两层适配,回声+whisper 幻觉双重治理。已合 main。
现在做:① M4 家里 systemd 自启(三进程+amixer 增益持久化) ② 免按住移植 Windows。
纪律:GPU 12G 卡别加模型;杀端口 fuser -k、杀脚本 pgrep 排除 $$(pkill -f 会自杀 ssh);tar 推送连 hud/src 一起;
家里重启后三进程+增益手工拉(HANDOFF ②);main 提交先确认。
重启 verify 见 HANDOFF ⑤。
```
