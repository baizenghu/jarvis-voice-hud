import { describe, expect, it } from "vitest";
import { base64ToBytes, encodeWav, pickMime } from "./audio.ts";

describe("pickMime", () => {
  it("prefers webm when supported", () => {
    expect(pickMime(() => true)).toBe("audio/webm");
  });

  it("falls back to ogg when only ogg is supported", () => {
    expect(pickMime((m) => m === "audio/ogg")).toBe("audio/ogg");
  });

  it("returns empty string when nothing is supported", () => {
    expect(pickMime(() => false)).toBe("");
  });
});

describe("encodeWav", () => {
  it("writes a valid 16-bit mono PCM header and clamped samples", () => {
    const buf = encodeWav(new Float32Array([0, 0.5, -1.5]), 48000);
    const v = new DataView(buf);
    expect(buf.byteLength).toBe(44 + 6);
    expect(String.fromCharCode(v.getUint8(0), v.getUint8(1), v.getUint8(2), v.getUint8(3))).toBe("RIFF");
    expect(v.getUint16(22, true)).toBe(1); // mono
    expect(v.getUint32(24, true)).toBe(48000);
    expect(v.getUint32(40, true)).toBe(6); // data bytes
    expect(v.getInt16(44, true)).toBe(0);
    expect(v.getInt16(46, true)).toBe(Math.floor(0.5 * 0x7fff));
    expect(v.getInt16(48, true)).toBe(-0x8000); // clamped
  });
});

describe("base64ToBytes", () => {
  it("decodes ascii base64 to bytes", () => {
    // "hi" → base64 "aGk="
    expect(Array.from(base64ToBytes("aGk="))).toEqual([104, 105]);
  });

  it("decodes empty string to empty array", () => {
    expect(base64ToBytes("").length).toBe(0);
  });
});
