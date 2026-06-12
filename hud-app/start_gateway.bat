@echo off
rem Jarvis HUD local gateway (Windows) — /api/ws on 127.0.0.1:8765.
rem Uses the hermes venv + D:\hermes-home config (MiniMax-M3 + SOUL persona).
set HERMES_HOME=D:\hermes-home
set HOST=127.0.0.1
set PORT=8765
D:\hermes-agent-main\venv\Scripts\python.exe D:\hermes-dev\hud-app\dev_server.py
