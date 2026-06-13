// Thin-client session driver. The agent (gateway-side) is the brain: after STT,
// the text goes to the agent, which decides what to do and calls voice_hud tools
// (play_music / stop_music / end_session). Those tool handlers broadcast action
// events to the HUD over /api/events; this module buffers and applies them. No
// semantic judgment here — only ordering + execution.

export type Action =
  | { type: "play_music"; query: string }
  | { type: "stop_music" }
  | { type: "end_session" };

// 确定性排序:end_session 永远最后(先把动作做完再结束/隐身)。
const RANK: Record<Action["type"], number> = { play_music: 0, stop_music: 0, end_session: 9 };

export function orderActions(actions: Action[]): Action[] {
  return [...actions].sort((x, y) => RANK[x.type] - RANK[y.type]);
}

// turns 串行(每轮 await submitPrompt 完成才听下一轮)→ 无需 turn-id。
// 靠"录音起始 clear() 丢上一轮 straggler + 念回复后 drain() 当前轮"。
export class ActionBuffer {
  private buf: Action[] = [];
  clear(): void {
    this.buf = [];
  }
  push(ev: Action): void {
    this.buf.push(ev);
  }
  drain(): Action[] {
    const out = orderActions(this.buf);
    this.buf = [];
    return out;
  }
}

// 可注入依赖,便于 fake-timer 测会话循环。main.ts 装配真 AudioEngine/rpc/事件订阅。
export interface SessionDeps {
  listen: () => Promise<string | null>; // 一窗录音+VAD;无人声/回声 → null
  submitPrompt: (text: string) => Promise<string>; // 交 agent,等 message.complete
  speak: (text: string) => Promise<void>; // TTS 念(招呼/agent 回复/超时兜底)
  playMusic: (query: string) => Promise<void>;
  stopMusic: () => void;
  setHudVisible: (visible: boolean) => void;
  reportState: (state: "busy" | "idle") => void;
  sleep: (ms: number) => Promise<void>; // 注入便于 fake-timers 推进
  pickGreeting: () => string;
  buffer: ActionBuffer;
  timeoutMs: number;
}

const TIMEOUT = Symbol("timeout");

// 用注入的 sleep 做超时,fake-timers 可推进。submitPrompt 永挂时 sleep 先 resolve。
async function withTimeout<T>(
  p: Promise<T>,
  ms: number,
  sleep: (ms: number) => Promise<void>,
): Promise<T | typeof TIMEOUT> {
  const timeout: Promise<typeof TIMEOUT> = sleep(ms).then(() => TIMEOUT);
  return Promise.race([p, timeout]);
}

// 薄客户端会话循环:wake→报 busy(整会话)+招呼→loop{ 录音起始 clear → listen →
// submitPrompt(超时兜底) → 念回复 → 排空 50ms → drain 执行动作 }。end_session 退出。
// busy 仅在整会话结束(finally)清,不在每轮清——否则 TTS 念到一半第二个唤醒词就触发。
export async function runSession(d: SessionDeps): Promise<void> {
  d.reportState("busy");
  d.setHudVisible(true);
  await d.speak(d.pickGreeting()); // 固定招呼(前端自主说话之一)
  try {
    for (;;) {
      d.buffer.clear(); // 录音起始:丢弃上一轮 straggler 动作
      const text = await d.listen(); // 复用现有录音/VAD/回声/静音逻辑
      if (text == null) {
        continue; // 无人声/回声:继续听(结束由 agent 调 end_session 决定)
      }
      const reply = await withTimeout(d.submitPrompt(text), d.timeoutMs, d.sleep);
      if (reply === TIMEOUT) {
        await d.speak("没听清,再说一次?");
        continue;
      }
      await d.speak(reply); // 念 agent 回复(message.complete 文本)
      await d.sleep(50); // 排空窗:收尾随动作事件
      let ended = false;
      for (const act of d.buffer.drain()) {
        if (act.type === "stop_music") {
          d.stopMusic();
        } else if (act.type === "play_music") {
          await d.playMusic(act.query);
        } else if (act.type === "end_session") {
          ended = true;
        }
      }
      if (ended) {
        break;
      }
    }
  } finally {
    d.setHudVisible(false);
    d.reportState("idle"); // busy 在此清(整会话结束)
  }
}
