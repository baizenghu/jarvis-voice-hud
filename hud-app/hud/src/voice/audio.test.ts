import { describe, expect, it } from "vitest";
import { base64ToBytes, pickMime } from "./audio.ts";

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

describe("base64ToBytes", () => {
  it("decodes ascii base64 to bytes", () => {
    // "hi" → base64 "aGk="
    expect(Array.from(base64ToBytes("aGk="))).toEqual([104, 105]);
  });

  it("decodes empty string to empty array", () => {
    expect(base64ToBytes("").length).toBe(0);
  });
});
