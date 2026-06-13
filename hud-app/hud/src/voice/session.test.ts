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
    submitPrompt: async () => "ok",
    speak: async () => {},
    playMusic: async () => {},
    stopMusic: () => {},
    setHudVisible: () => {},
    reportState: () => {},
    sleep: async () => {},
    pickGreeting: () => "<greeting>",
    buffer: new ActionBuffer(),
    timeoutMs: 30000,
  };
  return { ...base, ...over };
}

describe("runSession", () => {
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
        return "好,放晴天";
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
    // 招呼→念回复→play→end:play 在 speak 之后,end_session 使其退出
    expect(calls).toEqual(["speak:<greeting>", "speak:好,放晴天", "play:晴天"]);
  });

  it("submitPrompt 超时 → 念提示并继续听,不崩", async () => {
    vi.useFakeTimers();
    const calls: string[] = [];
    const buffer = new ActionBuffer();
    let turn = 0;
    const d = stubDeps({
      // 第一轮触发超时(submitPrompt 永不 resolve),第二轮正常并结束会话
      listen: async () => (turn === 0 ? "在吗" : "退下"),
      submitPrompt: () => {
        if (turn++ === 0) {
          return new Promise<string>(() => {}); // 永挂 → 超时
        }
        buffer.push({ type: "end_session" });
        return Promise.resolve("好,我退下了");
      },
      speak: async (t) => {
        calls.push("speak:" + t);
      },
      // 用真实 setTimeout(被 fake-timer 接管)实现 withTimeout / sleep(50)
      sleep: (ms) => new Promise<void>((r) => setTimeout(r, ms)),
      buffer,
      timeoutMs: 30000,
    });
    const p = runSession(d);
    await vi.runAllTimersAsync();
    await p;
    // 招呼 → 超时兜底 → 第二轮念回复(然后 end_session 退出)
    expect(calls).toEqual(["speak:<greeting>", "speak:没听清,再说一次?", "speak:好,我退下了"]);
  });
});
