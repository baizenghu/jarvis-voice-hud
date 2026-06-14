// Thin-client session driver. The agent (gateway-side) is the brain: after STT,
// the text goes to the agent, which returns {text, end} (decisions/0007). This
// module only does I/O — speak the text, and end the session when end=true. No
// semantic judgment here; music/other actions are the agent's own internal
// skills (not a HUD concern).

// 贾维斯↔agent 的边界对象(decisions/0007):agent 一轮应答 = 文本 + 是否结束。
// end 由各 agent 的薄适配器翻译进来(hermes:end_session 工具置位)。
export interface AgentReply {
  text: string; // 要念给用户的口语(沿用 message.complete payload.text)
  end: boolean; // agent 判懂"退下/再见" → true;念完 text 再回待机
}

// 可注入依赖,便于 fake-timer 测会话循环。main.ts 装配真 rpc/TTS/事件订阅。
export interface SessionDeps {
  listen: () => Promise<string | null>; // 一窗录音+VAD;无人声/回声 → null
  submitPrompt: (text: string) => Promise<AgentReply>; // 交 agent,等 {text,end}
  speak: (text: string) => Promise<void>; // TTS 念(招呼/agent 回复/超时兜底)
  setHudVisible: (visible: boolean) => void;
  reportState: (state: "busy" | "idle") => void;
  sleep: (ms: number) => Promise<void>; // 注入便于 fake-timers 推进
  pickGreeting: () => string;
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

// 薄客户端会话循环:wake→报 busy(整会话)+招呼→loop{ listen → submitPrompt(超时兜底)
// → 念回复 → reply.end 则退出 }。先念完 text 再退出 = "先念完告别再隐身"。
// busy 仅在整会话结束(finally)清,不在每轮清——否则 TTS 念到一半第二个唤醒词就触发。
export async function runSession(d: SessionDeps): Promise<void> {
  d.reportState("busy");
  d.setHudVisible(true);
  try {
    // 招呼套硬超时:即便 TTS 合成/播放卡住或抛错,也必走到 finally 清 busy,
    // 否则一次卡死会让网关永远停在 busy、之后所有唤醒被拒。
    await withTimeout(d.speak(d.pickGreeting()), d.timeoutMs, d.sleep);
    for (;;) {
      const text = await d.listen(); // 复用现有录音/VAD/回声/静音逻辑
      if (text == null) {
        continue; // 无人声/回声:继续听(结束由 agent 的 reply.end 决定)
      }
      const reply = await withTimeout(d.submitPrompt(text), d.timeoutMs, d.sleep);
      if (reply === TIMEOUT) {
        await withTimeout(d.speak("没听清,再说一次?"), d.timeoutMs, d.sleep);
        continue; // 超时不算结束,继续听
      }
      await withTimeout(d.speak(reply.text), d.timeoutMs, d.sleep); // 念回复(超时也不卡)
      if (reply.end) {
        break; // 先念完 text 再退出 → 先念完告别再隐身
      }
    }
  } finally {
    d.setHudVisible(false);
    d.reportState("idle"); // busy 在此清(整会话结束)
  }
}
