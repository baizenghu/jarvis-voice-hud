#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    WebviewUrl, WebviewWindowBuilder,
};

// 运行期注入:① 本机网关 WS 地址(tauri:// 协议下前端推不出端口);② 透明背景(透出桌面);
// ③ 顶部窄条拖拽区(M3:中心区留给"按住小球说话"的 canvas 事件,不能整窗覆盖);
// ④ phase5:语音服务直连开关/地址/token(从 env 读,不写死、不入源码,见 voice_http.ts)。
//    空值=回退旧 WS 路径(__JARVIS_VOICE_URL__ 空 → voiceSvcBase 走 wsUrl 派生;flag 默认 false)。
const INIT_SCRIPT: &str = r#"
window.__JARVIS_WS_URL__ = 'ws://127.0.0.1:8765/api/ws';
window.__JARVIS_OVERLAY__ = __OVERLAY__;
window.__JARVIS_USE_HTTP_VOICE__ = __USE_HTTP_VOICE__;
window.__JARVIS_VOICE_URL__ = '__VOICE_URL__';
window.__JARVIS_TOKEN__ = '__TOKEN__';
window.addEventListener('DOMContentLoaded', () => {
  const s = document.createElement('style');
  s.textContent = 'html,#hud{background:transparent !important;} body{background:__BG__ !important;}';
  document.head.appendChild(s);
  const drag = document.createElement('div');
  drag.setAttribute('data-tauri-drag-region', '');
  drag.style.cssText = 'position:fixed;top:0;left:0;right:0;height:48px;z-index:1000;cursor:move;';
  document.body.appendChild(drag);
});
"#;

fn main() {
    // JARVIS_OVERLAY=1 → 全屏鼠标穿透 overlay(纯语音交互,点击落到桌面);
    // 不设 → 原 320×320 悬浮小球(Windows 默认形态)。
    let overlay = std::env::var("JARVIS_OVERLAY").map(|v| v == "1").unwrap_or(false);

    // phase5: voice-service direct-connect, injected at runtime (no secrets in source).
    let use_http_voice = std::env::var("JARVIS_USE_HTTP_VOICE").map(|v| v == "1").unwrap_or(false);
    let voice_url = std::env::var("JARVIS_VOICE_URL").unwrap_or_default();
    let voice_token = std::env::var("JARVIS_TOKEN").unwrap_or_default();

    tauri::Builder::default()
        .setup(move |app| {
            // 悬浮 HUD 窗口(在 Rust 建以便挂 initialization_script)。
            let win = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Jarvis HUD")
                .inner_size(320.0, 320.0)
                // 非 overlay 锁尺寸;overlay 需要 set_size 铺满,resizable(false) 会拦下程序化改尺寸
                .resizable(overlay)
                .decorations(false)
                .transparent(true)
                .always_on_top(true)
                .skip_taskbar(true)
                .shadow(false)
                .center()
                // overlay:半透明深色底压住桌面,环更显;小球:全透明
                .initialization_script(
                    &INIT_SCRIPT
                        .replace("__OVERLAY__", if overlay { "true" } else { "false" })
                        .replace("__BG__", if overlay { "rgba(4, 10, 18, 0.55)" } else { "transparent" })
                        .replace("__USE_HTTP_VOICE__", if use_http_voice { "true" } else { "false" })
                        .replace("__VOICE_URL__", &voice_url)
                        .replace("__TOKEN__", &voice_token),
                )
                .build()?;

            if overlay {
                // 不用 fullscreen(true):合成器会对全屏窗口去合成,透明就黑了。
                // 手动铺满显示器 + 鼠标穿透。
                if let Some(monitor) = win.current_monitor()? {
                    win.set_size(*monitor.size())?;
                    win.set_position(tauri::PhysicalPosition::new(0, 0))?;
                }
                win.set_ignore_cursor_events(true)?;
                // 待机隐身:唤醒词到达时由前端 show(),退下后 hide()
                win.hide()?;
            }

            // Linux(WebKitGTK)不弹麦克风授权框,默认拒 getUserMedia —— 宿主显式
            // 开媒体流并放行权限请求(本地 HUD,无第三方内容,放行安全)。
            #[cfg(target_os = "linux")]
            {
                use tauri::Manager;
                let win = app
                    .get_webview_window("main")
                    .expect("main window just built");
                win.with_webview(|webview| {
                    use webkit2gtk::{PermissionRequestExt, SettingsExt, WebViewExt};
                    let wv = webview.inner();
                    if let Some(settings) = WebViewExt::settings(&wv) {
                        settings.set_enable_media_stream(true);
                    }
                    wv.connect_permission_request(|_, req| {
                        req.allow();
                        true
                    });
                })?;
            }

            // 托盘菜单 Quit —— 无边框/skipTaskbar 窗口的退出路径。
            // 图标用 if let 而非 unwrap:图标坏/缺时窗口照起,只是没托盘图标。
            let quit = MenuItem::with_id(app, "quit", "退出 Jarvis HUD", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&quit])?;
            let mut tray = TrayIconBuilder::new()
                .menu(&menu)
                .on_menu_event(|app, event| {
                    if event.id().as_ref() == "quit" {
                        app.exit(0);
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            } else {
                eprintln!("jarvis-hud: no default window icon; tray will use system fallback");
            }
            tray.build(app)?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Jarvis HUD");
}
