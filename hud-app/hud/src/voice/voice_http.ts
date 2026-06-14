// Phase 5 step3: HUD-side fetch client for the standalone voice service
// (hud-app/voice_svc.py). decisions/0007: voice is the agent's mouth+ears; the
// HUD talks to the voice service directly over HTTP instead of tunnelling
// STT/TTS through the gateway's WS RPC.
//
// Approach (a) (chosen): rpc.ts keeps its existing transcribe(b64,mime) /
// synthesize(text)→{audio:b64,mime} signatures, and this module adapts
// base64↔Blob / base64↔ArrayBuffer internally — so main.ts is zero-change. The
// base64 round-trip is removed later in the contract step (delete WS path +
// clean main.ts), not now.

import { base64ToBytes } from "./audio.ts";
import { wsUrl, type SynthesizeResult } from "./rpc.ts";

type VoiceWindow = {
  __JARVIS_VOICE_URL__?: string;
  __JARVIS_TOKEN__?: string;
  __JARVIS_USE_HTTP_VOICE__?: boolean;
};

function win(): VoiceWindow {
  return window as VoiceWindow;
}

// Feature flag — default false (legacy WS path). The real-machine cutover flips
// this via window injection (Tauri initialization_script / build env). Until
// then HUD behaviour is identical to before this module existed.
export function useHttpVoice(): boolean {
  return win().__JARVIS_USE_HTTP_VOICE__ === true;
}

// The voice service may NOT share the gateway's address (phase5 §6 critic), so
// an explicit __JARVIS_VOICE_URL__ injection is primary; deriving an http base
// from the ws url is only a fallback for the same-host dev case.
export function voiceSvcBase(): string {
  const override = win().__JARVIS_VOICE_URL__;
  if (override) {
    return override.replace(/\/$/, "");
  }
  return wsUrl().replace(/^ws/, "http").replace(/\/api\/ws$/, "");
}

function tokenQuery(): string {
  const t = win().__JARVIS_TOKEN__;
  return t ? `?token=${encodeURIComponent(t)}` : "";
}

// MediaRecorder mime → file suffix; the service writes the upload to a tempfile
// whose extension it derives via splitext (whisper_api.py:51 parity).
function suffixFor(mime: string): string {
  const sub = mime.split("/")[1]?.split(";")[0];
  return sub || "webm";
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) {
    bin += String.fromCharCode(bytes[i]);
  }
  return btoa(bin);
}

// transcribe: accept the base64 the rpc layer already has (approach a), POST it
// as multipart so the service gets raw bytes. Any failure → "" (same "no speech
// detected" degradation as the WS path: rpc.ts:130-134).
export async function transcribeHttp(audioB64: string, mime: string): Promise<string> {
  try {
    const blob = new Blob([base64ToBytes(audioB64)], { type: mime });
    const fd = new FormData();
    fd.append("file", blob, `audio.${suffixFor(mime)}`);
    const resp = await fetch(`${voiceSvcBase()}/transcribe${tokenQuery()}`, {
      method: "POST",
      body: fd,
    });
    if (!resp.ok) {
      return "";
    }
    const data = (await resp.json()) as { text?: string };
    return data.text ?? "";
  } catch {
    return "";
  }
}

// synthesize: POST JSON, receive raw audio/wav bytes, re-wrap into the
// {audio:b64, mime} shape main.ts expects (base64ToBytes(syn.audio) at
// main.ts:231). Any non-ok / failure → null (HUD shows text, plays nothing:
// rpc.ts:151-155 parity).
export async function synthesizeHttp(text: string): Promise<SynthesizeResult | null> {
  try {
    const resp = await fetch(`${voiceSvcBase()}/synthesize${tokenQuery()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!resp.ok) {
      return null;
    }
    const buf = await resp.arrayBuffer();
    return { audio: bytesToBase64(new Uint8Array(buf)), mime: "audio/wav" };
  } catch {
    return null;
  }
}
