use std::time::Duration;
use tauri::Manager;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

pub fn check(app: tauri::AppHandle) {
    std::thread::spawn(move || {
        let reachable = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(8))
            .build()
            .and_then(|client| client.head("https://kioku.merigafy.com/").send())
            .is_ok_and(|response| response.status().is_success());
        if !reachable {
            if let Some(window) = app.get_webview_window("main") {
                let retry_window = window.clone();
                app.dialog().message("Kioku could not connect. Check your internet connection and try reloading.")
                    .parent(&window).title("Connection unavailable").kind(MessageDialogKind::Warning)
                    .buttons(MessageDialogButtons::OkCancelCustom("Reload".into(), "Keep Open".into())).show(move |retry| { if retry { let _ = retry_window.reload(); } });
            }
        }
    });
}
