"""0.3 全链路 smoke:prompt.submit → in-process agent → voice_hud 工具 → /api/events 动作事件。
订阅 /api/events 抓 play_music;同时 /api/ws session.create + prompt.submit。
Usage: python ws_tool_smoke.py [base_ws] ["放首晴天"]   网关须已运行。临时脚本,不入库。
"""
from __future__ import annotations
import asyncio, json, sys
import websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8767"
PROMPT = sys.argv[2] if len(sys.argv) > 2 else "放首周杰伦的晴天"


async def listen_events(got: asyncio.Event, box: dict) -> None:
    async with websockets.connect(f"{BASE}/api/events", open_timeout=10) as ws:
        async with asyncio.timeout(150):
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") in ("play_music", "stop_music", "end_session"):
                    box["action"] = msg
                    got.set()
                    return


async def run_prompt() -> str | None:
    async with websockets.connect(f"{BASE}/api/ws", open_timeout=10) as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "session.create", "params": {"cols": 80}}))
        async with asyncio.timeout(150):
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("id") == 1:
                    sid = msg["result"]["session_id"]
                    print(f"session: {sid}", flush=True)
                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "prompt.submit",
                                              "params": {"session_id": sid, "text": PROMPT}}))
                if msg.get("method") == "event" and (msg.get("params") or {}).get("type") == "message.complete":
                    return (msg["params"].get("payload") or {}).get("text", "")
    return None


async def main() -> int:
    got = asyncio.Event(); box: dict = {}
    ev_task = asyncio.create_task(listen_events(got, box))
    await asyncio.sleep(0.5)  # let events subscribe first
    reply = await run_prompt()
    print(f"agent reply: {reply!r}", flush=True)
    try:
        await asyncio.wait_for(got.wait(), timeout=5)
    except asyncio.TimeoutError:
        pass
    ev_task.cancel()
    if box.get("action"):
        print(f"✅ 动作事件到达 /api/events: {box['action']}", flush=True)
        return 0
    print("❌ 未收到 voice_hud 动作事件(agent 没调工具 / 工具没进清单 / 广播没到)", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
