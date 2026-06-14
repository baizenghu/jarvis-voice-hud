import { afterEach, describe, expect, it, vi } from "vitest";
import { runSession, type SessionDeps } from "./session.ts";

// 默认桩 + 覆盖,便于 fake-timer 测会话循环主行为。
// idleTimeoutMs 默认设极大 → 静默超时在非该用例里不触发。
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
    now: () => 0,
    idleTimeoutMs: Number.MAX_SAFE_INTEGER,
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

describe("runSession 路②:静默超时自动退场", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("唤醒后持续静默超过 idleTimeoutMs → 自动退场(无需 end_session)", async () => {
    const calls: string[] = [];
    let t = 0;
    const d = stubDeps({
      listen: async () => {
        t += 60; // 每个录音窗 60ms,无人声 → null
        return null;
      },
      speak: async (s) => {
        calls.push("speak:" + s);
      },
      now: () => t,
      idleTimeoutMs: 100,
    });
    await runSession(d); // 不抛、不死循环 → 静默超时退出
    expect(calls).toEqual(["speak:<greeting>"]); // 只念了招呼,没别的
  });

  it("用户说话会重置静默基线(不因之前的静默误退)", async () => {
    const calls: string[] = [];
    let t = 0;
    let turn = 0;
    const d = stubDeps({
      listen: async () => {
        t += 60;
        return turn === 0 ? "在吗" : null; // 第一轮说话,之后静默
      },
      submitPrompt: async () => {
        turn++;
        return { text: "在的", end: false };
      },
      speak: async (s) => {
        calls.push("speak:" + s);
      },
      now: () => t,
      idleTimeoutMs: 100,
    });
    await runSession(d);
    // 说了"在吗"→念"在的"→之后静默 100ms 才退;若基线没被说话重置会更早退
    expect(calls).toEqual(["speak:<greeting>", "speak:在的"]);
  });

  it("长任务(submitPrompt 慢)不被算作静默 → 长任务后仍能继续对话(不误退)", async () => {
    const calls: string[] = [];
    let t = 0;
    let li = 0;
    const seq: (string | null)[] = ["查个东西", null, "再问一句", "退下"];
    const d = stubDeps({
      listen: async () => {
        t += 60;
        return li < seq.length ? seq[li++] : "退下"; // 勿用 ?? :会把 seq 里的 null 误吞
      },
      submitPrompt: async (text) => {
        if (text === "查个东西") {
          t += 5000; // 长工具任务推进大量时间
          return { text: "查好了", end: false };
        }
        if (text === "再问一句") return { text: "好的", end: false };
        return { text: "退下了", end: true };
      },
      speak: async (s) => {
        calls.push("speak:" + s);
      },
      now: () => t,
      idleTimeoutMs: 100,
    });
    await runSession(d);
    // 长任务后那个静默窗(seq[1]=null)若基线**错放在转写到达**,5000ms 会被算进静默 →
    // 在此误退,听不到"再问一句"那轮;基线正确放在**轮结束后**则只过了 60ms,继续对话。
    expect(calls).toEqual(["speak:<greeting>", "speak:查好了", "speak:好的", "speak:退下了"]);
  });
});
