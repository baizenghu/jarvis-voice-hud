import { describe, expect, it } from "vitest";
import { bandLevels, base64ToBytes, encodeWav, parseMusicIntent, pickMime } from "./audio.ts";

describe("bandLevels", () => {
  it("returns zeros for an empty spectrum", () => {
    expect(bandLevels(new Uint8Array(0))).toEqual({ bass: 0, mid: 0, treble: 0 });
  });

  it("isolates energy into the band it falls in (128 bins)", () => {
    const bass = new Uint8Array(128); // bins 0..10 = bass (< 8% of 128)
    bass[0] = 255;
    bass[2] = 255;
    expect(bandLevels(bass).bass).toBeGreaterThan(0);
    expect(bandLevels(bass).mid).toBe(0);
    expect(bandLevels(bass).treble).toBe(0);

    const treble = new Uint8Array(128);
    treble[120] = 255; // top bins = treble (>= 35%)
    expect(bandLevels(treble).treble).toBeGreaterThan(0);
    expect(bandLevels(treble).bass).toBe(0);
  });

  it("normalizes a full-scale band to ~1", () => {
    const full = new Uint8Array(128).fill(255);
    expect(bandLevels(full).bass).toBeCloseTo(1, 5);
    expect(bandLevels(full).treble).toBeCloseTo(1, 5);
  });
});

describe("parseMusicIntent", () => {
  it("extracts the song after a play verb + 首/点", () => {
    expect(parseMusicIntent("放首晴天")).toEqual({ action: "play", query: "晴天" });
    expect(parseMusicIntent("来首张学友的歌")).toEqual({ action: "play", query: "张学友的歌" });
    expect(parseMusicIntent("放点轻音乐")).toEqual({ action: "play", query: "轻音乐" });
  });

  it("handles 播放/点播 with the rest as query", () => {
    expect(parseMusicIntent("播放周杰伦的晴天")).toEqual({ action: "play", query: "周杰伦的晴天" });
    expect(parseMusicIntent("帮我播放七里香")).toEqual({ action: "play", query: "七里香" });
  });

  it("matches 放<X>歌/音乐", () => {
    expect(parseMusicIntent("放周杰伦的歌")).toEqual({ action: "play", query: "周杰伦" });
  });

  it("defaults to popular music when no title is given", () => {
    expect(parseMusicIntent("帮我放首歌")).toEqual({ action: "play", query: "热门音乐" });
    expect(parseMusicIntent("放点音乐")).toEqual({ action: "play", query: "热门音乐" });
  });

  it("detects stop commands", () => {
    expect(parseMusicIntent("停")).toEqual({ action: "stop", query: "" });
    expect(parseMusicIntent("别放了")).toEqual({ action: "stop", query: "" });
    expect(parseMusicIntent("关掉音乐")).toEqual({ action: "stop", query: "" });
  });

  it("returns null for non-music utterances (no false positives)", () => {
    expect(parseMusicIntent("今天天气怎么样")).toBeNull();
    expect(parseMusicIntent("放假了吗")).toBeNull();
    expect(parseMusicIntent("放心吧")).toBeNull();
  });
});

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
