#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod connection;
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
        let Some(window) = app.get_webview_window("main") else {
            return;
        };
        match result {
            Ok(destination) => {
                app.dialog()
                    .message(format!("Saved to {}", destination.display()))
                    .parent(&window)
                    .title("Download complete")
                    .show(|_| {});
            }
            Err(_) => {
                app.dialog().message("The file could not be saved. Check your connection and destination, then try again.")
                .parent(&window).title("Download failed").kind(MessageDialogKind::Error).show(|_| {});
            }
        }
    });
}

fn active_window(app: &tauri::AppHandle) -> Option<tauri::WebviewWindow> {
    app.webview_windows()
        .into_values()
        .find(|window| window.label() != "update-progress" && window.is_focused().unwrap_or(false))
        .or_else(|| app.get_webview_window("main"))
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(
                    tauri_plugin_window_state::StateFlags::SIZE
                        | tauri_plugin_window_state::StateFlags::POSITION
                        | tauri_plugin_window_state::StateFlags::MAXIMIZED,
                )
                .build(),
        )
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
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
            for (id, title, shortcut) in [
                ("back", "Back", "CmdOrCtrl+["),
                ("forward", "Forward", "CmdOrCtrl+]"),
                ("chat", "Chat", "CmdOrCtrl+1"),
                ("documents", "Documents", "CmdOrCtrl+2"),
            ] {
                navigation.append(&tauri::menu::MenuItem::with_id(
                    app,
                    id,
                    title,
                    true,
                    Some(shortcut),
                )?)?;
            }
            Ok(menu)
        })
        .on_window_event(|window, event| {
            if window.label() == "update-progress" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event { api.prevent_close(); }
            }
            if window.label() == "main" {
                if let tauri::WindowEvent::Focused(_) = event {
                    if let Some(webview) = window.app_handle().get_webview_window("main") {
                        let _ = webview.eval("window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange'))");
                    }
                }
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .on_menu_event(|app, event| {
            if let Some(window) = active_window(app) {
                match event.id().as_ref() {
                    "back" => {
                        let _ = window.eval("history.back()");
                    }
                    "forward" => {
                        let _ = window.eval("history.forward()");
                    }
                    "chat" => {
                        let _ = window.navigate("https://kioku.merigafy.com/".parse().unwrap());
                    }
                    "documents" => {
                        let _ = window
                            .navigate("https://kioku.merigafy.com/documents".parse().unwrap());
                    }
                    _ => {}
                }
            }
            if event.id().as_ref() == "updates" {
                updates::check(app.clone(), true);
            }
            if event.id().as_ref() == "reload" {
                if let Some(window) = active_window(app) {
                    let _ = window.reload();
                }
            }
        })
        .setup(|app| {
            let handle = app.handle().clone();
            let launch = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)?
                .as_millis();
            let url = format!("https://kioku.merigafy.com/?desktop_launch={launch}").parse()?;
            let mut config = app.config().app.windows[0].clone();
            config.url = tauri::WebviewUrl::External(url);
            tauri::WebviewWindowBuilder::from_config(app, &config)?
                .initialization_script(include_str!("window.js"))
                .on_navigation(|url| {
                    if url.as_str() == "about:blank" || (url.scheme() == "https" && url.host_str() == Some("kioku.merigafy.com")) {
                        return true;
                    }
                    if matches!(url.scheme(), "https" | "http") {
                        let _ = std::process::Command::new("/usr/bin/open")
                            .arg(url.as_str())
                            .spawn();
                    }
                    false
                })
                .on_new_window(move |url, features| {
                    if url.scheme() == "https" && url.host_str() == Some("kioku.merigafy.com") {
                        static NEXT_WINDOW: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
                        let label = format!("source-{}", NEXT_WINDOW.fetch_add(1, std::sync::atomic::Ordering::Relaxed));
                        let created = tauri::WebviewWindowBuilder::new(&handle, label, tauri::WebviewUrl::External("about:blank".parse().unwrap()))
                            .window_features(features).title("Kioku — Source").inner_size(1100.0, 800.0)
                            .on_navigation(|url| {
                                if url.as_str() == "about:blank" || (url.scheme() == "https" && url.host_str() == Some("kioku.merigafy.com")) { return true; }
                                if matches!(url.scheme(), "https" | "http") { let _ = std::process::Command::new("/usr/bin/open").arg(url.as_str()).spawn(); }
                                false
                            }).build();
                        return match created { Ok(window) => tauri::webview::NewWindowResponse::Create { window }, Err(_) => tauri::webview::NewWindowResponse::Deny };
                    }
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
            connection::check(app.handle().clone());
            updates::start(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to launch Kioku")
        .run(|app, event| {
            if let tauri::RunEvent::Reopen { .. } = event {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
        });
}
