//! Launch at login: on by default, and the Owner's to turn off.
//!
//! The personal edition's sync lives in this tray. A tray that does not come back after a
//! reboot is a library that quietly stops taking in the world, so the first launch
//! registers the app with the operating system itself instead of waiting to be asked.
//!
//! The mechanism is the record, not the prompt. Any record at all — the app's own default
//! or the Owner's later choice — ends the app's say in the matter, so an Owner who turns
//! login off is never overruled by the next launch. A failure writes nothing, so a refusal
//! today (no permission) is retried tomorrow rather than frozen into a decision nobody made.
use crate::state::{LoginState, Runtime};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};
use tauri::{AppHandle, State};
use tauri_plugin_autostart::ManagerExt;

/// The tray's own preferences, beside the panel's; only the `login` key is read or written,
/// so a preference left here by another hand survives this file being rewritten.
const FILE: &str = "preferences.json";
const KEY: &str = "login";

/// Who decided. `App` is the shipped default; `Owner` is the Settings toggle.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Decider {
    App,
    Owner,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Decision {
    pub enabled: bool,
    pub by: Decider,
    #[serde(default)]
    pub at_ms: u64,
}
impl Decision {
    pub fn new(enabled: bool, by: Decider, at_ms: u64) -> Self {
        Self { enabled, by, at_ms }
    }
}

/// What a launch must do about login registration, given the record and the operating
/// system's own answer. Pure: the whole default lives here.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Startup {
    /// A decision is on record — whoever made it, the app does not decide again.
    Decided,
    /// Nothing on record and the system already launches us: record it, call nothing.
    Adopt,
    /// Nothing on record: register, then record that the app did it.
    Register,
}
pub fn startup(recorded: Option<&Decision>, registered: bool) -> Startup {
    match (recorded, registered) {
        (Some(_), _) => Startup::Decided,
        (None, true) => Startup::Adopt,
        (None, false) => Startup::Register,
    }
}

fn file(dir: &Path) -> PathBuf {
    dir.join(FILE)
}
fn document(dir: &Path) -> Map<String, Value> {
    std::fs::read_to_string(file(dir))
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .and_then(|value| match value {
            Value::Object(map) => Some(map),
            _ => None,
        })
        .unwrap_or_default()
}
/// The decision on record, or `None` when the file is absent, unreadable or says nothing
/// about login. An unreadable file is not a decision: the default applies again.
pub fn read(dir: &Path) -> Option<Decision> {
    serde_json::from_value(document(dir).get(KEY)?.clone()).ok()
}
pub fn write(dir: &Path, decision: &Decision) -> Result<(), String> {
    let mut preferences = document(dir);
    preferences.insert(
        KEY.into(),
        serde_json::to_value(decision).map_err(|e| e.to_string())?,
    );
    std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    let text =
        serde_json::to_string_pretty(&Value::Object(preferences)).map_err(|e| e.to_string())?;
    std::fs::write(file(dir), text + "\n").map_err(|e| e.to_string())
}

fn registered(app: &AppHandle) -> bool {
    app.autolaunch().is_enabled().unwrap_or(false)
}

/// Run once in the setup hook, before the webview exists. Idempotent: on every launch after
/// the first, the record is already there and this touches neither the system nor the file.
pub fn settle(app: &AppHandle, dir: &Path, now_ms: u64) -> LoginState {
    let recorded = read(dir);
    let already = registered(app);
    match startup(recorded.as_ref(), already) {
        Startup::Decided => LoginState {
            enabled: already,
            error: None,
        },
        Startup::Adopt => {
            let _ = write(dir, &Decision::new(true, Decider::App, now_ms));
            LoginState {
                enabled: true,
                error: None,
            }
        }
        Startup::Register => match app.autolaunch().enable() {
            Ok(()) => {
                let _ = write(dir, &Decision::new(true, Decider::App, now_ms));
                LoginState {
                    // The system's own answer, not the call's optimism.
                    enabled: registered(app),
                    error: None,
                }
            }
            // No record: a refusal is not the Owner's decision, and the next launch tries
            // again. The pane says the toggle is off and why, rather than a silent success.
            Err(error) => LoginState {
                enabled: false,
                error: Some(error.to_string()),
            },
        },
    }
}

#[tauri::command]
pub fn login_status(app: AppHandle, runtime: State<'_, Runtime>) -> LoginState {
    let error = runtime.login.read().unwrap().error.clone();
    LoginState {
        enabled: registered(&app),
        error,
    }
}
/// The Owner's own decision, which outranks the default for good.
///
/// It answers with what the system does afterwards, refusal and all, rather than failing:
/// a refused call is a fact the pane must keep showing, not a toast that fades. Only a call
/// the system honoured is recorded, so a refusal leaves no decision in the Owner's name.
#[tauri::command]
pub fn set_login(app: AppHandle, runtime: State<'_, Runtime>, enabled: bool) -> LoginState {
    let manager = app.autolaunch();
    let outcome = if enabled {
        manager.enable()
    } else {
        manager.disable()
    };
    let state = LoginState {
        enabled: registered(&app),
        error: outcome.err().map(|error| error.to_string()),
    };
    if state.error.is_none() {
        let _ = write(
            &runtime.preferences,
            &Decision::new(state.enabled, Decider::Owner, crate::poller::now_ms()),
        );
    }
    *runtime.login.write().unwrap() = state.clone();
    state
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp() -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "pkc-login-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        dir
    }

    #[test]
    fn the_first_launch_decides_and_no_later_launch_decides_again() {
        assert_eq!(startup(None, false), Startup::Register);
        assert_eq!(startup(None, true), Startup::Adopt);
        // The Owner's off is a decision, and so is the app's own default: neither is
        // re-made, so nothing the app does can turn login back on.
        let off = Decision::new(false, Decider::Owner, 1);
        assert_eq!(startup(Some(&off), false), Startup::Decided);
        let on = Decision::new(true, Decider::App, 1);
        assert_eq!(startup(Some(&on), true), Startup::Decided);
        assert_eq!(startup(Some(&on), false), Startup::Decided);
    }

    #[test]
    fn the_decision_survives_beside_preferences_this_file_does_not_own() {
        let dir = temp();
        assert_eq!(read(&dir), None);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(file(&dir), r#"{"synthetic": {"kept": true}}"#).unwrap();
        assert_eq!(read(&dir), None);
        let decision = Decision::new(false, Decider::Owner, 1_700_000_000_000);
        write(&dir, &decision).unwrap();
        assert_eq!(read(&dir), Some(decision));
        let document = document(&dir);
        assert_eq!(
            document.get("synthetic"),
            Some(&serde_json::json!({"kept": true}))
        );
        // A damaged file is not a decision; the shipped default applies again.
        std::fs::write(file(&dir), "not json").unwrap();
        assert_eq!(read(&dir), None);
        assert_eq!(startup(read(&dir).as_ref(), false), Startup::Register);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
