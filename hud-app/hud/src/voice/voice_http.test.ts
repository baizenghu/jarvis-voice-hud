// Phase 5 step3: HUD-side fetch client for the standalone voice service.
// Approach (a): rpc.ts signatures unchanged; this module adapts base64↔Blob/
// ArrayBuffer internally so main.ts is zero-change. Tests stub window + fetch
// (vitest default node env has no DOM/window).
import { afterEach, describe, expect, it, vi } from "vitest";

import { synthesizeHttp, transcribeHttp, useHttpVoice, voiceSvcBase } from "./voice_http.ts";

type Win = {
  __JARVIS_VOICE_URL__?: string;
  __JARVIS_WS_URL__?: string;
  __JARVIS_TOKEN__?: string;
  __JARVIS_USE_HTTP_VOICE__?: boolean;
};

function stubWindow(w: Win): void {
  vi.stubGlobal("window", w);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useHttpVoice", () => {
  it("defaults to false when the flag is unset", () => {
    stubWindow({});
    expect(useHttpVoice()).toBe(false);
  });

  it("is true only when explicitly injected true", () => {
    stubWindow({ __JARVIS_USE_HTTP_VOICE__: true });
    expect(useHttpVoice()).toBe(true);
  });
});

describe("voiceSvcBase", () => {
  it("prefers the explicit __JARVIS_VOICE_URL__ injection", () => {
    stubWindow({ __JARVIS_VOICE_URL__: "http://10.8.0.2:8011/" });
    expect(voiceSvcBase()).toBe("http://10.8.0.2:8011");
  });

  it("falls back to deriving an http base from the ws url", () => {
    stubWindow({ __JARVIS_WS_URL__: "ws://host:8765/api/ws" });
    expect(voiceSvcBase()).toBe("http://host:8765");
  });
});

describe("transcribeHttp", () => {
  it("POSTs multipart to /transcribe with ?token= and returns result.text", async () => {
    stubWindow({ __JARVIS_VOICE_URL__: "http://c:8011", __JARVIS_TOKEN__: "tok" });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ text: "你好" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const text = await transcribeHttp("QUJD", "audio/webm"); // base64 "ABC"

    expect(text).toBe("你好");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://c:8011/transcribe?token=tok");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("omits ?token= when no token is injected", async () => {
    stubWindow({ __JARVIS_VOICE_URL__: "http://c:8011" });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ text: "x" }) });
    vi.stubGlobal("fetch", fetchMock);
    await transcribeHttp("QUJD", "audio/webm");
    expect(fetchMock.mock.calls[0][0]).toBe("http://c:8011/transcribe");
  });

  it("returns empty string when fetch rejects", async () => {
    stubWindow({ __JARVIS_VOICE_URL__: "http://c:8011" });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    expect(await transcribeHttp("QUJD", "audio/webm")).toBe("");
  });

  it("returns empty string on a non-ok response", async () => {
    stubWindow({ __JARVIS_VOICE_URL__: "http://c:8011" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }));
    expect(await transcribeHttp("QUJD", "audio/webm")).toBe("");
  });
});

describe("synthesizeHttp", () => {
  it("POSTs JSON and wraps the audio bytes back into {audio:b64, mime}", async () => {
    stubWindow({ __JARVIS_VOICE_URL__: "http://c:8011" });
    const wav = new Uint8Array([1, 2, 3, 4]).buffer;
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, arrayBuffer: () => Promise.resolve(wav) });
    vi.stubGlobal("fetch", fetchMock);

    const syn = await synthesizeHttp("好的");

    expect(syn).not.toBeNull();
    expect(syn!.mime).toBe("audio/wav");
    expect(syn!.audio).toBe(btoa("\x01\x02\x03\x04"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://c:8011/synthesize");
    expect(JSON.parse(init.body as string)).toEqual({ text: "好的" });
  });

  it("returns null on a non-ok response (HUD degrades to text-only)", async () => {
    stubWindow({ __JARVIS_VOICE_URL__: "http://c:8011" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502 }));
    expect(await synthesizeHttp("好的")).toBeNull();
  });

  it("returns null when fetch rejects", async () => {
    stubWindow({ __JARVIS_VOICE_URL__: "http://c:8011" });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    expect(await synthesizeHttp("好的")).toBeNull();
  });
});
