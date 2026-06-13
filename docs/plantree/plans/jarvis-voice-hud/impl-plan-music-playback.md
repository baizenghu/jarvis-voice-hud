# Phase 4 实施计划 —— 在线音乐播放 + HUD 跟跳

架构见 [decisions/0006](decisions/0006-music-playback-in-webview.md)。
核心:音乐走 HUD webview 内 `<audio>` → 现有 analyser → 声纹核;网关同源代理 YouTube 流。
分里程碑:M1 网关代理 → M2 前端播放+触发 → M3 声纹核音乐模式 → M4 停/抑制+真机验收。

## 拓扑
```
语音"放首晴天" → STT → LLM 选 play_music 工具 → 前端 setMusic("晴天")
   前端 <audio src="/api/music?q=晴天">  ──同源──┐
                                                 ↓
   网关 /api/music: yt-dlp 解析 bestaudio[ext=m4a] 直链 → 代理字节流
                                                 ↓
   <audio> → createMediaElementSource → 现有 analyser → 声纹核(分频段跳)
                                       └ → ctx.destination(出声)
```

## M1 —— 网关音乐代理端点 —— ✅ 完成(2026-06-12,中心 Linux 验收)
**目标**:`dev_server.py` 加 `GET /api/music?q=<词>`,yt-dlp 解析在线流并同源代理回字节。
- 实现:`_resolve_stream_url` 用 `python -m yt_dlp -f "bestaudio[ext=m4a]/bestaudio" -g "ytsearch1:<q>"`
  (走 `sys.executable`,免 PATH、Windows 一致;20s 超时)→ httpx **流式代理**(非重定向,否则跨域 analyser tainted),
  转发 `Range`、透传 content-type/range/accept-ranges。失败返 400(空 q)/502(解析失败)JSON。
- **验收门已过**:curl `-G --data-urlencode q="周杰伦 晴天"` → **206 + audio/mp4 + content-range bytes 0-262143/5152105
  + accept-ranges(Range/seek 生效)**,落地文件 `file` 认作 ISO Media MPEG-4。单测 `tests/test_music_proxy.py` 3 绿
  + `test_wake_hub` 不回归。
- 前置:`yt-dlp` 已装中心 venv(2026.06.09);**Windows 待装**(winget);**不装 mpv**。
- ⚠️ **隐患**:yt-dlp 警告"No supported JavaScript runtime"(YouTube 提取已弃用无 JS runtime 路径)——
  当前仍能解析 itag140,但日后可能要装 deno。真出问题再处理,见此备注。
- FastAPI 坑:Union 返回注解要 `response_model=None`,否则启动报 invalid response field。

## M2 —— 前端播放 + 触发 —— ✅ 完成(2026-06-12,中心 Chrome smoke 验收)
**目标**:贾维斯听到"放歌"→ 前端开始播,复用现有 audio 路径。
- `voice/audio.ts`:`playMusic(query)` 新建 `<audio id=music-player src="/api/music?q=...">`,
  经 `createMediaElementSource` 接 analyser **和** destination(与 TTS 同形,analyser 仍不接 destination)。
  各自 MediaElementSource、共用单例 analyser → 放歌时核读到的是音乐频谱。
  另加 `stopMusic`/`isMusicPlaying`/`duckForSpeech`(Layer 1 原语)。
- **触发链(决策变更,见下)**:**前端意图识别**——纯函数 `parseMusicIntent(text)` 从转写/输入解析
  播放/停止 + 歌名,`main.ts` 在 endTurn/textTurn 命中即 `playMusic`,**跳过 LLM/TTS**(音乐本身就是声音)。
  放歌指令在 wakeTurn 对话循环里**像"退下"一样 break**——否则免按住"一直在听"会一直 duck 掉音乐。
- **为何不走原计划的"LLM 工具下发"**:① 后端工具没法在 webview 出声,信号终究要回前端;
  ② LLM 何时调工具要改 SOUL prompt,而它在 `HERMES_HOME/config.yaml`(不在 repo,每台各改)。
  前端意图识别全在 repo 内、可单测、零后端改动。代价:意图不经 LLM(功能等价),且中文意图正则保守
  (要 `首/点/个` 或 `播放/点播` 或 `歌/音乐` 后缀,避免"放假/放心"误触)——LLM 驱动可去掉此限,留作可选增强。
- **验收门已过**:中心起 `dev_server`(serve dist)+ Chrome 实测:输入"放首晴天"→ `music-player` 同源
  `/api/music?q=晴天` **paused=false、currentTime 在走、duration 318s、readyState 4**,reply "好,放晴天。";
  输入"停"→ paused=true、src 移除、reply "好,停了。"。单测 `audio.test.ts` parseMusicIntent 6 例
  (含 3 个否定防误触)→ 前端 18 绿 + build/tsc/eslint 干净。

## M3 —— 声纹核音乐模式 —— ✅ 完成(2026-06-12,中心 Chrome 像素验收)
**目标**:跳动跟音乐节奏,比 TTS 动效更炸。
- `voice/audio.ts`:纯函数 `bandLevels(freq)` 把 128 频段拆**低/中/高**(0..8% / 8..35% / 35..100%)归一化;
  `getBands()` 调它。
- `hud/ring-hud.ts`:加 `getBands`/`getMusicActive` getter + 平滑 bass/mid/treble;放歌时切**品红调色板
  `MUSIC_PAL`(#f24bd6)**,核脉冲由 bass 驱动、波形抖动由 mid/treble、外环辉光由 treble 抬。
  **不改状态机**——音乐态由 `isMusicPlaying()` 门控,语音态(idle/listening/thinking/speaking)动效原样不动。
- `main.ts`:`hud.getBands/getMusicActive` 接 audio。
- **验收门已过**(Chrome 取画布像素):待机中心 = CYAN `[34,211,238]`;放歌后中心 = MAGENTA `[242,75,214]`
  (=MUSIC_PAL,证明门控+渲染);核区域亮度逐帧波动 **CV 8.5%**(证明 analyser 同源读到音乐、频段驱动跳动);
  "停"后中心回 `[35,211,239]`≈CYAN。单测 `bandLevels` 3 例 → 前端 21 绿。

## M4 —— 放歌不干扰语音识别(硬约束)+ 停 + 真机验收(未开始)
**硬约束(用户明确)**:歌声不得影响 KWS 唤醒与 STT 转写。分层防御详见
[topics/music-vs-asr-isolation.md](topics/music-vs-asr-isolation.md):
- **Layer 1(必做)**:STT 录音窗内 HUD `pause`/重压音乐,录完恢复 → STT 受害面确定性解决
  (`voice/audio.ts` 录音开始/结束钩子)。
- **Layer 2**:KWS 唤醒期 OS 级 AEC——家里 PipeWire `module-echo-cancel`(扬声器为参考),
  KWS 监听消回声虚拟源;Windows 用声卡自带 AEC。不改 KWS 引擎。
- **Layer 3 兜底**:放歌持续 duck + 网关把"放歌中"状态推给 `kws_listener` 自适应阈值;末位用点击/物理键唤醒。
- "停/别放了/退下"暂停 audio + 退音乐态;退下仍走 Phase 3 隐身。
- **验收门**:两台真机放鼓点强的歌,期间①喊"贾维斯"能醒 ②醒后转写干净 ③"停"退场。

## 范围外(v1 不做)
- Spotify(登录/Premium/SDK,见 decisions/0006);歌单/上一首下一首/音量语音控制(先单曲播放/停);
  歌词显示;本机音乐文件(需求是在线流)。
