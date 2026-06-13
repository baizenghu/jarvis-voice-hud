---
name: play-music
description: 用户想听歌、放音乐、换一首、停止播放时,在本机用浏览器自动放歌(歌曲宝 gequbao.com,免费免登录)。调用脚本 gequbao_play.py 完成——确定性、不靠看屏点击。
metadata:
  hermes:
    tags: [music, audio, browser, playback]
---
# 放歌(歌曲宝 · 脚本自动化)

用户想听歌时,用 `terminal` 执行脚本即可——脚本会自动起浏览器、搜歌、播放(CDP 固定操作,不靠截屏/视觉)。音乐在浏览器出声(系统声卡),HUD 不跟跳,正常。

## 放歌
```
~/hermes-agent/.venv/bin/python ~/hermes-agent/hud-app/gequbao_play.py "周杰伦 晴天"
```
把 `周杰伦 晴天` 换成用户要的歌(带歌手更准)。**看脚本最后一行输出**:
- `PLAYING: <歌名>` → 成功,回复用户"好,放<歌名>"。
- `FAILED: ...` → 没放成,把原因如实告诉用户(别假装放了),可换个歌名再试一次。

## 停止 / 换歌
- 停:`~/hermes-agent/.venv/bin/python ~/hermes-agent/hud-app/gequbao_play.py --stop`
- 换歌:用新歌名再跑一次放歌命令即可(无需先停)。

## 注意
- 只跑这个脚本,不要用 clawtouch 截屏点播放键(那条又慢又不稳,已弃用)。
- 普通对话(非听歌请求)不触发本流程。
