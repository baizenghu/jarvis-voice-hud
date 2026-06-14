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
  now: () => number; // 单一时间源(注入便于 fake-timer 测静默超时)
  idleTimeoutMs: number; // 路②:轮结束后持续静默超此 → 自动退场
  isMusicPlaying: () => boolean; // 当前播放器是否真在放歌(决定录命令前要不要压低)
  duck: (on: boolean) => void; // 压低/恢复音乐音量(经网关 CDP),让 STT 听清命令
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
  let ducked = false;
  try {
    // 招呼套硬超时:即便 TTS 合成/播放卡住或抛错,也必走到 finally 清 busy,
    // 否则一次卡死会让网关永远停在 busy、之后所有唤醒被拒。
    await withTimeout(d.speak(d.pickGreeting()), d.timeoutMs, d.sleep);
    // 路②静默超时基线:招呼后开始计;**只在"轮真正结束后"复位**(不在转写到达时),
    // 否则慢的 submitPrompt 会让下一个静默窗误判超时。长任务期间不在 listen==null 分支,
    // 自然不计入静默。
    let lastSpeechAt = d.now();
    for (;;) {
      // 音乐在放 → 录命令前压低音量,STT 才听得清"停止"。一旦压低就保持到会话结束。
      // 修:原逻辑在 wakeSession 开始判一次,"先点歌再喊停"时点歌那刻还没音乐 → 永不压低 →
      // "停止"被全音量歌声盖住识别不出。改成每轮录音前按"当前"音乐态判。
      if (!ducked && d.isMusicPlaying()) {
        d.duck(true);
        ducked = true;
      }
      const text = await d.listen(); // 复用现有录音/VAD/回声/静音逻辑
      if (text == null) {
        if (d.now() - lastSpeechAt >= d.idleTimeoutMs) {
          break; // 路②:轮后持续静默 → 自动退场(无需 agent end)
        }
        continue; // 仍在静默窗内:继续听(结束由 agent reply.end 或本超时决定)
      }
      const reply = await withTimeout(d.submitPrompt(text), d.timeoutMs, d.sleep);
      if (reply === TIMEOUT) {
        await withTimeout(d.speak("没听清,再说一次?"), d.timeoutMs, d.sleep);
        lastSpeechAt = d.now(); // 用户有说话(只是没答上)→ 算交互,重置静默基线
        continue;
      }
      await withTimeout(d.speak(reply.text), d.timeoutMs, d.sleep); // 念回复(超时也不卡)
      if (reply.end) {
        break; // 路①:先念完 text 再退出 → 先念完告别再隐身
      }
      lastSpeechAt = d.now(); // 轮真正结束后才复位静默基线
    }
  } finally {
    if (ducked) {
      d.duck(false); // 会话结束恢复音乐音量(没压过则不动)
    }
    d.setHudVisible(false);
    d.reportState("idle"); // busy 在此清(整会话结束)
  }
}
