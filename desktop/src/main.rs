#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            tauri::WebviewWindowBuilder::from_config(app, &app.config().app.windows[0])?
                .on_new_window(|url, _| {
                    if matches!(url.scheme(), "https" | "http") {
                        let _ = std::process::Command::new("/usr/bin/open")
                            .arg(url.as_str())
                            .spawn();
                    }
                    tauri::webview::NewWindowResponse::Deny
                })
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to launch Kioku");
}
