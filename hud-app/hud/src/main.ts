// Wire rpc + audio + machine + renderer. Dev activation: press-and-hold on the
// canvas (mousedown → listen/record, mouseup → run the full turn).

import "./styles.css";
import { RingHud } from "./hud/ring-hud.ts";
import { AudioEngine, base64ToBytes, blobToBase64 } from "./voice/audio.ts";
import { VoiceMachine } from "./voice/machine.ts";
import { VoiceRpc, wsUrl } from "./voice/rpc.ts";

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

const hud = new RingHud(canvas);
hud.getState = () => machine.state;
hud.getLevel = () => audio.getLevel();
hud.getBands = () => audio.getBands();
hud.getMusicActive = () => audio.isMusicPlaying();
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
// while a turn runs (TTS playback would otherwise re-trigger the KWS).
let eventsWs: WebSocket | null = null;

// Overlay 模式(Tauri 全屏穿透壳注入 __JARVIS_OVERLAY__):待机隐藏窗口,
// 唤醒现身,退下隐身。浏览器/小球模式下是 no-op。
interface TauriGlobals {
  __JARVIS_OVERLAY__?: boolean;
  __TAURI__?: { window: { getCurrentWindow(): { show(): Promise<void>; hide(): Promise<void> } } };
}

function setHudVisible(visible: boolean): void {
  const g = window as TauriGlobals;
  if (!g.__JARVIS_OVERLAY__ || !g.__TAURI__) {
    return;
  }
  const w = g.__TAURI__.window.getCurrentWindow();
  void (visible ? w.show() : w.hide());
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
    const msg = JSON.parse(e.data as string) as { type?: string };
    if (msg.type === "wake") {
      log("唤醒:贾维斯");
      void wakeTurn();
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

// Returns the user's transcript, or null if nothing usable was heard —
// the wake-conversation loop uses this to decide whether to keep going.
async function endTurn(): Promise<string | null> {
  if (machine.state !== "listening") {
    return null;
  }
  busy = true;
  reportState("busy");
  machine.send("STOP_LISTEN"); // → transcribing
  try {
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
      return "";
    }
    youEl.textContent = `you: ${text}`;
    machine.send("TRANSCRIBED"); // → thinking

    log("thinking…");
    const reply = await rpc.submitPrompt(text);
    replyEl.textContent = `Jarvis: ${reply}`;
    lastReply = reply;
    machine.send("REPLIED"); // → speaking

    log("synthesizing…");
    const syn = await rpc.synthesize(reply);
    if (syn) {
      await audio.play(base64ToBytes(syn.audio), syn.mime);
      await audio.awaitPlaybackEnd();
    }
    return text;
  } catch (e) {
    log(`turn err: ${(e as Error).message}`);
    return null;
  } finally {
    machine.send("DONE"); // → idle (no-op if already reset)
    machine.send("RESET");
    resumeMusic(); // un-duck if music was paused for this window
    resumeMusic = () => {};
    busy = false;
    reportState("idle");
  }
}

// Wake-word activation: conversation mode. After "贾维斯" wakes us, keep
// taking hands-free turns until the user dismisses ("退下/再见/拜拜") or a
// listening window passes with no usable speech.
const WAKE_SILENCE_MS = 1200; // end a turn after this much trailing silence
const WAKE_WAIT_SPEECH_MS = 5000; // give the user this long to start talking
const WAKE_MAX_MS = 15000; // hard cap per listening window
const WAKE_LEVEL = 0.08;
const GREETINGS =["我在,请讲。", "在的,有什么吩咐?", "先生,随时待命。", "你好 BOSS,我是贾维斯,有什么可以为你效劳?"];

let conversing = false;

// One hands-free listening window: record until trailing silence (after
// speech), or bail early when the user never starts talking.
async function autoListen(): Promise<string | null> {
  await beginTurn();
  if (machine.state !== "listening") {
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
  return endTurn();
}

async function wakeTurn(): Promise<void> {
  if (conversing) {
    return;
  }
  conversing = true;
  setHudVisible(true);
  try {
    // 唤醒应答:先打个招呼,让用户知道它在听了
    const hello = GREETINGS[Math.floor(Math.random() * GREETINGS.length)];
    try {
      replyEl.textContent = `Jarvis: ${hello}`;
      lastReply = hello;
      const syn = await rpc.synthesize(hello);
      if (syn) {
        await audio.play(base64ToBytes(syn.audio), syn.mime);
        await audio.awaitPlaybackEnd();
      }
    } catch (e) {
      log(`greet err: ${(e as Error).message}`);
    }
    for (;;) {
      // 播放尾音 + 混响沉降期,避免下一轮录到贾维斯自己的声音
      await new Promise((r) => setTimeout(r, 800));
      const text = await autoListen();
      if (text === "") {
        continue; // 回声被过滤,接着听真人说话
      }
      if (!text) {
        log("(对话结束 — 未听到指令)");
        break;
      }
    }
  } finally {
    conversing = false;
    setHudVisible(false);
  }
}

// Text turn (M2): Enter in #ask → prompt.submit → show reply. Drives the same
// machine through its existing transitions (listening/transcribing flash by).
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
    replyEl.textContent = `Jarvis: ${reply}`;
    machine.send("REPLIED"); // → speaking (no audio in M2)
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
