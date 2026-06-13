#!/usr/bin/env python3
"""读系统输出 sink 的 monitor → FFT 算低/中/高频段声级 → POST 给网关
/api/audio_level,让 HUD 光圈+背景跟独立播放器(歌曲宝 Chrome)的音乐跳动。

webview analyser 只看得到 HUD 自己的音频;音乐在独立 Chrome 走系统声卡,
故由本进程从 sink monitor 抓系统输出补这条可视化链路。

默认读 echocancel_sink.monitor(=当前默认汇,音乐/TTS 都经它)。
用法: audio_levels.py [monitor_device]
"""
import http.client
import json
import os
import subprocess
import sys
import time

import numpy as np

RATE = 16000
CHUNK = 1024            # ~64ms / ~15.6fps
DEV = sys.argv[1] if len(sys.argv) > 1 else "echocancel_sink.monitor"
GW_HOST = "127.0.0.1"
GW_PORT = int(os.environ.get("PORT", "8765"))

FLOOR = 0.0008          # 静音判定(线性能量),低于则不发,HUD 回落到常态
TRAIL_S = 0.5           # 转静音后再补发 0.5s 的 0 帧让光圈平滑收回
_HANN = np.hanning(CHUNK)


def bands(samples: np.ndarray) -> tuple[float, float, float]:
    mag = np.abs(np.fft.rfft(samples * _HANN)) / len(samples)
    freqs = np.fft.rfftfreq(len(samples), 1.0 / RATE)

    def energy(lo: float, hi: float) -> float:
        m = (freqs >= lo) & (freqs < hi)
        return float(np.sqrt(np.mean(mag[m] ** 2))) if m.any() else 0.0

    return energy(20, 200), energy(200, 2000), energy(2000, 8000)


def main() -> None:
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    proc = subprocess.Popen(
        ["parec", "--device=" + DEV, f"--rate={RATE}", "--channels=1", "--format=s16le"],
        stdout=subprocess.PIPE, env=env,
    )
    conn = http.client.HTTPConnection(GW_HOST, GW_PORT, timeout=1)
    peak = [1e-6, 1e-6, 1e-6]
    last_active = 0.0
    nbytes = CHUNK * 2  # s16 = 2 bytes/sample, mono
    while True:
        raw = proc.stdout.read(nbytes)
        if len(raw) < nbytes:
            break
        s = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        b = bands(s)
        now = time.monotonic()
        active = sum(b) > FLOOR
        if active:
            last_active = now
        elif (now - last_active) > TRAIL_S:
            continue  # 静音过久就停发,让 HUD 新鲜窗口过期回落

        out = []
        for i, v in enumerate(b):
            peak[i] = max(v, peak[i] * 0.995)   # 自适应峰值归一,随音量自动缩放
            out.append(min(1.0, v / peak[i]) if active else 0.0)
        payload = json.dumps({"bass": out[0], "mid": out[1], "treble": out[2]})
        try:
            conn.request("POST", "/api/audio_level", body=payload,
                         headers={"Content-Type": "application/json"})
            conn.getresponse().read()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            conn = http.client.HTTPConnection(GW_HOST, GW_PORT, timeout=1)


if __name__ == "__main__":
    main()
