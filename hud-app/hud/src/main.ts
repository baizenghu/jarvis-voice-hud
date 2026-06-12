// Wire rpc + audio + machine + renderer. Dev activation: press-and-hold on the
// canvas (mousedown → listen/record, mouseup → run the full turn).

import "./styles.css";
import { RingHud } from "./hud/ring-hud.ts";
import { AudioEngine, base64ToBytes, blobToBase64 } from "./voice/audio.ts";
import { VoiceMachine } from "./voice/machine.ts";
import { VoiceRpc } from "./voice/rpc.ts";

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
hud.start();

machine.onChange((s) => {
  statusEl.dataset.state = s;
});

let busy = false;

async function beginTurn(): Promise<void> {
  if (busy || !machine.can("START_LISTEN")) {
    return;
  }
  try {
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
  machine.send("STOP_LISTEN"); // → transcribing
  try {
    const { blob, mime } = await audio.stopRecording();
    if (!blob.size) {
      log("(录到 0 字节 — 按住太短或静音)");
      machine.send("RESET");
      return;
    }
    const b64 = await blobToBase64(blob);
    log("transcribing…");
    const text = await rpc.transcribe(b64, mime);
    if (!text) {
      log("(no speech detected)");
      machine.send("RESET");
      return;
    }
    youEl.textContent = `you: ${text}`;
    machine.send("TRANSCRIBED"); // → thinking

    log("thinking…");
    const reply = await rpc.submitPrompt(text);
    replyEl.textContent = `Jarvis: ${reply}`;
    machine.send("REPLIED"); // → speaking

    log("synthesizing…");
    const syn = await rpc.synthesize(reply);
    if (syn) {
      await audio.play(base64ToBytes(syn.audio), syn.mime);
      await audio.awaitPlaybackEnd();
    }
  } catch (e) {
    log(`turn err: ${(e as Error).message}`);
  } finally {
    machine.send("DONE"); // → idle (no-op if already reset)
    machine.send("RESET");
    busy = false;
  }
}

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
