---
name: play-music
description: 用户想听歌/放音乐/换歌/停止时,调 play_music / stop_music 工具在语音 HUD 播放
platforms: [linux, windows]
metadata:
  hermes:
    tags: [music, audio, voice-hud, playback]
---
# 播放音乐(语音 HUD)
用户想听歌/换歌时:调 `play_music(query=真实歌名)`。纠正同音错字("放手晴天"→晴天),
可带歌手("周杰伦 晴天")。没指定具体歌→`query=""`(放热门)。想停/别放了→`stop_music`。
听懂"退下/再见/不聊了"→`end_session`。
调完工具,再用一句口语确认(会被念出来),例:"好,这就放晴天。"
普通对话不要调这些工具。
