import { describe, expect, it } from "vitest";
import { VoiceMachine } from "./machine.ts";

describe("VoiceMachine", () => {
  it("starts idle", () => {
    expect(new VoiceMachine().state).toBe("idle");
  });

  it("runs the happy-path turn", () => {
    const m = new VoiceMachine();
    expect(m.send("START_LISTEN")).toBe(true);
    expect(m.state).toBe("listening");
    expect(m.send("STOP_LISTEN")).toBe(true);
    expect(m.state).toBe("transcribing");
    expect(m.send("TRANSCRIBED")).toBe(true);
    expect(m.state).toBe("thinking");
    expect(m.send("REPLIED")).toBe(true);
    expect(m.state).toBe("speaking");
    expect(m.send("DONE")).toBe(true);
    expect(m.state).toBe("idle");
  });

  it("rejects invalid transitions", () => {
    const m = new VoiceMachine();
    expect(m.send("STOP_LISTEN")).toBe(false);
    expect(m.send("TRANSCRIBED")).toBe(false);
    expect(m.state).toBe("idle");
  });

  it("RESET returns to idle from any state and is a no-op when idle", () => {
    const m = new VoiceMachine();
    m.send("START_LISTEN");
    m.send("STOP_LISTEN");
    expect(m.state).toBe("transcribing");
    expect(m.send("RESET")).toBe(true);
    expect(m.state).toBe("idle");
    expect(m.send("RESET")).toBe(true); // no-op, still valid
    expect(m.state).toBe("idle");
  });

  it("can() reflects validity", () => {
    const m = new VoiceMachine();
    expect(m.can("START_LISTEN")).toBe(true);
    expect(m.can("STOP_LISTEN")).toBe(false);
    expect(m.can("RESET")).toBe(true);
  });

  it("notifies listeners with next + prev", () => {
    const m = new VoiceMachine();
    const seen: Array<[string, string]> = [];
    const off = m.onChange((s, prev) => seen.push([s, prev]));
    m.send("START_LISTEN");
    m.send("STOP_LISTEN");
    off();
    m.send("TRANSCRIBED"); // not recorded after unsubscribe
    expect(seen).toEqual([
      ["listening", "idle"],
      ["transcribing", "listening"],
    ]);
  });
});
