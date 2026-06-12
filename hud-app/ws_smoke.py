"""Smoke-test the /api/ws JSON-RPC gateway: session.create + prompt.submit.

Usage: python ws_smoke.py [ws://127.0.0.1:8765/api/ws] ["prompt text"]
Prints the agent reply (message.complete payload) and exits 0; nonzero on failure.
Client-only — the gateway must already be running.
"""
from __future__ import annotations

import asyncio
import json
import sys

import websockets


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8765/api/ws"
    prompt = sys.argv[2] if len(sys.argv) > 2 else "用一句话自我介绍"
    async with websockets.connect(url, open_timeout=10) as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "session.create",
                                  "params": {"cols": 80}}))
        sid = None
        reply = None
        async with asyncio.timeout(120):
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("id") == 1:
                    sid = msg["result"]["session_id"]
                    print(f"session: {sid}", flush=True)
                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "prompt.submit",
                                              "params": {"session_id": sid, "text": prompt}}))
                elif msg.get("method") == "event":
                    p = msg.get("params", {})
                    if p.get("type") == "message.complete":
                        reply = (p.get("payload") or {}).get("text", "")
                        break
        print(f"reply: {reply}")
        return 0 if reply else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
