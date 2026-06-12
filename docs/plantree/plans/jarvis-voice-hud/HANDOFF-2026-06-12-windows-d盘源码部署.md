---
title: HANDOFF 2026-06-12 — 贾维斯 agent 迁 D 盘源码部署完成,下一步 2c/2b
date: 2026-06-12
status: Phase 2a 全部完成并验证(原生→迁 D 盘源码版);2b 等硬件、2c 可立即做;本 session 2 个 plantree 文档未提交
supersedes:
---

# ① 一句话现状

贾维斯语音 agent 已**原生跑在 Windows**(192.168.0.3,源码+uv 装在 `D:\hermes-agent-main`,配置在 `D:\hermes-home`,C 盘已清),
STT/TTS 远程调 Linux 中心(192.168.0.7)。**Phase 2a(Windows 原生 + 远程语音 + 操作本机)四项端到端验证全过**。
下一步:**2c Tauri 悬浮 HUD**(不阻塞,可立即做)或 **2b clawtouch GUI**(阻塞:Pico 2 硬件未到)。

# ② git + 持久状态

- repo:`/home/baizh/hermes-agent`,分支 **`main`**(phase2a 系列已并入 main,`main..HEAD` = 0)。
- 最新 commit:`9182edd`(docs: impl-plan-phase2a)。`cosyvoice_say.py` / `cosyvoice_server.py` / `whisper_api.py` 均已在之前提交(在 tree 内)。
- ⚠️ **本 session 有 3 项未提交**(`git status --short`,均为文档,无代码改动):
  - `M docs/plantree/plans/jarvis-voice-hud/impl-plan-phase2a.md`(加「迁 D 盘+源码安装」整节 + 完成定义)
  - `M docs/plantree/plans/jarvis-voice-hud/roadmap.md`(2a 标完成 + D 盘迁移 + 顶部「NEW SESSION 入口」指针)
  - `?? docs/plantree/plans/jarvis-voice-hud/HANDOFF-2026-06-12-windows-d盘源码部署.md`(本文件,新建)
  - 提交前注意:当前在 **main**,按仓库纪律不要未经确认直接 push;要提交先确认是否需开分支。
- 仓库外改动(不在 hermes-agent git 内):全局 `~/.claude/CLAUDE.md` 加了「HANDOFF 交接」段;`mynotebook/` 新增
  `_entities/handoff-策略.md` + `语音助手-贾维斯/2026-06-12-Windows原生部署-源码迁D盘踩坑.md`(+index/log)。
- Windows 部署态(**非 git**,在另一台机):`D:\hermes-agent-main`(源码+`venv\`)、`D:\hermes-home`(`config.yaml`+`SOUL.md`)、`D:\hermes-agent-main\cosyvoice_say.py`(TTS 桥接)、`D:\hermes-keep`(原始备份,可删)。
- 笔记(**独立目录** `/home/baizh/mynotebook/`,非本 repo):本 session 新增 `语音助手-贾维斯/2026-06-12-Windows原生部署-源码迁D盘踩坑.md` + index/log 已更。

# ③ 本 session 成果

1. **Phase 2a 原生 Windows 跑通**(上一 session)→ 本 session **迁 D 盘改源码 uv 安装** —— 证据:`uv sync --extra all --locked` exit 0;四项端到端实测:
   - LLM:`hermes -z "用一句话做个自我介绍"` → "我是贾维斯,你的语音助手,有什么需要尽管说。"(MiniMax-M3 关思考 + SOUL 人设)
   - TTS:Git Bash 跑桥接(D 盘路径)→ 中心 8003 → 产出 `/d/hermes-home/tts_out.mp3` 25749 字节
   - STT:`curl --noproxy "*" http://192.168.0.7:8010/health` → `{"ok":true}`
   - 操作本机:`hermes --yolo -z "写文件再读回"` → `D:\hermes-home\agent_selftest.txt` 实际落盘 `SRC-BUILD-OK`
2. **干净卸载原生版 + 环境变量四件套持久化** —— 证据:`hermes uninstall --full --yes` + `attrib`/`rd` 清残留;`reg query` 确认 PATH/HERMES_HOME 等就绪。
3. **plan-tree 更新**(未提交,见 ②):impl-plan-phase2a 加迁移整节;roadmap 2a 标完成。
4. **mynotebook 踩坑笔记**:新增 Windows 部署/迁移篇 + 与 0611 音频篇双向互链 + index(72→73)/log。

# ④ 下一步 backlog(按 ROI)

1. **2c Tauri 悬浮 HUD** —— 不阻塞、立即可做;无边框置顶悬浮窗连本机 Windows hermes,GitHub Actions 出 `.exe`。做完 Windows 上就有可视贾维斯 HUD。
2. **提交本 session 2 个 plantree 文档** —— 低成本收尾,消除文档漂移(先确认 main/分支策略)。
3. **2b clawtouch GUI** —— 阻塞:Pico 2 未到货。到货后 Windows 装 `clawtouch-mcp` + 刷 `clawtouch-hid` + `clawtouch-skills` 进 skills → 看屏+点击操控 Windows。
4. **Phase 3 唤醒词「贾维斯」** —— openWakeWord,最低优先。

已关闭的决策(别再提议):
- **agent 跨机器执行任务** 已否决 —— 跨机不可靠,改 agent 原生装 Windows、语音两端当远程 API。
- **TTS 用 F5 / GPT-SoVITS / IndexTTS-2 / VoxCPM / Piper / CosyVoice2** 已否决 —— 各有致命问题(漏读参考文本/慢/挤显存/下载慢/机械音/不稳),定 **CosyVoice3-0.5B**。
- **物理搬 venv 到 D 盘** 已否决 —— venv 烤死绝对路径,改卸载重装。
- **`uv sync --all-extras`** 已否决 —— 拉 matrix/python-olm 在 Windows build 失败,用 **`--extra all`**(curated)。
- **MiniMax M2.x** 已否决 —— 关不掉思考(慢),用 **M3**(`thinking:{type:disabled}`)。

# ⑤ 重启 verify

```bash
# --- Linux 中心(本机 /home/baizh/hermes-agent)---
curl -s --max-time 4 http://127.0.0.1:8010/health    # 预期 {"ok":true};不符 → whisper STT 没起,Windows 语音转写会失败
curl -s --max-time 4 http://127.0.0.1:8003/health    # 预期 {"ok":true,"sample_rate":24000};不符 → CosyVoice TTS 没起
cd /home/baizh/hermes-agent && git log --oneline -1  # 预期 9182edd;git status --short 应有 2 个 docs modified(本 session 未提交,符合预期)

# --- Windows(从中心 SSH 过去)---
SSHPASS=baizh sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null baizh@192.168.0.3 "hermes -z 你好"
# 预期:贾维斯短句回复;不符 → config/HERMES_HOME/NO_PROXY/MiniMax key 出问题(逐项查 ⑥)
```

# ⑥ 环境约束与 gotcha

- **中心两服务必须在跑**语音才工作(都绑 0.0.0.0):
  - whisper:`cd /home/baizh/hermes-agent && HOST=0.0.0.0 PORT=8010 .venv/bin/python hud-app/whisper_api.py`
  - cosyvoice:`bash /home/baizh/hermes-agent/hud-app/start_cosyvoice.sh`(conda env `cosyvoice`,GPU ~4-5G)
- **杀残留 server 用 `fuser -k <port>/tcp`**,**别 `pkill -f cosyvoice_server`** —— 模式串出现在自身命令行会自杀(exit 144);harness 还会 block 前台 `sleep`(用 `curl --retry` 或 Monitor 等待)。
- **Windows SSH**:`SSHPASS=baizh sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null baizh@192.168.0.3 "<cmd>"`(密码 baizh,默认 shell=cmd)。**`%LOCALAPPDATA%`/`%USERPROFILE%` 等 env 在单命令里不展开 → 一律绝对路径;文件操作用 `robocopy SRC DST file…`**(可靠建目录/处理只读),`wmic` 已移除用 `Get-PSDrive`。
- **Windows hermes 四件套 env(已持久化,改了要新开终端/新 ssh 才生效)**:
  `HERMES_HOME=D:\hermes-home`、`HERMES_GIT_BASH_PATH=C:\Program Files\Git\bin\bash.exe`(TTS 是 command 型 bash 语法,缺它跑不了)、`NO_PROXY=192.168.0.7,api.minimaxi.com,localhost,127.0.0.1`、`PATH += D:\hermes-agent-main\venv\Scripts`。
- **本地代理 `127.0.0.1:10808` 劫持 LAN** → NO_PROXY 必含中心 IP + MiniMax 域名;curl 手测加 `--noproxy "*"`。
- **CosyVoice3 参考文本必须 `<|endofprompt|>` 格式**(见 `start_cosyvoice.sh` 的 `COSYVOICE_REF_TEXT`),改坏会让声码器崩。
- **语音(麦克风)只能在 Windows 本机终端跑**,不能从 SSH(无麦克风、无 TUI)。文本测试可 SSH `hermes -z`。
- **MiniMax key** 在 Windows `D:\hermes-home\config.yaml` 和中心 `/home/baizh/octopus-slim/.octopus-state/octopus.json`。
- 路标(本项目无 `tasks/todo.md`):新 session 入口看 `docs/plantree/plans/jarvis-voice-hud/roadmap.md` 顶部 + 本篇。

---

## 重启开场白(新 session 第一条消息粘这段)

```
项目 ~/hermes-agent(贾维斯语音 HUD)。读 docs/plantree/plans/jarvis-voice-hud/HANDOFF-2026-06-12-windows-d盘源码部署.md + roadmap.md。
上个 session:贾维斯 agent 迁到 Windows D 盘源码版(D:\hermes-agent-main + D:\hermes-home),Phase 2a 四项端到端全过(commit 9182edd,另有 3 项文档未提交:2 改 + 本 HANDOFF)。
⚠️ 语音依赖中心两服务(whisper :8010 / cosyvoice :8003);麦克风只能在 Windows 本机终端跑,SSH 只能文本 hermes -z。
现在做:① 2c Tauri 悬浮 HUD(不阻塞)或 ② 等 Pico 到货做 2b clawtouch GUI。
纪律不变:杀残留进程用 fuser -k <port>/tcp 别 pkill -f;Windows 远程操作一律绝对路径+robocopy;在 main 上提交/push 先确认。
重启 verify:curl -s http://127.0.0.1:8010/health 和 :8003/health(预期 ok)+ git log --oneline -1(预期 9182edd)。
```
