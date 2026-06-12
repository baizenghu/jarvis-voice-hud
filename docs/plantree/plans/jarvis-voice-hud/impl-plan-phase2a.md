# Phase 2a 实施计划 —— Windows 原生 hermes + 远程语音 + 操作本机(文件/命令档)

架构见 [decisions/0005](decisions/0005-windows-native-agent-deployment.md)。本档只做 ①文件/命令档,不含 Pico/GUI(2b)。

## 拓扑
```
Windows 笔记本(192.168.0.3,公司 LAN):
  hermes(源码版,装 D:\hermes-agent-main)──STT/TTS──→ Linux 中心(192.168.0.7)
                            ├─ whisper API  :8010  /v1/audio/transcriptions(OpenAI 兼容)
                            └─ CosyVoice3    :8003  /tts
```

## Linux 中心侧 —— ✅ 已完成并验证
- `hud-app/whisper_api.py`:OpenAI 兼容 `POST /v1/audio/transcriptions`(复用 hermes `transcribe_recording`
  = large-v3 + VAD + 幻觉过滤),`HOST=0.0.0.0 PORT=8010` 起。本机 + 局域网均返回正确文本。
- `hud-app/cosyvoice_server.py`:加 `HOST` 环境变量;`start_cosyvoice.sh` 默认 `HOST=0.0.0.0`,绑局域网。
- 两个 API 从 Windows 实测可达(需绕过 Windows 本地代理,见下)。
- 起服务:
  - `HOST=0.0.0.0 PORT=8010 .venv/bin/python hud-app/whisper_api.py`
  - `bash hud-app/start_cosyvoice.sh`(默认绑 0.0.0.0)

## ⚠️ 关键坑:Windows 本地代理劫持局域网
Windows 设了本地代理 `127.0.0.1:10808`(Clash/V2Ray 类),`curl`/HTTP 客户端会把**连 192.168.0.7 的请求
也走代理** → 代理对 LAN 失败。实测 `--noproxy "*"` 后两个 API 都通。
**→ Windows hermes 必须设 `NO_PROXY`/`no_proxy` 包含中心 IP**(`192.168.0.7`,建议加 `192.168.0.0/16,127.0.0.1`),
让 STT 的 OpenAI 客户端、TTS 桥接的 urllib 都绕过代理直连中心。

## Windows 侧 —— ✅ 已完成并验证(2026-06-11)
目标机:Win11 24H2(192.168.0.3),hermes v0.16.0 原生装在 `%LOCALAPPDATA%\hermes`。
四项端到端实测全过:
- **LLM**:`hermes -z "..."` → 中心 MiniMax-M3(关思考 + 贾维斯人设),回 "我是贾维斯,你的语音助手…"。
- **TTS**:Windows 跑 `cosyvoice_say.py` 桥接 → 中心 8003 → ffmpeg,产出 26KB mp3。
- **STT**:Windows curl → 中心 8010 `/v1/audio/transcriptions` 返回正确文本。
- **操作本机**:`hermes --yolo -z "写文件再读回"`,文件实际落地 Windows 盘并读回。

关键收尾经验:
- 一次性带工具用 `hermes -z`,免审批加 `--yolo`(否则危险命令会卡审批提示)。
- cmd 里 `set VAR=值 &&` 会把空格算进值 → 用 `set "VAR=值"` 引号形式;hermes 配置用 Git Bash `env VAR=值` 无此坑。
- NO_PROXY 必须含 `192.168.0.7,api.minimaxi.com`,否则本地代理劫持 LAN/外网。

## 迁移到 D 盘 + 源码安装 —— ✅ 完成(2026-06-12)
原生版(`install.ps1`)装在 C 盘 `%LOCALAPPDATA%\hermes`。应需求迁到 D 盘,改用**源码 + uv** 安装。

### 为什么不直接搬目录
Python venv 的 `Scripts\*.exe`(含 `hermes.exe`)和 `pyvenv.cfg` 烤死了绝对路径,物理 `move` 会找不到解释器
→ **不能搬,只能干净卸载 + 重装**。

### 步骤
1. **备份配置**:`robocopy "%LOCALAPPDATA%\hermes" "D:\hermes-keep" config.yaml SOUL.md cosyvoice_say.py`。
2. **卸载原生版**:`hermes uninstall --full --yes`(清程序 + 数据 + PATH/HERMES_HOME/HERMES_GIT_BASH_PATH/NO_PROXY)。
   残留 `.git\objects` 只读文件触发 WinError 5 → `attrib -r -s -h ...\* /s /d` 后 `rd /s /q` 强删。
3. **源码已下到** `D:\hermes-agent-main`。系统依赖已具备(独立于已删安装):`uv` / `ffmpeg`(WinGet)/ `git` / `node` / `python`。
4. **uv 装**(照 `setup-hermes.sh` 官方方式):
   ```
   cd /d D:\hermes-agent-main
   set UV_PROJECT_ENVIRONMENT=D:\hermes-agent-main\venv
   uv sync --extra all --locked
   ```
   `[all]` 是 curated 集合,**已排除 voice/faster-whisper/torch**(改懒加载)→ 正合远程 STT/TTS,不拖巨物。
   用 `--extra all`,**不是** `--all-extras`(后者会拉 bedrock/matrix 等 Windows 上 build 失败的后端)。
5. **恢复配置**(从 `D:\hermes-keep`):config.yaml + SOUL.md → `D:\hermes-home\`;cosyvoice_say.py → `D:\hermes-agent-main\`。
   改 config.yaml 里 TTS command 的两处路径:python `/c/...AppData/.../python.exe` → `/d/hermes-agent-main/venv/Scripts/python.exe`;
   脚本 `/c/...hermes/cosyvoice_say.py` → `/d/hermes-agent-main/cosyvoice_say.py`。
6. **环境变量**(`setx` 持久化 / PATH 用 PowerShell `[Environment]::SetEnvironmentVariable(...,'User')` 追加去重):
   - `HERMES_HOME=D:\hermes-home`(config/SOUL/数据都在 D 盘)
   - `HERMES_GIT_BASH_PATH=C:\Program Files\Git\bin\bash.exe`(TTS command 是 bash 语法,卸载时被清,**必须重设**)
   - `NO_PROXY=192.168.0.7,api.minimaxi.com,localhost,127.0.0.1`
   - `PATH += D:\hermes-agent-main\venv\Scripts`
7. **验收**:新开终端 `hermes -z` 测 LLM、Git Bash 跑桥接测 TTS、`--yolo` 测读写本机、curl 测 STT —— 四项全过。

### 最终布局(全在 D 盘)
- `D:\hermes-agent-main\`:源码 + `venv\`(程序本体);`cosyvoice_say.py` 桥接脚本。
- `D:\hermes-home\`:`config.yaml`(TTS 路径已改 D 盘)+ `SOUL.md`。
- `D:\hermes-keep\`:原始备份(可删)。
- 源码版 Python 3.13.2(uv 拉的;原生版是 3.11,都在 `>=3.11,<3.14` 内)。

### 迁移踩坑
- ssh→cmd 上下文里 `%LOCALAPPDATA%`/`%USERPROFILE%` **不展开**,`mkdir`/`move`/`copy` 对新建目录还常报"找不到路径"
  → 一律用**绝对路径 + `robocopy`**(可靠自建目标目录、处理只读)。
- `wmic` 在新版 Win11 已移除 → 查盘符用 `Get-PSDrive` / `Get-CimInstance Win32_LogicalDisk`。
- PowerShell 含中文的复杂命令经 ssh→cmd 易乱码崩 → 改读本机同源仓库 + 纯 ASCII 命令。
- `hermes uninstall` 不动用户自设的 `NO_PROXY`?实测卸载后 `NO_PROXY` 也没了 → 重装务必重设。

### 原始步骤(留存,原生 install.ps1 方式)
目标机已探明:Win11 24H2,原生 Python(anaconda 3.12 / Python 3.11),WSL 没装(不需要),hermes 未装。

1. **装 hermes**(PowerShell,非交互):`iex (irm https://hermes-agent.nousresearch.com/install.ps1)`
   —— 自带 uv/Python3.11/Node/ffmpeg/MinGit,装在 `%LOCALAPPDATA%\hermes`,免管理员。
2. **设 `NO_PROXY`**(用户或环境变量):`setx NO_PROXY "192.168.0.7,192.168.0.0/16,127.0.0.1,localhost"`。
3. **配 hermes 模型**(同中心):`provider: custom` → `https://api.minimaxi.com/v1` + 那个 MiniMax key;
   `custom_providers[].extra_body: {thinking: {type: disabled}}`(M3 关思考);`model.default: MiniMax-M3`。
4. **配 STT 指向中心**:`stt.provider: openai`,`stt.openai.base_url: http://192.168.0.7:8010/v1`,
   `stt.openai.api_key: dummy`,`stt.openai.model: large-v3`。
5. **配 TTS 指向中心**:把 `hud-app/cosyvoice_say.py` 拷到 Windows;`tts.provider: cosyvoice`,
   command 用 hermes 自带 python 跑该桥接,env 设 `COSYVOICE_API=http://192.168.0.7:8003` + `no_proxy=192.168.0.7`。
6. **SOUL**:把"短句、禁顿号列举"的人设拷到 Windows hermes。
7. **验收**:在 Windows 上 `hermes` 跑一轮对话(文本),确认走中心 STT/TTS;再让贾维斯读写本机文件、跑命令
   (验证"操作本机"那档)。HUD(Tauri)留到 2c。 —— ✅ 全部完成

## 完成定义 —— ✅ 全部达成(原生 2026-06-11 / 迁 D 盘源码版 2026-06-12)
- Windows 上的 hermes 能:语音转写(经中心 whisper)→ MiniMax-M3 回复 → 合成念回(经中心 CosyVoice 昊然嗓);
- 且能读写 Windows 本机文件、跑本机命令(Git Bash)。
- 全程局域网直连中心(NO_PROXY 生效)。
- 当前部署:源码 + uv 装在 `D:\hermes-agent-main`,数据/配置在 `D:\hermes-home`,C 盘已清空。

## 不在本档内
- Pico/clawtouch GUI 自动化(2b,等硬件);Tauri 悬浮窗(2c)。
