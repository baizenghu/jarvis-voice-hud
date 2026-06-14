# 决策 0006 —— 在线音乐在 HUD webview 内播放(网关同源代理),否决 mpv/原生进程

> ⚠️ **已被取代(2026-06-14)**:webview 内播(`<audio src=/api/music>` + yt-dlp 同源代理 + analyser 跟跳)
> 太脆(WebKitGTK 编码/CSP/Cloudflare),实际改为 **gequbao 方案**——agent 的 `play-music` skill 起独立真 Chrome
> (`gequbao_play.py` CDP)放歌,光圈改读**系统声卡 FFT**(`audio_levels.py`)。决策 0007 进一步明确:**放歌是
> agent 的 skill,不是 HUD/网关的事**。webview 放歌子系统(`audio.ts` playMusic/stopMusic、`/api/music` 代理、
> `MUSIC_UPSTREAM`)已删除。本决策仅留作历史。**仍有效的部分**:音乐期 STT 隔离(duck)、`music_state` 驱动粉色态。

日期:2026-06-12。状态:**已被取代**(见上;原:已采纳)。

## 背景
新需求两条:① 语音"帮我放首歌"让贾维斯放在线流(YouTube/Spotify 等),两台都要(家里 Linux 10.8.0.3 + 公司 Windows);
② **HUD 声纹核要跟着歌曲跳动**。

关键事实(查证 `hud-app/hud/src/voice/audio.ts`):
- HUD 已有 `AnalyserNode`(`fftSize 256` → 128 频段),已在用 `getByteFrequencyData` 取频谱驱动声纹核。
- TTS 播放走 `<audio>` 元素 → `createMediaElementSource` → **接到同一个 analyser**(`audio.ts:206-212`),
  所以声纹核**现在就跟着 TTS 跳**。注释明确:analyser 是 sink,**绝不能接 destination**(麦克风也喂它,会声学反馈)。

## 决策
**音乐从 HUD webview 内部播放,走与 TTS 相同的 `<audio>` → MediaElementSource → analyser 路径。**
后端不引入 mpv;由网关(`dev_server.py`)做**同源代理**把在线流喂进 webview。

1. **播放位置 = webview 内**,不是原生进程。理由:声纹核可视化只能看到流经 webview Web Audio 的音频;
   原生进程(mpv)的声音直接进系统声卡,analyser 抓不到 → **不会跳**。要"跟跳",播放就必须在 webview。
2. **网关同源代理解决 CORS**:跨域音频喂进 `createMediaElementSource` 会被判 **tainted**,analyser 读出全 0(哑跳)。
   YouTube `googlevideo` 直链跨域 → 必须经网关 `/api/music?q=` 代理成同源,analyser 才出数。
   (TTS 现在能跳正因为它同源,来自本机网关。)
3. **音源解析用 yt-dlp**,优先 `bestaudio[ext=m4a]`(AAC)——WebKitGTK 解码 AAC 比 opus/webm 稳
   (呼应 HANDOFF:WebKitGTK 没有 webm/ogg 编码器,解码同样挑食)。
4. **"停" = 暂停 audio 元素**;播放期间 duck/抑制 KWS(复用 Phase 3 已有 busy 抑制)。

## 否决项(别再提议)
- **mpv / 原生播放器**:跨平台、省事,但声音不流经 webview → **声纹核不跳**,与需求②直接冲突。仅当放弃"跟跳"才考虑。
- **直接 `<audio src=YouTube 直链>`**:能出声,但跨域 → analyser tainted 读全 0,**哑跳**。必须经同源代理。
- **Spotify v1**:要登录 + Premium + Web Playback SDK/API,工程量大,留待 v2;v1 先做 YouTube。
- **系统音频 loopback 抓流再分析**(PulseAudio monitor / WASAPI loopback 回喂 analyser):Linux 勉强可行、
  Windows 难,且引入麦克风/回声纠缠。同源代理路径更统一、两台一致。

## 家里 IP 被 YouTube 反爬 → 中心中转(MUSIC_UPSTREAM,零 cookies)
2026-06-12 部署家里 Linux(10.8.0.3)发现:家里 IP 被 YouTube bot 检测拦
("Sign in to confirm you're not a bot",换 player_client 无效),B 站 `bilisearch` 412 风控——
裸 yt-dlp 拿不到直链;**中心(10.8.0.2)IP 没被拦**。
- **决策**:`dev_server.py` 加 `MUSIC_UPSTREAM` env。家里网关设 `MUSIC_UPSTREAM=http://10.8.0.2:8766`,
  `/api/music` 转发到中心同款端点(中心本地 yt-dlp 解析+取流),家里再**同源**回传页面(analyser 不 tainted)。
  中心跑一个 `dev_server` 实例绑 `10.8.0.2:8766`(不设 MUSIC_UPSTREAM = 本地解析)。
- **为何不上 cookies**:cookies = 用户登录态,会过期要维护。家里本就依赖中心跑 STT/TTS,
  走中心中转**不新增可用性依赖、零登录**。已否决 YouTube/B 站 cookies 方案(除非中心也被拦再议)。
- 部署细节(进程/env/yt-dlp 装法)见 [impl-plan-music-playback.md](../impl-plan-music-playback.md) 部署记录。

## 硬约束:放歌不得干扰语音识别
用户明确要求歌声不能影响 KWS/STT。**webview 内播带来的红利**:HUD 100% 知道何时在放、且持有音量控制 →
"听音时确定性静音音乐"成立(mpv 方案做不到)。分层防御(Layer1 STT 静音音乐 / Layer2 OS 级 AEC / Layer3 duck+自适应)
详见 [topics/music-vs-asr-isolation.md](../topics/music-vs-asr-isolation.md)。这是选 webview 内播而非 mpv 的又一理由。

## 残留未决(收窄后,见 open-questions Q6)
- Windows 侧 OS AEC 走哪条;家里 `module-echo-cancel` 对外放音乐的实测压制是否够 KWS 不误触/不漏听。
