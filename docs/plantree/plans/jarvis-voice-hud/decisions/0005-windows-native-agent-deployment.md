# 决策 0005 —— agent 原生跑 Windows,STT/TTS 当 Linux GPU API,GUI 用 clawtouch 本地 MCP

日期:2026-06-11。状态:已采纳(待实施)。

## 背景
最初(decision 0001)把音频放前端、agent + STT/TTS 全放 Linux 中心,Windows 只做瘦 HUD。
但需求升级:**贾维斯要能访问 Windows 上的文件、并操控这台 Windows**(文件/命令 + GUI 自动化)。
"agent 在 A 机操作 B 机"有真实摩擦(路径、上下文、看屏都隔着),不适合"操作本机"的桌面助手。

关键事实(已在目标机 `192.168.0.3` desktop-9oehqe1 实测确认):
- **Windows 11 24H2**(build 26100),OpenSSH 通,默认 cmd。
- **原生 Python 已有**(anaconda 3.12 + Python 3.11)→ clawtouch-mcp 直接可装。
- **WSL 未安装**。
- 局域网到 Linux 中心 `192.168.0.7` ping 4ms,可达。
- **hermes 现已原生支持 Windows**(官网 `install.ps1`:uv + Python 3.11 + Node + ffmpeg + 便携 MinGit
  Git Bash 跑 shell,装在 `%LOCALAPPDATA%\hermes`,免管理员、不碰系统 Git)。磁盘上 0.16.0 旧 README
  说"不支持 native Windows"是过时信息。

## 决策
按"边界是否干净"来切:**无状态字节服务远程化,有状态/本机操作就地化。**

1. **hermes agent 原生装在 Windows**(`install.ps1`,无需 WSL)。
   - 文件/命令是**真·本机**(原生 Windows 路径 + 自带 Git Bash),无 `/mnt/c`、无跨机器。
2. **STT(whisper)+ TTS(CosyVoice3)留 Linux 中心当 HTTP API**(吃 GPU,必须在 3060 这台)。
   - 它们是无状态"字节进字节出",远程调 API 是干净边界。CosyVoice 已是 HTTP(8003),改绑局域网即可;
     whisper 包一个 HTTP 接口(或用 hermes 支持的远程 whisper provider)。
   - Windows hermes 的 `voice.transcribe`/`voice.synthesize` 指向中心 API。
3. **GUI 自动化用 clawtouch 三件套,跑在同一台原生 Windows**:
   - `clawtouch-hid`:Pico 2 刷固件,USB 插 Windows,当真实键鼠(HID,OS 层不可区分,绕过软件自动化限制)。
   - `clawtouch-mcp`:**stdio MCP 服务**,在原生 Windows 跑(要 Pico 的 `COM` 口 + `hid.screenshot` 截
     Windows 桌面);hermes 同在原生 Windows → **本地 stdio 直连**,无 SSH/interop 缝。
   - `clawtouch-skills`:作为 hermes skills(各 App 操作指南)。
4. **HUD**:Tauri 悬浮窗(Phase 2)或先浏览器版,本地连 Windows hermes。

## 拓扑
```
Windows(原生,无 WSL):
  hermes agent ──本地 stdio MCP──→ clawtouch-mcp ──USB──→ Pico ──→ 键鼠 + 截屏
       │  └─ 文件/命令:原生 Windows + Git Bash
       └─ STT/TTS 远程 ↓        Tauri HUD(本地连 hermes)
Linux 中心(GPU):  whisper API + CosyVoice3(8003) 绑局域网
```

## 后果
- ✅ agent 操作文件/GUI 全是"本地",无跨机器执行的别扭(用户核心诉求)。
- ✅ GPU 引擎集中在 Linux 一台;Windows 不需要 GPU。
- ✅ hermes 与 clawtouch-mcp 同机 → GUI 是本地 MCP,最简。
- ➖ 要在 Windows 再装一套 hermes;`voice_bytes` 改为调远程 STT/TTS API;Linux 引擎要对局域网暴露。
- ➖ 需要硬件:一块 **Raspberry Pi Pico 2** 刷 clawtouch-hid(②GUI 的前提;没有则 ① 文件/命令 + 语音先行)。
- 安全:STT/TTS 仅在可信局域网/WG 暴露;clawtouch 是真键鼠,权限等同物理操作本机,注意授权边界。

## 被否决的备选
- **hermes 留 Linux 中心 + SSH/MCP-over-SSH 操作 Windows**:就是用户指出的"跨机器执行"摩擦;且 GUI 部分
  反正都得在原生 Windows,留 Linux 没省到 GUI 的复杂度。
- **hermes 跑 Windows WSL2**:原以为 native Windows 不支持才要 WSL;但 WSL2 摸不到 Pico 的 COM 口、
  截不到 Windows 桌面、文件走 `/mnt/c` 不够本地。既然 hermes 原生支持 Windows,WSL 这条作废。

## 实施顺序(供 roadmap 引用)
① Linux:CosyVoice 绑局域网 + whisper 包 HTTP API。
② Windows:装 hermes(install.ps1)+ 配模型/STT/TTS 指向中心。
③ 跑通"Windows hermes + 远程语音 + 本机文件/命令"(① 档完成)。
④ Pico 到位后:装 clawtouch-mcp + 接本地 MCP + clawtouch-skills(② 档)。
⑤ Tauri HUD 上 Windows(原 Phase 2 视觉壳)。
