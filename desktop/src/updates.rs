use std::{sync::Mutex, time::Duration};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

static NOTIFIED: Mutex<Option<String>> = Mutex::new(None);
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
    std::thread::spawn(move || {
        let result = (|| -> Result<Option<String>, Box<dyn std::error::Error>> {
            let client = reqwest::blocking::Client::builder()
                .timeout(Duration::from_secs(5))
                .user_agent("Kioku-Desktop-Update-Check")
                .build()?;
            let response = client.get(RELEASES).send()?.error_for_status()?.text()?;
            Ok(latest(&response)?)
        })();
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
                app.dialog().message(format!("Kioku {next} is available. You have {}. Open the download page?", env!("CARGO_PKG_VERSION")))
                    .title("Update available").buttons(MessageDialogButtons::OkCancel).show(move |accepted| {
                        if accepted {
                            let _ = std::process::Command::new("/usr/bin/open")
                                .arg(format!("https://github.com/felipemeriga/kioku/releases/tag/desktop-v{next}")).spawn();
                        }
                    });
            }
            Ok(None) if manual => {
                app.dialog()
                    .message("No desktop release is published yet. Try again later.")
                    .title("Kioku updates")
                    .show(|_| {});
            }
            Ok(_) if manual => {
                app.dialog()
                    .message("You are using the latest published desktop version.")
                    .title("Kioku updates")
                    .show(|_| {});
            }
            Err(_) if manual => {
                app.dialog()
                    .message(
                        "Could not check for updates. Check your connection and try again later.",
                    )
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
