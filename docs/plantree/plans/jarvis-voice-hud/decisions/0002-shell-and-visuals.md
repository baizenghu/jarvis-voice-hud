# 决策 0002 —— Tauri v2 外壳 + WebGL HUD 前端

日期:2026-06-11。状态:已采纳(待用户复核计划)。

## 背景
用户想要一个漂亮、带动效的钢铁侠/贾维斯风格 HUD 悬浮在 Windows 桌面上。最终目标是 Windows,
开发在 Linux。参考项目(LumiOS)用的是 Tauri v2 + React/WebGL 前端。

## 决策
- **视觉:** 用一个 web 前端以 WebGL/Canvas 渲染 HUD(发光环 + 粒子 + 音频反应声纹)。web/WebGL
  是用合理成本拿到 shader 驱动辉光、粒子和音频反应效果的唯一可行路径;原生 Python GUI 工具箱做
  这些效果要难得多。
- **外壳:** Tauri v2(Rust + 系统 WebView2)把该前端包成无边框、透明、置顶的桌面窗口。相比
  Electron 选它是因为产物小、内存低,且与 LumiOS 参考一致。相比 PySide/Qt 选它是因为视觉本就
  是 web 原生的。
- **构建:** Windows `.exe` 经 GitHub Actions 产出(从 Linux 交叉编译 Tauri 很折腾,CI 是受支持
  的路径)。前端先在 Linux 普通浏览器里验证,再做任何打包。

## 后果
- ✅ 视觉上限最高;前端可移植;Windows 产物小。
- ✅ 前端与 hermes 解耦(只走 WS RPC),因此可在 Linux 浏览器里开发和测试。
- ➖ Phase 2 才引入 Rust/Tauri 工具链和 CI 打包步骤。

## 被否决的备选
- **Electron** —— 透明窗口最省心,但产物 ~100MB+、内存重。
- **PySide6/Qt + QML** —— 与 hermes 同语言,但 shader 级贾维斯效果比 WebGL 难得多。
