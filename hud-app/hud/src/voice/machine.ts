// Small, pure state machine for the voice turn. No DOM here — the renderer
// subscribes to onChange and reads the current state. Testable in isolation.

export type HudState =
  | "idle"
  | "listening"
  | "transcribing"
  | "thinking"
  | "speaking";

export type HudEvent =
  | "START_LISTEN" // user pressed: begin mic capture
  | "STOP_LISTEN" // user released: move to transcription
  | "TRANSCRIBED" // STT returned → ask the agent
  | "REPLIED" // agent reply arrived → synthesize + speak
  | "DONE" // playback finished → back to idle
  | "RESET"; // hard reset / error → idle

// Allowed transitions: idle → listening → transcribing → thinking → speaking → idle.
// RESET from anywhere returns to idle.
const TRANSITIONS: Record<HudState, Partial<Record<HudEvent, HudState>>> = {
  idle: { START_LISTEN: "listening" },
  listening: { STOP_LISTEN: "transcribing", RESET: "idle" },
  transcribing: { TRANSCRIBED: "thinking", RESET: "idle" },
  thinking: { REPLIED: "speaking", RESET: "idle" },
  speaking: { DONE: "idle", RESET: "idle" },
};

export class VoiceMachine {
  private current: HudState = "idle";
  private listeners = new Set<(s: HudState, prev: HudState) => void>();

  get state(): HudState {
    return this.current;
  }

  // Returns true if the transition was valid (and applied).
  send(event: HudEvent): boolean {
    // RESET is always valid from any state.
    const next = event === "RESET" ? "idle" : TRANSITIONS[this.current][event];
    if (!next || next === this.current) {
      // RESET while already idle is a no-op but not an error.
      if (event === "RESET") {
        return true;
      }
      return false;
    }
    const prev = this.current;
    this.current = next;
    for (const fn of this.listeners) {
      fn(next, prev);
    }
    return true;
  }

  can(event: HudEvent): boolean {
    if (event === "RESET") {
      return true;
    }
    return Boolean(TRANSITIONS[this.current][event]);
  }

  onChange(fn: (s: HudState, prev: HudState) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
}
