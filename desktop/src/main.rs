#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod updates;

use std::{io::Write, time::Duration};
use tauri::Manager;
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};

fn download(app: tauri::AppHandle, url: tauri::Url) {
    std::thread::spawn(move || {
        let name = url
            .query_pairs()
            .find(|(key, value)| key == "download" && !value.is_empty())
            .map(|(_, value)| value.into_owned())
            .unwrap_or_else(|| {
                url.path_segments()
                    .and_then(|mut s| s.next_back())
                    .unwrap_or("download")
                    .to_owned()
            });
        let decoded = percent_encoding::percent_decode_str(&name).decode_utf8_lossy();
        let filename = std::path::Path::new(decoded.as_ref())
            .file_name()
            .and_then(|s| s.to_str())
            .filter(|s| !s.is_empty())
            .unwrap_or("download");
        let result = (|| -> Result<std::path::PathBuf, Box<dyn std::error::Error>> {
            let parent = app.path().download_dir()?;
            let original = std::path::Path::new(filename);
            let stem = original
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("download");
            let extension = original.extension().and_then(|s| s.to_str());
            let mut destination = parent.join(filename);
            for index in 1..10000 {
                if !destination.exists() {
                    break;
                }
                let suffix = extension.map(|e| format!(".{e}")).unwrap_or_default();
                destination = parent.join(format!("{stem} ({index}){suffix}"));
            }
            let mut file = tempfile::NamedTempFile::new_in(&parent)?;
            let client = reqwest::blocking::Client::builder()
                .timeout(Duration::from_secs(300))
                .redirect(reqwest::redirect::Policy::none())
                .build()?;
            let mut response = client.get(url.as_str()).send()?.error_for_status()?;
            std::io::copy(&mut response, &mut file)?;
            file.flush()?;
            file.persist_noclobber(&destination)?;
            Ok(destination)
        })();
        match result {
            Ok(destination) => {
                app.dialog()
                    .message(format!("Saved to {}", destination.display()))
                    .title("Download complete")
                    .show(|_| {});
            }
            Err(_) => {
                app.dialog().message("The file could not be saved. Check your connection and destination, then try again.")
                .title("Download failed").kind(MessageDialogKind::Error).show(|_| {});
            }
        }
    });
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .menu(|app| {
            let menu = tauri::menu::Menu::default(app)?;
            let reload =
                tauri::menu::MenuItem::with_id(app, "reload", "Reload", true, Some("CmdOrCtrl+R"))?;
            let navigation = tauri::menu::Submenu::with_items(app, "Navigation", true, &[&reload])?;
            menu.append(&navigation)?;
            let updates = tauri::menu::MenuItem::with_id(
                app,
                "updates",
                "Check for Updates…",
                true,
                None::<&str>,
            )?;
            navigation.append(&updates)?;
            Ok(menu)
        })
        .on_menu_event(|app, event| {
            if event.id().as_ref() == "updates" {
                updates::check(app.clone(), true);
            }
            if event.id().as_ref() == "reload" {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.reload();
                }
            }
        })
        .setup(|app| {
            updates::start(app.handle().clone());
            let handle = app.handle().clone();
            let launch = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)?
                .as_millis();
            let url = format!("https://kioku.merigafy.com/?desktop_launch={launch}").parse()?;
            let mut config = app.config().app.windows[0].clone();
            config.url = tauri::WebviewUrl::External(url);
            tauri::WebviewWindowBuilder::from_config(app, &config)?
                .on_new_window(move |url, _| {
                    if url.scheme() == "https"
                        && url.host_str() == Some("xsovdaetdlgtqwesrbse.supabase.co")
                        && url.path().starts_with("/storage/v1/object/sign/")
                    {
                        download(handle.clone(), url);
                    } else if matches!(url.scheme(), "https" | "http") {
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
