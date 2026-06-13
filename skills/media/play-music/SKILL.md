---
name: play-music
description: 用户想听歌、放音乐、换一首时,在本机 Linux 桌面用浏览器(歌曲宝 gequbao.com,免费免登录)放歌。严格三步:terminal 开搜索页 → 点歌曲名称进详情页 → 点蓝色"▶ 播放"按钮。
metadata:
  hermes:
    tags: [music, audio, browser, clawtouch, gui]
---
# 网页放歌(歌曲宝 + clawtouch)— 严格三步

用户想听歌时,在本机 Chrome 用 **歌曲宝(gequbao.com)** 放。音乐在浏览器出声(系统声卡),HUD 不跟跳,正常。

## 三步(严格按序,每步后截 1 张图确认)
1. **打开搜索页**:`terminal` 执行 `DISPLAY=:0 xdg-open "https://www.gequbao.com/s/周杰伦 晴天"`(歌名换成用户要的,可带歌手)。等约 2 秒。
2. **点歌曲名称进详情页**:`mcp_clawtouch_hid_screenshot` 截图,找到**第一条结果的歌曲名称蓝色链接**(左侧的"晴天",**不是**右边的"播放&下载"按钮),`mcp_clawtouch_hid_click` 点它 → 进入歌曲详情页。等约 2 秒。
3. **点播放**:`mcp_clawtouch_hid_screenshot` 截图,找到歌名下方、进度条下面的**蓝色"▶ 播放"按钮**,`mcp_clawtouch_hid_click` 点它 → 出声。然后回复用户"好,放<歌名>",**结束**。

## 关键 / 防坑
- **第 3 步必做**:详情页打开后**默认暂停**(进度停在 00:01)。**看到 00:01 不等于在放**,必须亲手点那个蓝色"▶ 播放"。
- **若截屏看到的不是歌曲宝页面**(比如终端、Claude 界面、别的窗口):说明 Chrome 没在前台。先点屏幕左侧 dock 里的 **Chrome 图标**把浏览器调到前台,再重新截图继续——不要对着错窗口点。
- 每步只截 1 张图,点击没点中最多重试 1 次,别无限循环。
- 真打不开/找不到按钮,如实告诉用户。普通对话不触发本流程。
