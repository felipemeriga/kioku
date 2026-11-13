use std::{
    collections::HashSet,
    path::{Path, PathBuf},
    sync::{LazyLock, Mutex},
};
use tauri::{webview::DownloadEvent, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};

// Reserve names until exit: macOS does not report the completed download path.
// Keeping failed names reserved also prevents concurrent downloads from sharing a file.
static RESERVED: LazyLock<Mutex<HashSet<PathBuf>>> = LazyLock::new(|| Mutex::new(HashSet::new()));

fn trusted(url: &tauri::Url) -> bool {
    url.as_str().starts_with("blob:https://kioku.merigafy.com/")
        || (url.scheme() == "https"
            && url.host_str() == Some("xsovdaetdlgtqwesrbse.supabase.co")
            && url.path().starts_with("/storage/v1/object/sign/"))
}

fn destination(root: &Path, proposed: &Path, reserved: &mut HashSet<PathBuf>) -> Option<PathBuf> {
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
    for index in 0..10000 {
        let candidate = if index == 0 {
            root.join(name)
        } else {
            root.join(format!("{stem} ({index}){extension}"))
        };
        if candidate.symlink_metadata().is_err() && reserved.insert(candidate.clone()) {
            return Some(candidate);
        }
    }
    None
}

fn notice(app: &tauri::AppHandle, success: bool) {
    if let Some(window) = app.get_webview_window("main") {
        app.dialog().message(if success { "Saved to your Downloads folder." } else { "The file could not be saved. Check your connection and destination, then try again." })
            .parent(&window).title(if success { "Download complete" } else { "Download failed" })
            .kind(if success { MessageDialogKind::Info } else { MessageDialogKind::Error }).show(|_| {});
    }
}

pub fn handle(webview: tauri::Webview, event: DownloadEvent<'_>) -> bool {
    match event {
        DownloadEvent::Requested {
            url,
            destination: output,
        } => {
            if !trusted(&url) {
                return false;
            }
            let chosen = webview
                .app_handle()
                .path()
                .download_dir()
                .ok()
                .and_then(|root| {
                    let mut names = RESERVED.lock().ok()?;
                    destination(&root, output, &mut names)
                });
            if let Some(path) = chosen {
                *output = path;
                true
            } else {
                notice(webview.app_handle(), false);
                false
            }
        }
        DownloadEvent::Finished { success, .. } => {
            notice(webview.app_handle(), success);
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
    fn preserves_original_names_and_never_reuses_existing_or_reserved_paths() {
        let dir = tempfile::tempdir().unwrap();
        let mut names = HashSet::new();
        std::fs::write(dir.path().join("record.jsonl"), "existing evidence").unwrap();
        assert_eq!(
            destination(dir.path(), Path::new("record.jsonl"), &mut names).unwrap(),
            dir.path().join("record (1).jsonl")
        );
        assert_eq!(
            destination(dir.path(), Path::new("record.jsonl"), &mut names).unwrap(),
            dir.path().join("record (2).jsonl")
        );
        assert_eq!(
            std::fs::read_to_string(dir.path().join("record.jsonl")).unwrap(),
            "existing evidence"
        );
        assert_eq!(
            destination(dir.path(), Path::new("../../outside.txt"), &mut names).unwrap(),
            dir.path().join("outside.txt")
        );
    }
}
