use std::{
    collections::HashMap,
    io::Write,
    path::{Path, PathBuf},
    sync::{LazyLock, Mutex},
};
use tauri::{webview::DownloadEvent, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};

struct Pending {
    directory: tempfile::TempDir,
    name: PathBuf,
}
// macOS completion events contain the URL but no destination path.
static PENDING: LazyLock<Mutex<HashMap<String, Pending>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

fn trusted(url: &tauri::Url) -> bool {
    url.as_str().starts_with("blob:https://kioku.merigafy.com/")
        || (url.scheme() == "https"
            && url.host_str() == Some("xsovdaetdlgtqwesrbse.supabase.co")
            && url.path().starts_with("/storage/v1/object/sign/"))
}

fn save(source: &Path, root: &Path, proposed: &Path) -> std::io::Result<PathBuf> {
    let name = proposed
        .file_name()
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| std::ffi::OsStr::new("download"));
    let original = Path::new(name);
    let stem = original.file_stem().unwrap_or(name).to_string_lossy();
    let extension = original
        .extension()
        .map(|ext| format!(".{}", ext.to_string_lossy()))
        .unwrap_or_default();
    let mut file = tempfile::NamedTempFile::new_in(root)?;
    std::io::copy(&mut std::fs::File::open(source)?, &mut file)?;
    file.flush()?;
    for index in 0..10000 {
        let path = if index == 0 {
            root.join(name)
        } else {
            root.join(format!("{stem} ({index}){extension}"))
        };
        match file.persist_noclobber(&path) {
            Ok(_) => return Ok(path),
            Err(error) if error.error.kind() == std::io::ErrorKind::AlreadyExists => {
                file = error.file
            }
            Err(error) => return Err(error.error),
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::AlreadyExists,
        "No available download filename",
    ))
}

fn notice(app: &tauri::AppHandle, result: std::io::Result<PathBuf>) {
    if let Some(window) = app.get_webview_window("main") {
        let (message, title, kind) = match result {
            Ok(path) => (format!("Saved to {}", path.display()), "Download complete", MessageDialogKind::Info),
            Err(_) => ("The file could not be saved. Check your connection and destination, then try again.".to_owned(), "Download failed", MessageDialogKind::Error),
        };
        app.dialog()
            .message(message)
            .parent(&window)
            .title(title)
            .kind(kind)
            .show(|_| {});
    }
}

pub fn handle(webview: tauri::Webview, event: DownloadEvent<'_>) -> bool {
    match event {
        DownloadEvent::Requested { url, destination } => {
            if !trusted(&url) {
                return false;
            }
            // Keep WebKit away from protected user folders. Rust publishes the
            // finished file into Downloads on a worker, without overwriting anything.
            let prepared = (|| -> Option<PathBuf> {
                let directory = tempfile::Builder::new()
                    .prefix("kioku-download-")
                    .tempdir()
                    .ok()?;
                let path = directory.path().join("download");
                let name = destination
                    .file_name()
                    .map(PathBuf::from)
                    .unwrap_or_else(|| "download".into());
                let mut pending = PENDING.lock().ok()?;
                if pending.contains_key(url.as_str()) {
                    return None;
                }
                pending.insert(url.to_string(), Pending { directory, name });
                Some(path)
            })();
            if let Some(path) = prepared {
                *destination = path;
                true
            } else {
                let app = webview.app_handle().clone();
                std::thread::spawn(move || {
                    notice(
                        &app,
                        Err(std::io::Error::other("Could not prepare download")),
                    )
                });
                false
            }
        }
        DownloadEvent::Finished { url, success, .. } => {
            let pending = PENDING
                .lock()
                .ok()
                .and_then(|mut pending| pending.remove(url.as_str()));
            if let Some(pending) = pending {
                let app = webview.app_handle().clone();
                std::thread::spawn(move || {
                    let result = if success {
                        app.path()
                            .download_dir()
                            .map_err(std::io::Error::other)
                            .and_then(|root| {
                                save(
                                    &pending.directory.path().join("download"),
                                    &root,
                                    &pending.name,
                                )
                            })
                    } else {
                        Err(std::io::Error::other("WebKit download failed"))
                    };
                    notice(&app, result);
                });
            }
            true
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_untrusted_download_origins() {
        assert!(trusted(
            &"blob:https://kioku.merigafy.com/record".parse().unwrap()
        ));
        for value in [
            "blob:http://kioku.merigafy.com/record",
            "blob:https://kioku.merigafy.com.evil.example/record",
            "https://evil.example/record",
            "file:///etc/passwd",
        ] {
            assert!(!trusted(&value.parse().unwrap()));
        }
    }
    #[test]
    fn publishes_with_safe_names_without_overwriting_existing_files() {
        let dir = tempfile::tempdir().unwrap();
        let source = dir.path().join("source");
        std::fs::write(&source, "new evidence").unwrap();
        let root = dir.path().join("Downloads");
        std::fs::create_dir(&root).unwrap();
        std::fs::write(root.join("record.jsonl"), "existing evidence").unwrap();
        assert_eq!(
            save(&source, &root, Path::new("record.jsonl")).unwrap(),
            root.join("record (1).jsonl")
        );
        assert_eq!(
            save(&source, &root, Path::new("record.jsonl")).unwrap(),
            root.join("record (2).jsonl")
        );
        assert_eq!(
            std::fs::read_to_string(root.join("record.jsonl")).unwrap(),
            "existing evidence"
        );
        assert_eq!(
            std::fs::read_to_string(root.join("record (1).jsonl")).unwrap(),
            "new evidence"
        );
        assert_eq!(
            save(&source, &root, Path::new("../../outside.txt")).unwrap(),
            root.join("outside.txt")
        );
        let outside = dir.path().join("outside");
        std::fs::write(&outside, "preserve").unwrap();
        std::os::unix::fs::symlink(&outside, root.join("link.txt")).unwrap();
        assert_eq!(
            save(&source, &root, Path::new("link.txt")).unwrap(),
            root.join("link (1).txt")
        );
        assert_eq!(std::fs::read_to_string(outside).unwrap(), "preserve");
    }
}
