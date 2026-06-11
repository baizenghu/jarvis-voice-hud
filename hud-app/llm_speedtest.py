#!/usr/bin/env python3
"""Standalone MiniMax (OpenAI-compatible) latency probe.

Reads base_url/api_key from ~/.hermes/config.yaml (model section). Streams a few
prompts against one or more models and reports:
  - TTFT      : time to first streamed chunk
  - think_end : time until the <think> block closes (reasoning cost)
  - first_say : time to first spoken (post-think) character
  - total     : full completion time
  - chars     : visible (post-think) characters produced

Usage:
  .venv/bin/python hud-app/llm_speedtest.py            # test default + M2.7
  .venv/bin/python hud-app/llm_speedtest.py --list     # list gateway models
  .venv/bin/python hud-app/llm_speedtest.py MiniMax-M3 abab6.5s-chat   # specific models
"""
import json
import os
import sys
import time
import urllib.request

import yaml

CFG = yaml.safe_load(open(os.path.expanduser("~/.hermes/config.yaml")))
M = CFG["model"]
BASE = M["base_url"].rstrip("/")
KEY = M["api_key"]
HEADERS = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}

PROMPTS = [
    "你好",
    "用一句话推荐一部电影",
    "简单解释下什么是黑洞",
]


def list_models() -> None:
    req = urllib.request.Request(BASE + "/models", headers=HEADERS)
    data = json.load(urllib.request.urlopen(req, timeout=20))
    ids = [m.get("id") for m in data.get("data", [])]
    print("gateway models:")
    for i in ids:
        print("  -", i)


def stream_once(model: str, prompt: str) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": 512,
    }).encode()
    req = urllib.request.Request(BASE + "/chat/completions", data=body, headers=HEADERS)
    t0 = time.time()
    ttft = think_end = first_say = None
    buf = ""        # full raw content (incl think)
    in_think = False
    seen_think = False
    resp = urllib.request.urlopen(req, timeout=120)
    for raw in resp:
        line = raw.decode("utf-8", "ignore").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        delta = (obj.get("choices") or [{}])[0].get("delta", {})
        # some gateways carry reasoning in a separate field
        chunk = delta.get("content") or ""
        reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
        if (chunk or reasoning) and ttft is None:
            ttft = time.time() - t0
        if reasoning:
            seen_think = True
        if chunk:
            buf += chunk
            if "<think>" in chunk:
                in_think = True; seen_think = True
            if "</think>" in buf and think_end is None and (in_think or "<think>" in buf):
                think_end = time.time() - t0
            # first visible (post-think) char
            visible = buf.split("</think>")[-1] if "</think>" in buf else ("" if in_think else buf)
            if visible.strip() and first_say is None:
                first_say = time.time() - t0
    total = time.time() - t0
    visible = buf.split("</think>")[-1] if "</think>" in buf else buf
    return {
        "ttft": ttft, "think_end": think_end, "first_say": first_say,
        "total": total, "chars": len(visible.strip()), "reasoning": seen_think,
        "say": visible.strip()[:60],
    }


def main() -> None:
    args = sys.argv[1:]
    if "--list" in args:
        list_models(); return
    models = [a for a in args if not a.startswith("-")] or [M["default"], "MiniMax-M2.7"]
    for model in models:
        print(f"\n===== {model} =====")
        for p in PROMPTS:
            try:
                r = stream_once(model, p)
            except Exception as e:
                print(f"  [{p}] FAILED: {type(e).__name__}: {str(e)[:80]}"); continue
            def f(x): return f"{x:.2f}s" if isinstance(x, float) else "—"
            print(f"  [{p[:12]:<12}] TTFT {f(r['ttft'])} | think {f(r['think_end'])} | "
                  f"first_say {f(r['first_say'])} | total {f(r['total'])} | {r['chars']}字"
                  f"{' (推理)' if r['reasoning'] else ''}")
            print(f"               → {r['say']}")


if __name__ == "__main__":
    main()
