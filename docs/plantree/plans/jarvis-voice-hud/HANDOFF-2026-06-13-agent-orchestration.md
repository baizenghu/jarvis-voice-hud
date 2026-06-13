---
title: HANDOFF 2026-06-13 — 控制权倒转(agent 编排 + 薄客户端)Phase 0-3 建好+验证,Phase 4 真机待做
date: 2026-06-13
status: 分支 feat/voice-hud-agent-orchestration;Phase 0-3 全绿(含 0.3 全链路 smoke);未合 main;未上真机
supersedes: HANDOFF-2026-06-12-phase3免按住与全屏overlay.md
---

# ① 一句话现状
把语音 HUD 从"前端正则当大脑"**倒转**为"agent 编排 + 薄客户端":KWS 开门 → STT 文本交 in-process agent →
agent 调 `play_music`/`stop_music`/`end_session` 工具 → 工具经 `WakeHub.broadcast` 推动作事件到 HUD `/api/events` 执行。
音乐播放/跟跳/中心中转(decisions/0006)不变,**只换触发层**。Phase 0-3 在分支建好并验证,**Phase 4 真机部署+语音验收还没做**。

# ② git + 持久状态
- 分支 **`feat/voice-hud-agent-orchestration`**(从 main 切),提交 `1b5ad5f`(WakeHub.broadcast)→ `15f5f06`(skill)→ **`b8410e7`(toolset 接线修复)**。**未合 main**。
- 设计 [design-agent-orchestration.md](design-agent-orchestration.md);计划 [impl-plan-agent-orchestration.md](impl-plan-agent-orchestration.md)(顶部有进度块)。
- 新代码:`hud-app/voice_hud_tools.py`(三工具 handler)、`hud-app/dev_server.py`(broadcast+注册+`_safe_emit`+monkeypatch `_load_enabled_toolsets`)、`hud-app/hud/src/voice/session.ts`(orderActions/ActionBuffer/runSession)、`hud-app/hud/src/main.ts`(薄客户端装配)、`skills/media/play-music/SKILL.md`、`hud-app/ws_tool_smoke.py`(0.3 smoke)。
- 家里(10.8.0.3)仍跑**旧 Phase 3** 代码(未部署本分支)。中心音乐中转 8766 + 家里网关 MUSIC_UPSTREAM 仍是上篇状态。

# ③ 本轮成果(均有验证)
1. brainstorm→writing-plans→Codex 审查(经代码核实修正 6 处)出设计+计划。
2. workflow 实现 Phase 1/2/3;独立复跑:后端 12 pytest、前端 20 vitest、build/lint 全绿。
3. **Phase 0 闸门**:0.1 minimaxi 裸 API 返 tool_call;0.2 contract 测试绿;**0.3 全链路 smoke 3/3**(中心 :8767 真网关)——放歌→`play_music{query:周杰伦 晴天}`、退下→`end_session`、"今天星期几"→不触发(只答)。
4. **关键修复 `b8410e7`**:注册工具 ≠ agent 能看到——必须 monkeypatch `tui_gateway.server._load_enabled_toolsets` 合并 voice_hud(否则 agent 闲聊+幻觉不调工具)。

# ④ 下一步(Phase 4)+ 负面清单
**Phase 4 真机(动家里实时助手,需用户在场确认)**:tar 推 `dev_server.py`+`voice_hud_tools.py`+`hud/src`(连 src,红线)到家里;装 skill 到 `~/hermes-home/skills/media/play-music/`;重启家里网关(带 `MUSIC_UPSTREAM=http://10.8.0.2:8766`,voice_hud 启用已在 dev_server 自动 monkeypatch);重启 tauri 壳;真喊验收(贾维斯→放首晴天→出声+跟跳→退下→隐身)。然后考虑合 main。

已关闭(别再提议):
- **前端正则判语义**已废(parseMusicIntent/parseMusicDirective/DISMISS_RE 删除)——语义全交 agent。
- **turn-id** 已去(会话内 prompt 串行,靠录音起始 clear + complete 后 50ms drain)。
- **/api/pub 兜底**不存在(dev_server 无此端点);命令通道只有 in-process `WakeHub.broadcast`。
- **MiniMax 走 anthropic_messages** 是内建 provider 的事;**家里是 custom provider + minimaxi base_url → chat_completions**,extra_body thinking:disabled 生效、工具 OpenAI 格式。
- 上篇 HANDOFF ④ 的否决项(openWakeWord/mpv/cookies 等)仍有效。

# ⑤ 重启 verify
```bash
cd /home/baizh/hermes-agent && git branch --show-current   # 预期 feat/voice-hud-agent-orchestration
git log --oneline -8 | grep b8410e7                        # toolset 修复在
.venv/bin/python -m pytest tests/test_voice_hud_tools.py tests/test_wake_hub.py tests/test_voice_hud_contract.py -q   # 9 passed
cd hud-app/hud && npm test 2>&1 | tail -3                  # 20 passed
# 0.3 全链路 smoke(中心,需联网+~/.hermes 的 MiniMax 配置):
cd /home/baizh/hermes-agent
HOST=127.0.0.1 PORT=8767 LOG_LEVEL=info setsid nohup .venv/bin/python -u hud-app/dev_server.py >/tmp/gw8767.log 2>&1 </dev/null &
until curl -s -o /dev/null --max-time 2 http://127.0.0.1:8767/; do sleep 1; done
.venv/bin/python -u hud-app/ws_tool_smoke.py ws://127.0.0.1:8767 "放首周杰伦的晴天"   # 期望 ✅ play_music 事件
fuser -k 8767/tcp                                          # 收尾
```

# ⑥ 约束(承上篇,新增)
- 工具进 agent 清单靠 dev_server 启动的 monkeypatch(`_patch_enabled_toolsets`)——别只 `registry.register` 就以为生效。
- agent 与 dev_server 同进程(in-process AIAgent),`_safe_emit` 用 `safe_schedule_threadsafe(coro, loop)`,loop 在 startup 捕获(handler 在线程池跑)。
- 上篇 ⑥ 全部仍有效(GPU 12G;fuser -k 杀端口;tar 连 hud/src;家里三进程+增益重启不自启;中心音乐中转 8766 必须跑、家里网关须带 MUSIC_UPSTREAM)。

---
## 重启开场白
```
项目 ~/hermes-agent(贾维斯语音 HUD)。读 docs/plantree/plans/jarvis-voice-hud/HANDOFF-2026-06-13-agent-orchestration.md + roadmap.md。
上轮:控制权倒转(agent 编排 + 薄客户端)Phase 0-3 在分支 feat/voice-hud-agent-orchestration 建好并验证(0.3 全链路 smoke 3/3,toolset 接线已修 b8410e7),未合 main、未上真机。
现在做:Phase 4 真机部署家里 + 语音验收(动实时助手,先确认)。
纪律:语义全交 agent(前端正则已废);工具须 monkeypatch _load_enabled_toolsets 才进 agent 清单;家里是 custom provider 走 chat_completions;杀端口 fuser -k;tar 连 hud/src;main 提交先确认。
verify 见 HANDOFF ⑤。
```
