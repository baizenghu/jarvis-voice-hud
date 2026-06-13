#!/usr/bin/env python3
"""歌曲宝放歌 — 确定性浏览器自动化(CDP),不靠截屏/vision。

  播放: gequbao_play.py "周杰伦 晴天"   → 起带调试端口的真 Chrome(过 Cloudflare)→
        CDP 导航搜索页 → 取第一条 /music/ 链接 → 直接导航详情页 → audio.play()
  停止: gequbao_play.py --stop          → CDP 暂停当前 audio

最后一行打印 `PLAYING: <歌名>` / `STOPPED` / `FAILED: <原因>`,供调用方判断。
"""
import asyncio, json, os, subprocess, sys, time, urllib.request
import websockets

PORT = 9222
PROFILE = "/tmp/jarvis-chrome"

# Chrome 必须拿到桌面会话的音频环境(XDG_RUNTIME_DIR 指向 PipeWire/Pulse socket),
# 否则有画面无声(页面 audio 在播但没有输出流到系统)。SSH 起子进程时这些 env 缺失。
_UID = os.getuid()
_XRD = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{_UID}"
CHROME_ENV = {
    "DISPLAY": ":0",
    "XDG_RUNTIME_DIR": _XRD,
    "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={_XRD}/bus",
    "PATH": "/usr/bin:/bin",
    "HOME": os.path.expanduser("~"),
}


def signal_music(on: bool):
    """告诉 HUD 网关「真在放歌」与否,驱动光圈粉色音乐态(避免 TTS/杂音误触发)。"""
    gw_port = os.environ.get("PORT", "8765")
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{gw_port}/api/music_state",
            data=json.dumps({"on": on}).encode(),
            headers={"Content-Type": "application/json"}, method="POST"), timeout=2).read()
    except Exception:
        pass


def cdp_targets():
    try:
        return json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=4))
    except Exception:
        return None


def ensure_chrome():
    if cdp_targets() is not None:
        return
    subprocess.Popen(
        ["google-chrome", f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
         "--autoplay-policy=no-user-gesture-required",
         "--no-first-run", "--no-default-browser-check", "--new-window", "about:blank"],
        env=CHROME_ENV,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(25):
        time.sleep(1)
        if cdp_targets() is not None:
            return
    print("FAILED: debug chrome 起不来"); sys.exit(1)


async def connect():
    pages = [t for t in (cdp_targets() or []) if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not pages:
        print("FAILED: 无可用页面"); sys.exit(1)
    return await websockets.connect(pages[0]["webSocketDebuggerUrl"], max_size=None)


async def run(query, stop):
    ensure_chrome()
    ws = await connect()
    i = 0
    async def cmd(method, params=None):
        nonlocal i; i += 1; mid = i
        await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == mid:
                return m.get("result", {})
    async def js(expr, gesture=False):
        r = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "userGesture": gesture, "awaitPromise": True})
        return (r.get("result") or {}).get("value")

    await cmd("Page.enable")
    if stop:
        await js("var x=document.querySelector('audio'); if(x){x.pause()}")
        signal_music(False)
        print("STOPPED"); return

    await cmd("Page.navigate", {"url": "https://www.gequbao.com/s/" + query})
    for _ in range(30):  # 等过 Cloudflare + 出结果
        await asyncio.sleep(1)
        if await js("!!document.querySelector('a[href*=\"/music/\"]')"):
            break
    href = await js("var a=document.querySelector('a[href*=\"/music/\"]'); a?a.getAttribute('href'):null")
    if not href:
        print("FAILED: 搜不到歌(可能被 Cloudflare 挡或无结果)"); return
    detail = "https://www.gequbao.com" + href if href.startswith("/") else href
    await cmd("Page.navigate", {"url": detail})
    for _ in range(20):
        await asyncio.sleep(1)
        if "/music/" in (await js("location.href") or "") and await js("document.readyState==='complete'"):
            break
    # 只 audio.play(),不点播放/暂停切换键(点了反而停)
    res = await js("(async()=>{var x=document.querySelector('audio'); if(!x)return 'no-audio';"
                   "try{await x.play(); return 'ok'}catch(e){return e.name+': '+e.message}})()", gesture=True)
    await asyncio.sleep(2)
    st = await js("var x=document.querySelector('audio'); x?JSON.stringify({paused:x.paused,ct:x.currentTime}):'none'")
    state = json.loads(st) if st and st != "none" else {}
    if res == "ok" and state.get("paused") is False and (state.get("ct") or 0) > 0:
        # 不最小化窗口:最小化会让页面 hidden,歌曲宝随即暂停音乐。让 HUD 光圈靠
        # always-on-top 盖在浏览器之上来解决遮挡问题(见前端 keep-above 重申)。
        signal_music(True)
        print(f"PLAYING: {query}")
    else:
        print(f"FAILED: play={res} state={st}")


def main():
    args = sys.argv[1:]
    stop = "--stop" in args
    query = " ".join(a for a in args if not a.startswith("--")) or "热门"
    asyncio.run(run(query, stop))


if __name__ == "__main__":
    main()
