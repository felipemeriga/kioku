use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::Duration,
};
use tauri::Manager;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

static NOTIFIED: Mutex<Option<String>> = Mutex::new(None);
static BUSY: AtomicBool = AtomicBool::new(false);
struct BusyGuard;
impl Drop for BusyGuard {
    fn drop(&mut self) {
        BUSY.store(false, Ordering::SeqCst);
    }
}

const RELEASES: &str = "https://api.github.com/repos/felipemeriga/kioku/releases?per_page=100";

fn version(value: &str) -> Option<[u64; 3]> {
    let parts: Vec<_> = value.split('.').collect();
    if parts.len() != 3
        || parts
            .iter()
            .any(|p| p.is_empty() || !p.bytes().all(|b| b.is_ascii_digit()))
    {
        return None;
    }
    Some([
        parts[0].parse().ok()?,
        parts[1].parse().ok()?,
        parts[2].parse().ok()?,
    ])
}

fn latest(body: &str) -> Result<Option<String>, serde_json::Error> {
    let releases: Vec<serde_json::Value> = serde_json::from_str(body)?;
    Ok(releases
        .iter()
        .filter(|r| r["draft"] == false && r["prerelease"] == false)
        .filter_map(|r| r["tag_name"].as_str()?.strip_prefix("desktop-v"))
        .filter_map(|v| Some((version(v)?, v.to_owned())))
        .max_by_key(|(v, _)| *v)
        .map(|(_, v)| v))
}

pub fn check(app: tauri::AppHandle, manual: bool) {
    if BUSY.swap(true, Ordering::SeqCst) {
        return;
    }
    std::thread::spawn(move || {
        let _busy = BusyGuard;
        let result = (|| -> Result<Option<String>, Box<dyn std::error::Error>> {
            let client = reqwest::blocking::Client::builder()
                .timeout(Duration::from_secs(5))
                .user_agent("Kioku-Desktop-Update-Check")
                .build()?;
            let response = client.get(RELEASES).send()?.error_for_status()?.text()?;
            Ok(latest(&response)?)
        })();
        let Some(window) = app.get_webview_window("main") else {
            return;
        };
        if manual {
            let _ = window.show();
            let _ = window.set_focus();
        }
        match result {
            Ok(Some(next)) if version(&next) > version(env!("CARGO_PKG_VERSION")) => {
                let Ok(mut notified) = NOTIFIED.lock() else {
                    return;
                };
                if !manual && notified.as_deref() == Some(next.as_str()) {
                    return;
                }
                *notified = Some(next.clone());
                drop(notified);
                let accepted = app.dialog().message(format!("Kioku {next} is available. Install the update and restart now? Finish any work in progress first."))
                    .parent(&window).title("Update available").buttons(MessageDialogButtons::OkCancelCustom("Install and Restart".into(), "Later".into())).blocking_show();
                if !accepted {
                    return;
                }
                let html = "<html><meta name='color-scheme' content='dark'><body style='margin:0;background:#0c0914;color:#eee;font:16px system-ui;padding:28px'><h2 style='color:#ff1493'>Updating Kioku</h2><p id='progress'>Preparing signed update…</p><p style='color:#aaa;font-size:13px'>Kioku will restart when installation finishes.</p></body></html>";
                let page = format!(
                    "data:text/html,{}",
                    percent_encoding::utf8_percent_encode(html, percent_encoding::NON_ALPHANUMERIC)
                );
                let progress = match tauri::WebviewWindowBuilder::new(
                    &app,
                    "update-progress",
                    tauri::WebviewUrl::External(page.parse().unwrap()),
                )
                .title("Updating Kioku")
                .inner_size(460.0, 220.0)
                .resizable(false)
                .closable(false)
                .minimizable(false)
                .build()
                {
                    Ok(progress) => progress,
                    Err(error) => {
                        eprintln!("Could not create update progress window: {error}");
                        app.dialog()
                            .message("Could not open the update window. Please try again.")
                            .parent(&window)
                            .show(|_| {});
                        return;
                    }
                };
                let installed = tauri::async_runtime::block_on(async {
                    let endpoint = format!("https://github.com/felipemeriga/kioku/releases/download/desktop-v{next}/latest.json").parse().unwrap();
                    let updater = app
                        .updater_builder()
                        .endpoints(vec![endpoint])?
                        .timeout(Duration::from_secs(120))
                        .build()?;
                    if let Some(update) = updater.check().await? {
                        if update.version != next {
                            return Err(tauri_plugin_updater::Error::Io(std::io::Error::other(
                                "Unexpected update version",
                            )));
                        }
                        let mut received = 0u64;
                        let mut last_progress = String::new();
                        update.download_and_install(|chunk, total| {
                            received += chunk as u64;
                            let message = total.filter(|n| *n > 0).map(|n| format!("Downloading… {}%", (received * 100 / n).min(100)))
                                .unwrap_or_else(|| format!("Downloading… {} KiB", received / 1024));
                            if message == last_progress { return; }
                            last_progress.clone_from(&message);
                            let _ = progress.eval(format!("document.getElementById('progress').textContent = {}", serde_json::to_string(&message).unwrap()));
                        }, || { let _ = progress.eval("document.getElementById('progress').textContent = 'Verifying signature and installing…'"); }).await?;
                        Ok(true)
                    } else {
                        Ok(false)
                    }
                });
                let _ = progress.destroy();
                match installed {
                    Ok(true) => app.restart(),
                    Ok(false) => {
                        app.dialog()
                            .message("The update is no longer available. Try checking again later.")
                            .parent(&window)
                            .show(|_| {});
                    }
                    Err(error) => {
                        eprintln!("Desktop update failed: {error}");
                        app.dialog().message("The update could not be verified or installed. Please try again later.").parent(&window).title("Update failed").kind(MessageDialogKind::Error).show(|_| {});
                    }
                }
            }
            Ok(None) if manual => {
                app.dialog()
                    .message("No desktop release is published yet. Try again later.")
                    .parent(&window)
                    .title("Kioku updates")
                    .show(|_| {});
            }
            Ok(_) if manual => {
                app.dialog()
                    .message("You are using the latest published desktop version.")
                    .parent(&window)
                    .title("Kioku updates")
                    .show(|_| {});
            }
            Err(_) if manual => {
                app.dialog()
                    .message(
                        "Could not check for updates. Check your connection and try again later.",
                    )
                    .parent(&window)
                    .title("Update check unavailable")
                    .kind(MessageDialogKind::Warning)
                    .show(|_| {});
            }
            _ => {}
        }
    });
}

pub fn start(app: tauri::AppHandle) {
    check(app.clone(), false);
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_secs(6 * 60 * 60));
        check(app.clone(), false);
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn selects_only_published_desktop_versions_in_semantic_order() {
        let body = r#"[
          {"tag_name":"cli-v99.0.0","draft":false,"prerelease":false},
          {"tag_name":"desktop-v0.2.0","draft":false,"prerelease":false},
          {"tag_name":"desktop-v0.10.0","draft":false,"prerelease":false},
          {"tag_name":"desktop-v9.0.0","draft":true,"prerelease":false},
          {"tag_name":"desktop-v8.0.0","draft":false,"prerelease":true},
          {"tag_name":"desktop-v../bad","draft":false,"prerelease":false}
        ]"#;
        assert_eq!(latest(body).unwrap().as_deref(), Some("0.10.0"));
        assert!(latest("{}").is_err());
        assert_eq!(latest("[]").unwrap(), None);
    }
}
