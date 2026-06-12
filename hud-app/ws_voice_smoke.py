"""Smoke-test gateway voice methods: synthesize text, then transcribe it back.

Usage: python ws_voice_smoke.py [ws://127.0.0.1:8765/api/ws] ["text"]
Round-trip: voice.synthesize → audio → voice.transcribe → text. Exit 0 if both legs work.
"""
from __future__ import annotations

import asyncio
import json
import sys

import websockets


async def rpc(ws, rid: int, method: str, params: dict) -> dict:
    await ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))
    async for raw in ws:
        msg = json.loads(raw)
        if msg.get("id") == rid:
            return msg


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8765/api/ws"
    text = sys.argv[2] if len(sys.argv) > 2 else "你好,我是贾维斯"
    async with websockets.connect(url, open_timeout=10, max_size=64 * 1024 * 1024) as ws:
        async with asyncio.timeout(180):
            syn = await rpc(ws, 1, "voice.synthesize", {"text": text})
            if syn.get("error"):
                print(f"synthesize ERROR: {syn['error']}")
                return 1
            audio = syn["result"]["audio"]
            mime = syn["result"]["mime"]
            print(f"synthesize OK: {len(audio)} b64 chars, mime={mime}")

            tr = await rpc(ws, 2, "voice.transcribe", {"audio": audio, "mime": mime})
            if tr.get("error"):
                print(f"transcribe ERROR: {tr['error']}")
                return 1
            print(f"transcribe OK: {tr['result'].get('text', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
