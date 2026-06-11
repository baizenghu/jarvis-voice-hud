# 语音回路(Phase 0,Linux/浏览器)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在这台 Linux 上,用浏览器把一整条语音回路跑通:浏览器录音 → 服务端转写 → 走现有 hermes agent 回合 → 服务端合成语音 → 浏览器播放。

**Architecture:** 新增两个字节型 JSON-RPC 方法(`voice.transcribe`、`voice.synthesize`),它们只是把音频字节读/写成临时文件,委托给 hermes 现有的 STT/TTS 引擎(`transcribe_recording`、`text_to_speech_tool`);agent 回合复用现有 `session.create` + `prompt.submit`。一个独立的浏览器测试页(harness)负责录音/播放并按顺序调这些 RPC。不改 agent 主循环,不动现有 `voice.record`/`voice.tts`。详见 [design.md](design.md) 与 [decisions/0001-audio-capture-location.md](decisions/0001-audio-capture-location.md)、[decisions/0004-linux-first-milestone.md](decisions/0004-linux-first-milestone.md)。

**Tech Stack:** Python(FastAPI WS 已存在)、pytest、浏览器 MediaRecorder + Web Audio + WebSocket(原生 JS,无框架)。

---

## 文件结构

- **Create** `tui_gateway/voice_bytes.py` —— 两个纯函数 `transcribe_bytes(audio, mime) -> str`、`synthesize_bytes(text) -> (bytes, mime)`,封装临时文件 + 引擎调用。单一职责、可单测。
- **Modify** `tui_gateway/server.py` —— 在现有 `voice.tts`(约 5226-5239 行)之后,新增两个 RPC 处理函数 `voice.transcribe`、`voice.synthesize`,做 base64 编解码后委托给 `voice_bytes`。
- **Create** `tests/tui_gateway/test_voice_bytes.py` —— 对 `voice_bytes` 两个函数的单测(monkeypatch 引擎,测适配逻辑:后缀选择、空/幻觉处理、字节往返)。
- **Create** `hud-app/voice-harness.html` —— 独立浏览器测试页,跑完整回路。这是后续 Phase 1 正式 HUD 前端目录 `hud-app/` 的第一个文件。

---

## Task 1: `synthesize_bytes` 适配函数

把一段文本交给现有 TTS 引擎,产出音频字节。先做这个,因为它不依赖任何音频输入,最易测。

**Files:**
- Create: `tui_gateway/voice_bytes.py`
- Test: `tests/tui_gateway/test_voice_bytes.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/tui_gateway/test_voice_bytes.py`:

```python
"""Unit tests for tui_gateway.voice_bytes — the STT/TTS byte adapters."""
import json
from pathlib import Path

import tui_gateway.voice_bytes as vb


def test_synthesize_bytes_reads_engine_output(monkeypatch, tmp_path):
    # Fake the TTS engine: write known bytes to the requested output_path,
    # return the JSON envelope the real text_to_speech_tool returns.
    def fake_tts(text, output_path=None):
        Path(output_path).write_bytes(b"ID3fake-mp3-bytes")
        return json.dumps({"success": True, "file_path": output_path})

    monkeypatch.setattr(vb, "text_to_speech_tool", fake_tts)

    audio, mime = vb.synthesize_bytes("hello world")

    assert audio == b"ID3fake-mp3-bytes"
    assert mime == "audio/mpeg"


def test_synthesize_bytes_empty_text_returns_empty(monkeypatch):
    # Empty text must not call the engine and must return no audio.
    called = False

    def fake_tts(text, output_path=None):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(vb, "text_to_speech_tool", fake_tts)

    audio, mime = vb.synthesize_bytes("   ")

    assert audio == b""
    assert called is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/tui_gateway/test_voice_bytes.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'tui_gateway.voice_bytes'`

- [ ] **Step 3: 写最小实现**

创建 `tui_gateway/voice_bytes.py`:

```python
"""Byte-oriented STT/TTS adapters for the voice HUD.

The HUD captures and plays audio in the browser (see
docs/plantree/plans/jarvis-voice-hud/decisions/0001-audio-capture-location.md),
so the server never touches a microphone. These two functions take/return raw
audio bytes and delegate to hermes' existing engines via a temp file, leaving
tools/transcription_tools.py and tools/tts_tool.py untouched.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Tuple

from tools.tts_tool import text_to_speech_tool
from tools.voice_mode import transcribe_recording

logger = logging.getLogger(__name__)


def synthesize_bytes(text: str) -> Tuple[bytes, str]:
    """Synthesize ``text`` with the configured TTS provider; return (bytes, mime).

    Returns ``(b"", "")`` for empty text or on synthesis failure — the caller
    falls back to showing the reply as text only.
    """
    if not text or not text.strip():
        return b"", ""

    tmp_dir = os.path.join(tempfile.gettempdir(), "hermes_voice")
    os.makedirs(tmp_dir, exist_ok=True)
    mp3_path = os.path.join(tmp_dir, f"synth_{os.getpid()}_{id(text)}.mp3")

    try:
        text_to_speech_tool(text=text, output_path=mp3_path)
    except Exception as e:
        logger.warning("synthesize_bytes: TTS failed: %s", e)
        return b"", ""

    # text_to_speech_tool may emit .ogg for messaging platforms; prefer the
    # explicit .mp3 we asked for, fall back to a sibling .ogg.
    ogg_path = mp3_path[:-4] + ".ogg"
    audio = b""
    mime = ""
    try:
        if os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0:
            with open(mp3_path, "rb") as f:
                audio = f.read()
            mime = "audio/mpeg"
        elif os.path.isfile(ogg_path) and os.path.getsize(ogg_path) > 0:
            with open(ogg_path, "rb") as f:
                audio = f.read()
            mime = "audio/ogg"
    finally:
        for p in (mp3_path, ogg_path):
            try:
                if os.path.isfile(p):
                    os.unlink(p)
            except OSError:
                pass

    return audio, mime
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/tui_gateway/test_voice_bytes.py -q`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add tui_gateway/voice_bytes.py tests/tui_gateway/test_voice_bytes.py
git commit -m "feat(voice-hud): add synthesize_bytes TTS adapter"
```

---

## Task 2: `transcribe_bytes` 适配函数

把浏览器录的音频字节(webm/ogg/wav)交给现有 STT 引擎,返回文本。

**Files:**
- Modify: `tui_gateway/voice_bytes.py`
- Test: `tests/tui_gateway/test_voice_bytes.py`

- [ ] **Step 1: 写失败测试**

在 `tests/tui_gateway/test_voice_bytes.py` 末尾追加:

```python
def test_transcribe_bytes_returns_text_and_uses_mime_suffix(monkeypatch):
    seen = {}

    def fake_transcribe(path, model=None):
        # Capture the suffix so we can assert mime→extension mapping, and the
        # bytes so we know they were written to disk before transcription.
        seen["suffix"] = Path(path).suffix
        seen["bytes"] = Path(path).read_bytes()
        return {"success": True, "transcript": "  hello there  "}

    monkeypatch.setattr(vb, "transcribe_recording", fake_transcribe)

    text = vb.transcribe_bytes(b"fake-webm-bytes", "audio/webm")

    assert text == "hello there"          # stripped
    assert seen["suffix"] == ".webm"      # mime mapped to extension
    assert seen["bytes"] == b"fake-webm-bytes"


def test_transcribe_bytes_empty_transcript_returns_empty(monkeypatch):
    # A filtered/hallucinated turn comes back as success+empty transcript.
    monkeypatch.setattr(
        vb, "transcribe_recording",
        lambda path, model=None: {"success": True, "transcript": "", "filtered": True},
    )
    assert vb.transcribe_bytes(b"x", "audio/ogg") == ""


def test_transcribe_bytes_unknown_mime_defaults_to_webm(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        vb, "transcribe_recording",
        lambda path, model=None: seen.update(suffix=Path(path).suffix) or {"success": True, "transcript": "ok"},
    )
    vb.transcribe_bytes(b"x", "application/octet-stream")
    assert seen["suffix"] == ".webm"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/tui_gateway/test_voice_bytes.py -q`
Expected: FAIL —— `AttributeError: module 'tui_gateway.voice_bytes' has no attribute 'transcribe_bytes'`

- [ ] **Step 3: 写最小实现**

在 `tui_gateway/voice_bytes.py` 顶部 import 区不变,在 `synthesize_bytes` 之前(或之后)新增:

```python
# Browser MediaRecorder MIME types → file extension the STT pipeline accepts.
# Extensions must be in tools.transcription_tools.SUPPORTED_FORMATS.
_MIME_TO_SUFFIX = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
}


def transcribe_bytes(audio: bytes, mime: str) -> str:
    """Transcribe raw audio bytes via the existing STT pipeline; return text.

    Returns ``""`` when there is no audio, when STT failed, or when the turn
    was empty / a filtered Whisper hallucination.
    """
    if not audio:
        return ""

    suffix = _MIME_TO_SUFFIX.get((mime or "").split(";")[0].strip(), ".webm")

    fd, path = tempfile.mkstemp(suffix=suffix, prefix="hermes_stt_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        try:
            result = transcribe_recording(path)
        except Exception as e:
            logger.warning("transcribe_bytes: STT failed: %s", e)
            return ""
    finally:
        try:
            if os.path.isfile(path):
                os.unlink(path)
        except OSError:
            pass

    if not result.get("success"):
        return ""
    return (result.get("transcript") or "").strip()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/tui_gateway/test_voice_bytes.py -q`
Expected: PASS(5 passed)

- [ ] **Step 5: 提交**

```bash
git add tui_gateway/voice_bytes.py tests/tui_gateway/test_voice_bytes.py
git commit -m "feat(voice-hud): add transcribe_bytes STT adapter"
```

---

## Task 3: 两个 JSON-RPC 方法

把适配函数暴露为 `voice.transcribe` / `voice.synthesize`,做 base64 编解码。

**Files:**
- Modify: `tui_gateway/server.py`(在 `voice.tts` 处理函数之后,约 5239 行)
- Test: `tests/tui_gateway/test_voice_bytes.py`

- [ ] **Step 1: 写失败测试**

在 `tests/tui_gateway/test_voice_bytes.py` 末尾追加(直接调 dispatch,验证 RPC 接线):

```python
import base64
import tui_gateway.server as server


def test_rpc_voice_synthesize_returns_base64(monkeypatch):
    # Handlers import from tui_gateway.voice_bytes at call time, so patch the
    # name on the voice_bytes module (NOT on server) — see Task 3 Step 3.
    monkeypatch.setattr(vb, "synthesize_bytes", lambda text: (b"AUDIO", "audio/mpeg"))
    resp = server.dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "voice.synthesize", "params": {"text": "hi"}},
        None,
    )
    assert resp["result"]["mime"] == "audio/mpeg"
    assert base64.b64decode(resp["result"]["audio"]) == b"AUDIO"


def test_rpc_voice_synthesize_requires_text():
    resp = server.dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": "voice.synthesize", "params": {"text": ""}},
        None,
    )
    assert "error" in resp


def test_rpc_voice_transcribe_returns_text(monkeypatch):
    monkeypatch.setattr(vb, "transcribe_bytes", lambda audio, mime: "hello")
    resp = server.dispatch(
        {
            "jsonrpc": "2.0", "id": 3, "method": "voice.transcribe",
            "params": {"audio": base64.b64encode(b"x").decode(), "mime": "audio/webm"},
        },
        None,
    )
    assert resp["result"]["text"] == "hello"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/tui_gateway/test_voice_bytes.py -k rpc -q`
Expected: FAIL —— dispatch 对未知方法返回 error(`test_rpc_voice_synthesize_returns_base64` 断言 `result` 时 KeyError/AssertionError)

- [ ] **Step 3: 写最小实现**

在 `tui_gateway/server.py` 的 `voice.tts` 处理函数之后(`# ── Methods: insights ──` 注释之前)插入:

```python
@method("voice.transcribe")
def _(rid, params: dict) -> dict:
    """Transcribe browser-captured audio bytes (base64) → text.

    The HUD records the mic locally and sends the bytes here; we reuse the
    existing STT engine. See tui_gateway/voice_bytes.py.
    """
    import base64

    b64 = params.get("audio") or ""
    mime = params.get("mime") or "audio/webm"
    if not b64:
        return _err(rid, 4021, "audio required")
    try:
        audio = base64.b64decode(b64)
    except Exception:
        return _err(rid, 4022, "audio is not valid base64")
    try:
        # Lazy import: optional audio deps must surface at call time, not at
        # gateway startup (mirrors the existing voice.tts handler).
        from tui_gateway.voice_bytes import transcribe_bytes

        text = transcribe_bytes(audio, mime)
        return _ok(rid, {"text": text})
    except ImportError:
        return _err(rid, 5027, "voice module not available — install audio dependencies")
    except Exception as e:
        return _err(rid, 5027, str(e))


@method("voice.synthesize")
def _(rid, params: dict) -> dict:
    """Synthesize ``text`` → audio bytes (base64) for the HUD to play."""
    import base64

    text = params.get("text", "")
    if not text or not text.strip():
        return _err(rid, 4023, "text required")
    try:
        from tui_gateway.voice_bytes import synthesize_bytes

        audio, mime = synthesize_bytes(text)
        if not audio:
            return _err(rid, 5028, "synthesis produced no audio")
        return _ok(rid, {"audio": base64.b64encode(audio).decode(), "mime": mime})
    except ImportError:
        return _err(rid, 5028, "voice module not available")
    except Exception as e:
        return _err(rid, 5028, str(e))
```

> **不要**在 `server.py` 顶部 import `voice_bytes`。它会连带在网关启动时 import `tools.tts_tool`/`tools.voice_mode`,在缺音频依赖的环境里会让整个网关启动失败——现有代码刻意懒加载正是为此(见 `voice.tts` 处理函数内的 `from hermes_cli.voice import speak_text`)。两个处理函数都在**函数体内**懒 import,如上所示。测试通过 patch `tui_gateway.voice_bytes` 上的名字生效(因为懒 import 在调用时读取该模块的当前属性)。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/tui_gateway/test_voice_bytes.py -q`
Expected: PASS(8 passed)

- [ ] **Step 5: 提交**

```bash
git add tui_gateway/server.py tests/tui_gateway/test_voice_bytes.py
git commit -m "feat(voice-hud): add voice.transcribe / voice.synthesize RPC methods"
```

---

## Task 4: 浏览器 harness + 端到端跑通

一个独立 HTML 页,按"录音 → transcribe → prompt.submit → 攒 message.complete → synthesize → 播放"走完整回路。这是手动集成验收。

**Files:**
- Create: `hud-app/voice-harness.html`

- [ ] **Step 1: 写 harness 页面**

创建 `hud-app/voice-harness.html`:

```html
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <title>语音回路 harness</title>
  <style>
    body { font: 16px system-ui; max-width: 640px; margin: 40px auto; }
    button { font-size: 18px; padding: 10px 20px; }
    #log { white-space: pre-wrap; background: #111; color: #0f0; padding: 12px;
           margin-top: 16px; border-radius: 8px; min-height: 200px; }
  </style>
</head>
<body>
  <h1>贾维斯语音回路 · Phase 0 harness</h1>
  <p>WS: <code id="wsurl"></code></p>
  <button id="rec">按住说话 (hold to talk)</button>
  <div id="log"></div>

<script>
const WS_URL = `ws://${location.hostname || "localhost"}:8080/api/ws`;
document.getElementById("wsurl").textContent = WS_URL;
const log = (m) => { document.getElementById("log").textContent += m + "\n"; };

let ws, sessionId = null, ridSeq = 1;
const pending = new Map();          // rid -> resolve
let replyText = "", awaitingReply = false, replyDone = null;

function connect() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => log("WS connected");
  ws.onclose = () => log("WS closed");
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {           // RPC response
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
      return;
    }
    if (msg.method === "event") {                  // server event
      const { type, payload } = msg.params;
      if (type === "message.complete" && awaitingReply) {
        replyText = (payload && payload.text) || "";
        awaitingReply = false;
        if (replyDone) replyDone();
      }
    }
  };
}

function rpc(method, params) {
  return new Promise((resolve) => {
    const id = ridSeq++;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
  });
}

async function ensureSession() {
  if (sessionId) return sessionId;
  const r = await rpc("session.create", { cols: 80 });
  sessionId = r.result.session_id;
  log("session: " + sessionId);
  return sessionId;
}

// ---- recording ----
let mediaRecorder, chunks = [];
const btn = document.getElementById("rec");

async function startRec() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  chunks = [];
  mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  mediaRecorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  mediaRecorder.start();
  log("recording…");
}

function blobToBase64(blob) {
  return new Promise((res) => {
    const r = new FileReader();
    r.onloadend = () => res(r.result.split(",")[1]);  // strip data: prefix
    r.readAsDataURL(blob);
  });
}

async function stopRecAndRun() {
  const done = new Promise((res) => (mediaRecorder.onstop = res));
  mediaRecorder.stop();
  mediaRecorder.stream.getTracks().forEach((t) => t.stop());
  await done;

  const blob = new Blob(chunks, { type: "audio/webm" });
  const audio = await blobToBase64(blob);
  log("transcribing…");
  const tr = await rpc("voice.transcribe", { audio, mime: "audio/webm" });
  const text = tr.result && tr.result.text;
  if (!text) { log("(no speech detected)"); return; }
  log("you: " + text);

  await ensureSession();
  replyText = ""; awaitingReply = true;
  const waitReply = new Promise((res) => (replyDone = res));
  await rpc("prompt.submit", { session_id: sessionId, text });
  log("thinking…");
  await waitReply;
  log("hermes: " + replyText);

  log("synthesizing…");
  const syn = await rpc("voice.synthesize", { text: replyText });
  if (syn.error) { log("TTS error: " + syn.error.message); return; }
  const bytes = Uint8Array.from(atob(syn.result.audio), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: syn.result.mime }));
  await new Audio(url).play();
  log("playing reply ▶");
}

btn.addEventListener("mousedown", startRec);
btn.addEventListener("mouseup", stopRecAndRun);
connect();
</script>
</body>
</html>
```

> 环境适配(实测时发现):此机无 `web_dist`(`hermes web` 静态挂载会启动失败)、无 venv、无 LLM key。
> 因此改用 `hud-app/dev_server.py`(只挂 `/api/ws` + 同源托管 harness,绕开 web_dist),并给 harness 加
> **echo 模式**(转写→念回,不需 LLM)先验证我们的新代码;完整对话回路待配置模型后再测。依赖装在项目
> `.venv`:`pip install -e ".[voice]" edge-tts`。

- [ ] **Step 2: 起 dev 服务(提供 WS + harness 页)**

Run: `.venv/bin/python hud-app/dev_server.py`
Expected: 在 127.0.0.1:8080 监听;`/api/ws` 可用,`/` 返回 harness 页。

- [ ] **Step 3: 浏览器验证(echo 模式,不需 LLM)**

浏览器打开 `http://localhost:8080/`(必须 localhost,否则麦克风权限被拒)。
按住 **echo** 按钮说一句话(如"你好,贾维斯"),松开。
Expected(`#log` 依次):`WS connected` → `recording…` → `transcribing…` → `you: …`(你的话)→ `synthesizing…` → `playing ▶`,并**听到**把你的话念回来。
首次会下载 faster-whisper 模型(~150MB),`transcribing…` 可能停顿一会儿。

若报错:
- `(no speech detected)` → STT 没听清;说长一点、靠近麦克风。
- `TTS error` → 检查 edge-tts(需联网)。

- [ ] **Step 4: 完整对话回路(需配置模型 + key)**

先 `.venv/bin/hermes model` 配一个 provider + key,再用 harness 的 **问 hermes** 按钮。
Expected:在 echo 各步之上多出 `session: …` → `thinking…` → `hermes: …`(LLM 回复)→ 念出回复。

- [ ] **Step 5: 提交**

```bash
git add hud-app/voice-harness.html
git commit -m "feat(voice-hud): add browser voice round-trip harness (Linux phase 0)"
```

- [ ] **Step 6: 更新路线图状态**

把 [roadmap.md](roadmap.md) 的 Phase 0 从"下一步"移到"已完成",并在条目后注明"已在 Linux 浏览器跑通(impl-plan-phase0.md)"。提交:

```bash
git add docs/plantree/plans/jarvis-voice-hud/roadmap.md
git commit -m "docs(voice-hud): mark phase 0 done"
```

---

## 完成定义(验收门)
- `python -m pytest tests/tui_gateway/test_voice_bytes.py -q` 全绿(8 passed)。
- 在 Linux 浏览器里完成一次完整的 说话→转写→agent 回复→合成→播放,且听到语音。
- 未触碰 agent 主循环、现有 `voice.record`/`voice.tts`、任一 STT/TTS provider 实现。

## 不在本计划内(留给后续)
- WebGL 贾维斯 HUD 视觉与状态机(Phase 1)。
- VAD 自动断句(本计划用按住说话;Phase 1 再加,见 open-question 3)。
- Tauri 外壳与 Windows 打包(Phase 2)、openWakeWord 唤醒词(Phase 3)。
