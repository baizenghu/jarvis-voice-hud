// Wire rpc + audio + machine + renderer. Thin client: after STT the text goes to
// the agent (gateway-side brain), which calls voice_hud tools that broadcast
// action events back over /api/events. This file only does I/O + executes those
// actions — no semantic judgment (see design-agent-orchestration.md).
// Dev activation: press-and-hold on the canvas (mousedown → record, mouseup → turn).

import "./styles.css";
import { RingHud } from "./hud/ring-hud.ts";
import { AudioEngine, base64ToBytes, blobToBase64 } from "./voice/audio.ts";
import { VoiceMachine } from "./voice/machine.ts";
import { VoiceRpc, wsUrl } from "./voice/rpc.ts";
import { ActionBuffer, runSession } from "./voice/session.ts";

const canvas = document.getElementById("hud") as HTMLCanvasElement;
const logEl = document.getElementById("log") as HTMLElement;
const youEl = document.getElementById("you") as HTMLElement;
const replyEl = document.getElementById("reply") as HTMLElement;
const statusEl = document.getElementById("status") as HTMLElement;

const log = (m: string): void => {
  logEl.textContent = `${m}\n${logEl.textContent}`.split("\n").slice(0, 12).join("\n");
};

const audio = new AudioEngine();
const machine = new VoiceMachine();
const rpc = new VoiceRpc();
audio.onLog = log;
rpc.onLog = log;
rpc.onStatus = (s) => {
  statusEl.textContent = `ws: ${s}`;
};

// 外部声级:音乐在独立 Chrome 出声,webview analyser 看不到。audio_levels.py 从
// 系统 sink monitor 算出频段经 /api/events 推来(type:"audio"),新鲜(<400ms)时
// 优先用它驱动光圈+背景,否则回落到 webview analyser。
// 粉色音乐态只在「播放器真的在放歌」时开(gequbao_play 发 music_state 信号),
// 不靠音量——否则 TTS(同走此 sink)和系统杂音都会误触发粉色。频段强度仍由
// audio_levels 从系统 monitor 提供;非音乐态的脉动回落到 webview analyser。
let extBands = { bass: 0, mid: 0, treble: 0 };
let extTs = 0;
let musicOn = false;   // 播放器真在放歌(music_state 事件驱动)
let lastLoud = 0;      // 最近一次系统输出够响的时刻
const extFresh = (): boolean => performance.now() - extTs < 400;
// 音乐态:报了 on 且最近 4s 内确有声(歌停/静音/--stop 后自动收回)。
const musicPlaying = (): boolean => musicOn && performance.now() - lastLoud < 4000;

const hud = new RingHud(canvas);
hud.getState = () => machine.state;
hud.getLevel = () => audio.getLevel();
hud.getBands = () => (musicPlaying() && extFresh() ? extBands : audio.getBands());
hud.getMusicActive = () => musicPlaying();
hud.start();

machine.onChange((s) => {
  statusEl.dataset.state = s;
});

let busy = false;
let lastReply = ""; // 回声过滤:记住上一句 TTS 内容
let resumeMusic: () => void = () => {}; // duck/resume around STT windows

// 去掉标点空白只留字词,回声比对不受标点差异干扰
const normalize = (s: string): string => s.replace(/[^\p{L}\p{N}]/gu, "");

// Phase 3: report busy/idle to the gateway so wake-word hits are suppressed
// while a session runs (TTS playback would otherwise re-trigger the KWS).
let eventsWs: WebSocket | null = null;

// Action events from the agent's voice_hud tools, buffered per turn and drained
// after the spoken reply (see runSession). One shared buffer for the session.
const actionBuffer = new ActionBuffer();

// Overlay 模式(Tauri 全屏穿透壳注入 __JARVIS_OVERLAY__):待机隐藏窗口,
// 唤醒现身,退下隐身。浏览器/小球模式下是 no-op。
interface TauriGlobals {
  __JARVIS_OVERLAY__?: boolean;
  __TAURI__?: {
    window: {
      getCurrentWindow(): {
        show(): Promise<void>;
        hide(): Promise<void>;
        setAlwaysOnTop(v: boolean): Promise<void>;
      };
    };
  };
}

function setHudVisible(visible: boolean): void {
  const g = window as TauriGlobals;
  if (!g.__JARVIS_OVERLAY__ || !g.__TAURI__) {
    return;
  }
  const w = g.__TAURI__.window.getCurrentWindow();
  if (visible) {
    // GTK 的 show() 会丢掉 keep-above:现身后必须重申置顶,否则贾维斯开的
    // 浏览器/任何窗口都会盖住光圈。
    void w.show().then(() => w.setAlwaysOnTop(true));
  } else if (!musicPlaying()) {
    // 音乐还在放就别藏:让光圈继续跟着跳(由 music watcher 在停后收回)。
    void w.hide();
  }
}

function reportState(state: "busy" | "idle"): void {
  if (eventsWs?.readyState === WebSocket.OPEN) {
    eventsWs.send(JSON.stringify({ type: state }));
  }
}

function connectEvents(): void {
  // same gateway as the RPC socket (handles the Tauri __JARVIS_WS_URL__ override)
  const ws = new WebSocket(wsUrl().replace(/\/api\/ws$/, "/api/events"));
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data as string) as {
      type?: string;
      query?: string;
      bass?: number;
      mid?: number;
      treble?: number;
      on?: boolean;
    };
    switch (msg.type) {
    case "audio":
      extBands = { bass: msg.bass ?? 0, mid: msg.mid ?? 0, treble: msg.treble ?? 0 };
      extTs = performance.now();
      if (extBands.bass + extBands.mid + extBands.treble > 0.05) {
        lastLoud = extTs;
      }
      break;
    case "music_state":
      musicOn = msg.on ?? false;
      if (musicOn) {
        lastLoud = performance.now();
      }
      break;
    case "wake":
      log("唤醒:贾维斯");
      void wakeSession();
      break;
    case "play_music":
      actionBuffer.push({ type: "play_music", query: msg.query ?? "" });
      break;
    case "stop_music":
      actionBuffer.push({ type: "stop_music" });
      break;
    case "end_session":
      actionBuffer.push({ type: "end_session" });
      break;
    }
  };
  ws.onclose = () => {
    eventsWs = null;
    setTimeout(connectEvents, 2000);
  };
  ws.onopen = () => {
    eventsWs = ws;
  };
}

// ── Manual press-and-hold path (dev): record while held, transcribe + answer on release.

async function beginTurn(): Promise<void> {
  if (busy || !machine.can("START_LISTEN")) {
    return;
  }
  try {
    resumeMusic = audio.duckForSpeech(); // music must not bleed into STT
    await audio.startRecording();
    machine.send("START_LISTEN");
  } catch (e) {
    log(`mic err: ${(e as Error).message}`);
  }
}

async function endTurn(): Promise<void> {
  if (machine.state !== "listening") {
    return;
  }
  busy = true;
  reportState("busy");
  machine.send("STOP_LISTEN"); // → transcribing
  try {
    const text = await finishRecordingToText();
    if (!text) {
      return;
    }
    youEl.textContent = `you: ${text}`;
    machine.send("TRANSCRIBED"); // → thinking
    log("thinking…");
    const reply = await rpc.submitPrompt(text);
    await speak(reply);
  } catch (e) {
    log(`turn err: ${(e as Error).message}`);
  } finally {
    machine.send("DONE"); // → idle (no-op if already reset)
    machine.send("RESET");
    resumeMusic(); // un-duck if music was paused for this window
    resumeMusic = () => {};
    busy = false;
    reportState("idle");
  }
}

// Stop the current recording and transcribe it. Returns the transcript, or null
// if nothing usable was heard (empty/silence/own-echo). Drives the machine
// through transcribing; leaves it in transcribing on success (caller advances).
async function finishRecordingToText(): Promise<string | null> {
  const { blob, mime } = await audio.stopRecording();
  if (!blob.size) {
    log("(录到 0 字节 — 按住太短或静音)");
    machine.send("RESET");
    return null;
  }
  const b64 = await blobToBase64(blob);
  log("transcribing…");
  const text = await rpc.transcribe(b64, mime);
  if (!text) {
    log("(no speech detected)");
    machine.send("RESET");
    return null;
  }
  // 回声过滤:转写出的是贾维斯自己上一句话(的一部分)→ 丢弃,继续听
  const t = normalize(text);
  if (lastReply && t.length >= 3 && normalize(lastReply).includes(t)) {
    log("(忽略自身回声)");
    machine.send("RESET");
    return null;
  }
  return text;
}

// Speak a line via TTS (synthesize + play through the analyser). Remembers it
// for echo filtering and shows it in the UI. Shared by greeting/reply/timeout.
async function speak(text: string): Promise<void> {
  if (!text) {
    return;
  }
  replyEl.textContent = `Jarvis: ${text}`;
  lastReply = text;
  machine.send("REPLIED"); // → speaking (no-op if not in thinking)
  log("synthesizing…");
  try {
    const syn = await rpc.synthesize(text);
    if (syn) {
      await audio.play(base64ToBytes(syn.audio), syn.mime);
      await audio.awaitPlaybackEnd();
    }
  } catch (e) {
    log(`tts err: ${(e as Error).message}`);
  }
  // 播完(或出错)回 idle,否则卡在 speaking(金色),下一轮 autoListen 的
  // START_LISTEN 从 speaking 态无效 → 只能聊一轮。DONE 在非 speaking 态是 no-op。
  machine.send("DONE");
}

// ── Wake-word session: agent-orchestrated conversation loop (runSession).

const WAKE_SILENCE_MS = 1200; // end a turn after this much trailing silence
const WAKE_WAIT_SPEECH_MS = 5000; // give the user this long to start talking
const WAKE_MAX_MS = 15000; // hard cap per listening window
const WAKE_LEVEL = 0.08;
const SESSION_TIMEOUT_MS = 180000; // agent reply timeout → 念提示再听。设 3 分钟,给工具
// 任务(看 skill + 跑 terminal,MiniMax 推理可达数十秒)充足时间,不被砍成"没听清"。
const GREETINGS = ["我在,请讲。", "在的,有什么吩咐?", "先生,随时待命。", "你好 BOSS,我是贾维斯,有什么可以为你效劳?"];

let conversing = false;

// One hands-free listening window: record until trailing silence (after speech),
// or bail when the user never starts talking. Returns the transcript or null
// (no usable speech / own echo). Pure I/O — no LLM call (runSession owns that).
async function autoListen(): Promise<string | null> {
  // 播放尾音 + 混响沉降期,避免下一轮录到贾维斯自己的声音
  await new Promise((r) => setTimeout(r, 800));
  if (!machine.can("START_LISTEN")) {
    return null;
  }
  try {
    resumeMusic = audio.duckForSpeech(); // music must not bleed into STT
    await audio.startRecording();
    machine.send("START_LISTEN");
  } catch (e) {
    log(`mic err: ${(e as Error).message}`);
    return null;
  }
  const t0 = performance.now();
  let lastVoice = performance.now();
  let spoke = false;
  await new Promise<void>((resolve) => {
    const timer = setInterval(() => {
      const now = performance.now();
      if (audio.getLevel() > WAKE_LEVEL) {
        spoke = true;
        lastVoice = now;
      }
      const done =
        (!spoke && now - t0 > WAKE_WAIT_SPEECH_MS) ||
        (spoke && now - lastVoice > WAKE_SILENCE_MS) ||
        now - t0 > WAKE_MAX_MS;
      if (done) {
        clearInterval(timer);
        resolve();
      }
    }, 100);
  });
  if (!spoke) {
    // 整窗没出现人声——丢弃录音,别送 whisper(静音会诱发"中文字幕"类幻觉)
    machine.send("STOP_LISTEN");
    await audio.stopRecording();
    machine.send("RESET");
    resumeMusic(); // un-duck (music kept playing through this idle window)
    resumeMusic = () => {};
    return null;
  }
  machine.send("STOP_LISTEN"); // → transcribing
  try {
    const text = await finishRecordingToText();
    if (text) {
      youEl.textContent = `you: ${text}`;
      machine.send("TRANSCRIBED"); // → thinking
    }
    return text;
  } finally {
    resumeMusic(); // un-duck after STT window
    resumeMusic = () => {};
  }
}

// 对话期间把真实音乐音量压低(经网关 CDP 调 audio.volume),否则音乐灌进 STT 录音,
// 系统 AEC 在 double-talk 下压不净人声,whisper 判 no speech detected。会话结束恢复。
function duckMusic(on: boolean): void {
  const base = wsUrl().replace(/^ws/, "http").replace(/\/api\/ws$/, "");
  void fetch(`${base}/api/music_duck`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on }),
  }).catch(() => {});
}

// Wake → drive the agent-orchestrated session. The agent decides everything
// (answer / play / stop / end); this only assembles the I/O deps.
async function wakeSession(): Promise<void> {
  if (conversing || busy) {
    return;
  }
  conversing = true;
  const duckedMusic = musicPlaying();
  if (duckedMusic) {
    duckMusic(true); // 对话期间压低音乐,STT 才听得清
  }
  await runSession({
    listen: autoListen,
    submitPrompt: (text) => rpc.submitPrompt(text),
    speak,
    playMusic: (q) => audio.playMusic(q),
    stopMusic: () => audio.stopMusic(),
    setHudVisible,
    reportState,
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
    pickGreeting: () => GREETINGS[Math.floor(Math.random() * GREETINGS.length)],
    buffer: actionBuffer,
    timeoutMs: SESSION_TIMEOUT_MS,
  }).catch((e) => log(`session err: ${(e as Error).message}`));
  if (duckedMusic) {
    duckMusic(false); // 会话结束恢复音量(若已停止则无害)
  }
  conversing = false;
}

// ── Text turn (dev): Enter in #ask → prompt.submit → speak reply.

const askEl = document.getElementById("ask") as HTMLInputElement;

async function textTurn(text: string): Promise<void> {
  if (busy || !machine.can("START_LISTEN")) {
    return;
  }
  busy = true;
  reportState("busy");
  machine.send("START_LISTEN");
  machine.send("STOP_LISTEN");
  youEl.textContent = `you: ${text}`;
  machine.send("TRANSCRIBED"); // → thinking
  try {
    log("thinking…");
    const reply = await rpc.submitPrompt(text);
    await speak(reply);
  } catch (e) {
    log(`turn err: ${(e as Error).message}`);
  } finally {
    machine.send("DONE");
    machine.send("RESET");
    busy = false;
    reportState("idle");
  }
}

askEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const text = askEl.value.trim();
    if (text) {
      askEl.value = "";
      void textTurn(text);
    }
  }
});

// Press-and-hold activation.
canvas.addEventListener("mousedown", (e) => {
  e.preventDefault();
  void beginTurn();
});
window.addEventListener("mouseup", () => void endTurn());
// Touch support for tablets.
canvas.addEventListener("touchstart", (e) => {
  e.preventDefault();
  void beginTurn();
}, { passive: false });
window.addEventListener("touchend", () => void endTurn());

rpc.connect().catch((e) => log(`connect failed: ${(e as Error).message}`));
connectEvents();

// 强制把 overlay 抬到最前:GTK 上窗口已是 keep-above 时再 setAlwaysOnTop(true) 是
// no-op(不会重叠抬升),压不过后来获得焦点的浏览器/窗口;切一次 false→true 才会
// 让 WM 重新置顶。
function raiseHud(): void {
  const g = window as TauriGlobals;
  if (!g.__JARVIS_OVERLAY__ || !g.__TAURI__) {
    return;
  }
  const w = g.__TAURI__.window.getCurrentWindow();
  void w.show().then(() => w.setAlwaysOnTop(false)).then(() => w.setAlwaysOnTop(true));
}

// Music watcher:该可见时(放歌/对话中)持续强制置顶,压住贾维斯开的浏览器等窗口;
// 否则(待机)收回隐藏。
setInterval(() => {
  if (musicPlaying() || conversing || busy) {
    raiseHud();
  } else {
    setHudVisible(false);
  }
}, 800);
