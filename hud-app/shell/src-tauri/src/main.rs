#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    WebviewUrl, WebviewWindowBuilder,
};

// 运行期注入:① 透明背景(透出桌面);② 全窗拖拽区(M1 无 canvas 交互)。
// hud 工程零改动 —— 注入发生在 webview 初始化时,不碰 dist 文件。
const INIT_SCRIPT: &str = r#"
window.addEventListener('DOMContentLoaded', () => {
  const s = document.createElement('style');
  s.textContent = 'html,body,#hud{background:transparent !important;}';
  document.head.appendChild(s);
  const drag = document.createElement('div');
  drag.setAttribute('data-tauri-drag-region', '');
  drag.style.cssText = 'position:fixed;inset:0;z-index:2147483647;';
  document.body.appendChild(drag);
});
"#;

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            // 悬浮 HUD 窗口(在 Rust 建以便挂 initialization_script)。
            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Jarvis HUD")
                .inner_size(320.0, 320.0)
                .resizable(false)
                .decorations(false)
                .transparent(true)
                .always_on_top(true)
                .skip_taskbar(true)
                .shadow(false)
                .center()
                .initialization_script(INIT_SCRIPT)
                .build()?;

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
