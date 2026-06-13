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
