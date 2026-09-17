//! The tray's entry to the voice call (docs/design/voice-call.md).
//!
//! The call lives in the console's Steward view, and this item opens it THERE, in the
//! Owner's own browser, rather than inside the panel. Three facts decide that, and none of
//! them is taste: the panel's content security policy reaches `ipc:` and nothing else, so
//! it can open neither the engine's loopback port nor the provider's socket; this bundle
//! declares no microphone purpose, so macOS would kill a webview that asked for one; and
//! the panel is a 380-point popover that hides the moment it loses focus, which is no place
//! to hold a conversation.
use crate::{panel, poller, state::Runtime};
use serde::Deserialize;
use tauri::Manager;
use tauri_plugin_shell::ShellExt;

/// The console address that arms a call.
///
/// `call=1` sits INSIDE the hash because the console routes on the hash and reads it there
/// as a view parameter, not as a selection. Arming is all the address does: a call bills by
/// the minute, so an address may set the page up and may never start one.
pub fn call_url(port: u16) -> String {
    format!("http://127.0.0.1:{port}/#/steward?call=1")
}

/// The engine's answer to whether a call can be placed here, and the one thing missing.
#[derive(Deserialize)]
struct CallStatus {
    #[serde(default)]
    configured: bool,
    #[serde(default)]
    detail: String,
}

/// Ask the library itself, rather than guessing from what the tray can see. The call needs a
/// provider key and a usable recall model, and neither is visible on disk from here.
async fn placeable(client: &reqwest::Client, port: u16, tenant: &str) -> Result<(), String> {
    let response = client
        .get(format!("http://127.0.0.1:{port}/v1/users/{tenant}/call"))
        .send()
        .await
        .map_err(|_| "Could not ask the engine whether it can place a call".to_string())?;
    // An engine built before the call answers 404. It cannot place one either, and saying
    // so names the upgrade instead of leaving the Owner on a console page with no button.
    if response.status() == reqwest::StatusCode::NOT_FOUND {
        return Err("This engine is older than the voice call; update it and restart.".into());
    }
    let status: CallStatus = response
        .error_for_status()
        .map_err(|e| format!("The engine refused the call check: {e}"))?
        .json()
        .await
        .map_err(|_| "Engine returned an invalid call document".to_string())?;
    if status.configured {
        Ok(())
    } else if status.detail.is_empty() {
        Err("This library cannot place a call yet.".into())
    } else {
        // The engine's own words for the one thing missing (no provider key, no model).
        Err(status.detail)
    }
}

async fn place(app: &tauri::AppHandle) -> Result<(), String> {
    let runtime = app.state::<Runtime>();
    // Port and tenant are read from disk at the moment of the click, never from the cached
    // snapshot: the library the Owner last switched to is the one they mean to call.
    let shallow = poller::shallow(&runtime.home, &runtime.login_path).await;
    let library = shallow
        .libraries
        .iter()
        .find(|l| l.status.current)
        .ok_or("Choose the current library in Settings before calling it.")?;
    if !library.status.engine.up {
        return Err("The engine is down. Start it from Dashboard.".into());
    }
    placeable(&runtime.client, library.status.engine.port, &library.tenant).await?;
    // The shell plugin's `open` is deprecated in favour of tauri-plugin-opener. This bundle
    // already ships the shell plugin and the panel's own console links go through it, so the
    // tray uses the same door rather than adding a second plugin for one menu item.
    #[allow(deprecated)]
    let opened = app.shell().open(call_url(library.status.engine.port), None);
    opened.map_err(|e| format!("Could not open your browser: {e}"))
}

/// The tray item's whole behaviour. A menu event is handled synchronously and every fact
/// this needs is on disk or on the engine, so the work goes to the same async runtime the
/// poller already runs on and the click returns immediately, as every menu item must.
pub fn request(app: &tauri::AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(reason) = place(&app).await {
            // The tray has no notification of its own, so the panel says it: opened on the
            // Dashboard, where the engine's state is, with the reason on its message line.
            // A menu item that did nothing would leave the Owner with nothing to fix.
            panel::open_with_notice(&app, Some("dashboard"), Some(reason));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_address_arms_the_call_on_the_librarys_own_loopback_port() {
        // The console's shipped shell scope (`tauri.conf.json`) admits this address: the
        // hash and its parameter fall inside the trailing `(/.*)?` after the port.
        assert_eq!(call_url(43022), "http://127.0.0.1:43022/#/steward?call=1");
    }

    #[test]
    fn a_library_that_cannot_call_is_refused_in_the_engines_own_words() {
        let status: CallStatus = serde_json::from_value(serde_json::json!({
            "configured": false, "reason": "no_openai_key",
            "detail": "A voice call needs OPENAI_API_KEY; none is configured.",
            "model": "synthetic-voice", "voice": "synthetic", "live": false,
        }))
        .unwrap();
        assert!(!status.configured);
        assert_eq!(
            status.detail,
            "A voice call needs OPENAI_API_KEY; none is configured."
        );
        // An older engine names neither field; the tray must still read the document.
        let older: CallStatus = serde_json::from_value(serde_json::json!({})).unwrap();
        assert!(!older.configured);
        assert!(older.detail.is_empty());
    }
}
