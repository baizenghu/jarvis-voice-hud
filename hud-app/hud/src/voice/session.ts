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

// 贾维斯↔agent 的边界对象(decisions/0007):agent 一轮应答 = 文本 + 是否结束。
// end 由各 agent 的薄适配器翻译进来(hermes:end_session 工具置位)。
export interface AgentReply {
  text: string; // 要念给用户的口语(沿用 message.complete payload.text)
  end: boolean; // agent 判懂"退下/再见" → true;念完 text 再回待机
}

// 可注入依赖,便于 fake-timer 测会话循环。main.ts 装配真 AudioEngine/rpc/事件订阅。
export interface SessionDeps {
  listen: () => Promise<string | null>; // 一窗录音+VAD;无人声/回声 → null
  submitPrompt: (text: string) => Promise<AgentReply>; // 交 agent,等 {text,end}
  speak: (text: string) => Promise<void>; // TTS 念(招呼/agent 回复/超时兜底)
  playMusic: (query: string) => Promise<void>;
  stopMusic: () => void;
  setHudVisible: (visible: boolean) => void;
  reportState: (state: "busy" | "idle") => void;
  sleep: (ms: number) => Promise<void>; // 注入便于 fake-timers 推进
  pickGreeting: () => string;
  buffer: ActionBuffer;
  timeoutMs: number;
  // expand-contract(phase 3 step B):on=结束只认 reply.end(新边界),off=只认
  // buffer 的 end_session(现状)。互斥,防双触发;默认 off → 行为与今日一致。
  useReplyEnd: boolean;
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
  try {
    // 招呼移入 try、且套硬超时:即便 TTS 合成/播放卡住或抛错,也必走到 finally 清 busy,
    // 否则一次卡死会让网关永远停在 busy、之后所有唤醒被拒。
    await withTimeout(d.speak(d.pickGreeting()), d.timeoutMs, d.sleep);
    for (;;) {
      d.buffer.clear(); // 录音起始:丢弃上一轮 straggler 动作
      const text = await d.listen(); // 复用现有录音/VAD/回声/静音逻辑
      if (text == null) {
        continue; // 无人声/回声:继续听(结束由 agent 调 end_session 决定)
      }
      const reply = await withTimeout(d.submitPrompt(text), d.timeoutMs, d.sleep);
      if (reply === TIMEOUT) {
        await withTimeout(d.speak("没听清,再说一次?"), d.timeoutMs, d.sleep);
        continue;
      }
      await withTimeout(d.speak(reply.text), d.timeoutMs, d.sleep); // 念 agent 回复(超时也不卡)
      await d.sleep(50); // 排空窗:收尾随动作事件
      let endedByBuffer = false;
      for (const act of d.buffer.drain()) {
        if (act.type === "stop_music") {
          d.stopMusic();
        } else if (act.type === "play_music") {
          await d.playMusic(act.query);
        } else if (act.type === "end_session") {
          endedByBuffer = true;
        }
      }
      // flag on:只认 reply.end(忽略 buffer 的 end_session);off:维持现状。互斥防双触发。
      if (d.useReplyEnd ? reply.end : endedByBuffer) {
        break;
      }
    }
  } finally {
    d.setHudVisible(false);
    d.reportState("idle"); // busy 在此清(整会话结束)
  }
}
