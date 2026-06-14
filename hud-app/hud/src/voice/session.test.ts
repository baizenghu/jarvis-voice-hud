import { afterEach, describe, expect, it, vi } from "vitest";
import { ActionBuffer, orderActions, runSession, type Action, type SessionDeps } from "./session.ts";

describe("orderActions", () => {
  it("play_music 永远排在 end_session 之前", () => {
    const a: Action[] = [{ type: "end_session" }, { type: "play_music", query: "晴天" }];
    expect(orderActions(a).map((x) => x.type)).toEqual(["play_music", "end_session"]);
  });
  it("stop_music 保持在前,end_session 最后", () => {
    const a: Action[] = [{ type: "end_session" }, { type: "stop_music" }];
    expect(orderActions(a).map((x) => x.type)).toEqual(["stop_music", "end_session"]);
  });
});

describe("ActionBuffer", () => {
  it("clear 丢弃上一轮残留,drain 返回当前轮(已排序)", () => {
    const b = new ActionBuffer();
    b.push({ type: "end_session" });
    b.push({ type: "play_music", query: "a" });
    b.clear(); // 模拟新一轮录音起始
    b.push({ type: "end_session" });
    b.push({ type: "play_music", query: "b" });
    expect(b.drain().map((x) => x.type)).toEqual(["play_music", "end_session"]); // 排序 + 只当前轮
    expect(b.drain()).toEqual([]); // drain 后清空
  });
});

// 默认桩 + 覆盖,便于 fake-timer 测会话循环主行为。
function stubDeps(over: Partial<SessionDeps>): SessionDeps {
  const base: SessionDeps = {
    listen: async () => null,
    submitPrompt: async () => ({ text: "ok", end: false }),
    speak: async () => {},
    playMusic: async () => {},
    stopMusic: () => {},
    setHudVisible: () => {},
    reportState: () => {},
    sleep: async () => {},
    pickGreeting: () => "<greeting>",
    buffer: new ActionBuffer(),
    timeoutMs: 30000,
    useReplyEnd: false,
  };
  return { ...base, ...over };
}

describe("runSession (flag off — end via buffer action, current behavior)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("play 在念完确认后才执行,end_session 退出循环", async () => {
    const calls: string[] = [];
    const buffer = new ActionBuffer();
    let turn = 0;
    const d = stubDeps({
      listen: async () => (turn++ === 0 ? "放首晴天" : null),
      submitPrompt: async () => {
        buffer.push({ type: "play_music", query: "晴天" });
        buffer.push({ type: "end_session" });
        return { text: "好,放晴天", end: false };
      },
      speak: async (t) => {
        calls.push("speak:" + t);
      },
      playMusic: async (q) => {
        calls.push("play:" + q);
      },
      buffer,
    });
    await runSession(d);
    expect(calls).toEqual(["speak:<greeting>", "speak:好,放晴天", "play:晴天"]);
  });

  it("submitPrompt 超时 → 念提示并继续听,不崩", async () => {
    vi.useFakeTimers();
    const calls: string[] = [];
    const buffer = new ActionBuffer();
    let turn = 0;
    const d = stubDeps({
      listen: async () => (turn === 0 ? "在吗" : "退下"),
      submitPrompt: () => {
        if (turn++ === 0) {
          return new Promise(() => {}); // 永挂 → 超时
        }
        buffer.push({ type: "end_session" });
        return Promise.resolve({ text: "好,我退下了", end: false });
      },
      speak: async (t) => {
        calls.push("speak:" + t);
      },
      sleep: (ms) => new Promise<void>((r) => setTimeout(r, ms)),
      buffer,
      timeoutMs: 30000,
    });
    const p = runSession(d);
    await vi.runAllTimersAsync();
    await p;
    expect(calls).toEqual(["speak:<greeting>", "speak:没听清,再说一次?", "speak:好,我退下了"]);
  });
});

describe("runSession (flag on — end via reply.end, new {text,end} boundary)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reply.end=true → 先念完 text 再退出循环", async () => {
    const calls: string[] = [];
    let turn = 0;
    const d = stubDeps({
      useReplyEnd: true,
      listen: async () => {
        if (turn++ === 0) return "退下";
        throw new Error("listen called again — should have exited");
      },
      submitPrompt: async () => ({ text: "好,我退下了", end: true }),
      speak: async (t) => {
        calls.push("speak:" + t);
      },
    });
    await runSession(d);
    expect(calls).toEqual(["speak:<greeting>", "speak:好,我退下了"]); // 先念后退
  });

  it("reply.end=false → 不退出,继续下一轮", async () => {
    const calls: string[] = [];
    let turn = 0;
    const d = stubDeps({
      useReplyEnd: true,
      listen: async () => {
        if (turn === 0) return "在吗";
        if (turn === 1) return "退下";
        throw new Error("listen called too many times");
      },
      submitPrompt: async () =>
        turn++ === 0 ? { text: "在的", end: false } : { text: "好,退下了", end: true },
      speak: async (t) => {
        calls.push("speak:" + t);
      },
    });
    await runSession(d);
    expect(calls).toEqual(["speak:<greeting>", "speak:在的", "speak:好,退下了"]);
  });

  it("flag on 时忽略 buffer 的 end_session(互斥,只认 reply.end)", async () => {
    const calls: string[] = [];
    const buffer = new ActionBuffer();
    let turn = 0;
    const d = stubDeps({
      useReplyEnd: true,
      listen: async () => {
        if (turn === 0) return "x";
        if (turn === 1) return "退下";
        throw new Error("listen called too many times");
      },
      submitPrompt: async () => {
        if (turn++ === 0) {
          buffer.push({ type: "end_session" }); // 旧路信号:flag on 必须忽略
          return { text: "第一句", end: false };
        }
        return { text: "好,退下了", end: true };
      },
      speak: async (t) => {
        calls.push("speak:" + t);
      },
      buffer,
    });
    await runSession(d);
    // 若误认 buffer 的 end_session,会在第一轮就退出 → 只到 "第一句"
    expect(calls).toEqual(["speak:<greeting>", "speak:第一句", "speak:好,退下了"]);
  });
});
