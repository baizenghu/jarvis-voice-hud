import { afterEach, describe, expect, it, vi } from "vitest";
import { runSession, type SessionDeps } from "./session.ts";

// 默认桩 + 覆盖,便于 fake-timer 测会话循环主行为。
function stubDeps(over: Partial<SessionDeps>): SessionDeps {
  const base: SessionDeps = {
    listen: async () => null,
    submitPrompt: async () => ({ text: "ok", end: false }),
    speak: async () => {},
    setHudVisible: () => {},
    reportState: () => {},
    sleep: async () => {},
    pickGreeting: () => "<greeting>",
    timeoutMs: 30000,
  };
  return { ...base, ...over };
}

describe("runSession (agent boundary = {text, end})", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reply.end=true → 先念完 text 再退出循环(先念完告别再隐身)", async () => {
    const calls: string[] = [];
    let turn = 0;
    const d = stubDeps({
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
    expect(calls).toEqual(["speak:<greeting>", "speak:好,我退下了"]);
  });

  it("reply.end=false → 不退出,继续下一轮", async () => {
    const calls: string[] = [];
    let turn = 0;
    const d = stubDeps({
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

  it("submitPrompt 超时 → 念提示并继续听,不算结束", async () => {
    vi.useFakeTimers();
    const calls: string[] = [];
    let turn = 0;
    const d = stubDeps({
      listen: async () => (turn === 0 ? "在吗" : "退下"),
      submitPrompt: () => {
        if (turn++ === 0) {
          return new Promise(() => {}); // 永挂 → 超时
        }
        return Promise.resolve({ text: "好,我退下了", end: true });
      },
      speak: async (t) => {
        calls.push("speak:" + t);
      },
      sleep: (ms) => new Promise<void>((r) => setTimeout(r, ms)),
      timeoutMs: 30000,
    });
    const p = runSession(d);
    await vi.runAllTimersAsync();
    await p;
    expect(calls).toEqual(["speak:<greeting>", "speak:没听清,再说一次?", "speak:好,我退下了"]);
  });
});
