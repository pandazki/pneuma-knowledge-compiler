//! All home mutations go through a closed vocabulary of pkchome subprocesses.
use crate::{poller, state::Runtime};
use serde::Deserialize;
use std::{path::PathBuf, process::Stdio, time::Duration};
use tauri::{Manager, State};
use tokio::{io::AsyncWriteExt, process::Command, time::timeout};

pub async fn login_path() -> String {
    let fallback = std::env::var("PATH").unwrap_or_default();
    #[cfg(target_os = "macos")]
    {
        let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/zsh".into());
        // Constant script, never interpolates input. Resolved once, not every poll.
        let result = timeout(
            Duration::from_secs(3),
            Command::new(shell)
                .args(["-lc", "echo \"$PATH\""])
                .stdin(Stdio::null())
                .kill_on_drop(true)
                .output(),
        )
        .await;
        if let Ok(Ok(out)) = result {
            if out.status.success() {
                if let Some(path) = String::from_utf8_lossy(&out.stdout)
                    .lines()
                    .rev()
                    .find(|l| l.starts_with('/'))
                {
                    return path.to_owned();
                }
            }
        }
    }
    fallback
}
#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Action {
    Up,
    Down,
    Restart,
    UseLibrary { library: String },
    SemanticRetrieval { library: String, enabled: bool },
    Unattended { library: String, enabled: bool },
    Backend { library: String, backend: String },
    Credential { key: String, value: String },
    Sync { library: String },
    SyncInterval { minutes: u64 },
    SyncEnabled { enabled: bool },
    WatchAdd { library: String, path: String },
    WatchRemove { library: String, path: String },
}
fn name(value: &str) -> Result<(), String> {
    if poller::valid_name(value) {
        Ok(())
    } else {
        Err("Invalid library name".into())
    }
}
pub fn arguments(action: &Action) -> Result<(Vec<String>, Option<&str>), String> {
    let args: Vec<String> = match action {
        Action::Up => vec!["up".into()],
        Action::Down => vec!["down".into()],
        Action::Restart => vec!["restart".into()],
        Action::Sync { library } => {
            name(library)?;
            vec![
                "sync".into(),
                "--library".into(),
                library.clone(),
                "--json".into(),
            ]
        }
        Action::SyncInterval { minutes } => {
            if *minutes == 0 {
                return Err("Sync interval must be at least one minute".into());
            }
            vec![
                "config".into(),
                "set".into(),
                "sync.interval_minutes".into(),
                minutes.to_string(),
            ]
        }
        Action::SyncEnabled { enabled } => vec![
            "config".into(),
            "set".into(),
            "sync.enabled".into(),
            if *enabled { "on" } else { "off" }.into(),
        ],
        Action::WatchAdd { library, path } | Action::WatchRemove { library, path } => {
            name(library)?;
            if path.trim().is_empty()
                || path.contains('\0')
                || !(path.starts_with('/') || path.starts_with("~/"))
            {
                return Err("Enter an absolute directory path or a path starting with ~/".into());
            }
            vec![
                "watch".into(),
                if matches!(action, Action::WatchAdd { .. }) {
                    "add"
                } else {
                    "rm"
                }
                .into(),
                path.clone(),
                "--library".into(),
                library.clone(),
            ]
        }
        Action::UseLibrary { library } => {
            name(library)?;
            vec!["library".into(), "use".into(), library.clone()]
        }
        Action::SemanticRetrieval { library, enabled } => {
            name(library)?;
            vec![
                "config".into(),
                "set".into(),
                "semantic_retrieval".into(),
                if *enabled { "on" } else { "off" }.into(),
                "--library".into(),
                library.clone(),
            ]
        }
        Action::Unattended { library, enabled } => {
            name(library)?;
            vec![
                "config".into(),
                "set".into(),
                "unattended".into(),
                if *enabled { "on" } else { "off" }.into(),
                "--library".into(),
                library.clone(),
            ]
        }
        Action::Backend { library, backend } => {
            name(library)?;
            if !["codex", "claude-code", "api"].contains(&backend.as_str()) {
                return Err("Invalid backend".into());
            }
            vec![
                "config".into(),
                "set".into(),
                "backend".into(),
                backend.clone(),
                "--library".into(),
                library.clone(),
            ]
        }
        Action::Credential { key, value } => {
            if key.is_empty()
                || !key.as_bytes()[0].is_ascii_uppercase()
                || !key
                    .bytes()
                    .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == b'_')
            {
                return Err("Credential name must match [A-Z][A-Z0-9_]*".into());
            }
            if value.trim().is_empty() || value.len() > 16384 || value.contains(['\r', '\n', '\0'])
            {
                return Err("Enter a non-empty, single-line key (at most 16 KiB)".into());
            }
            return Ok((
                vec![
                    "credentials".into(),
                    "set".into(),
                    key.clone(),
                    "--from-stdin".into(),
                ],
                Some(value),
            ));
        }
    };
    Ok((args, None))
}
async fn executable(runtime: &Runtime) -> Result<PathBuf, String> {
    let installed = poller::config(&runtime.home).await?.install.pkchome;
    if installed.trim().is_empty() {
        return Ok(PathBuf::from("pkchome"));
    }
    if let Some(rest) = installed.strip_prefix("~/") {
        return Ok(dirs::home_dir()
            .ok_or("Cannot locate your home directory")?
            .join(rest));
    }
    let path = PathBuf::from(installed);
    // Do not interpret relative install paths against the app bundle's launch directory.
    if path.is_absolute() || path.components().count() == 1 {
        Ok(path)
    } else {
        Err("install.pkchome must be an absolute path or a command on PATH".into())
    }
}
/// The tool's own words, with the submitted credential mechanically removed.
///
/// A provider's refusal is worth showing — `401 Unauthorized` is the difference between
/// "try again" and "you pasted the wrong thing" — but it may quote back what it was given.
/// Scrubbing here, at the one place a credential action's output leaves the process, is
/// what lets the window show the reason instead of a generic line.
fn error_output(stderr: &[u8], stdout: &[u8], secret: Option<&str>, fallback: String) -> String {
    let mut text = String::from_utf8_lossy(stderr).trim().to_owned();
    if text.is_empty() {
        text = String::from_utf8_lossy(stdout).trim().to_owned();
    }
    if let Some(secret) = secret {
        // The tool trims what it reads on stdin, so both forms can appear in its output.
        // The untrimmed value first: it contains the trimmed one.
        for form in [secret, secret.trim()] {
            if !form.is_empty() {
                text = text.replace(form, "\u{2022}\u{2022}\u{2022}");
            }
        }
    }
    if text.is_empty() {
        fallback
    } else {
        text.chars().take(4000).collect()
    }
}
#[tauri::command]
pub async fn run_action(runtime: State<'_, Runtime>, action: Action) -> Result<(), String> {
    let (args, secret) = arguments(&action)?;
    let _guard = runtime.action_lock.lock().await;
    if let Action::Sync { library } = &action {
        let result = poller::sync_now(&runtime, library).await;
        runtime.wake.notify_one();
        return result;
    }
    let mut command = Command::new(executable(&runtime).await?);
    command
        .args(args)
        .env("PATH", &runtime.login_path)
        .env("PKC_HOME", &runtime.home)
        .current_dir(&runtime.home)
        .stdin(if secret.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let result = timeout(Duration::from_secs(300), async {
        let mut child = command
            .spawn()
            .map_err(|e| format!("Could not launch pkchome: {e}"))?;
        if let Some(value) = secret {
            let mut stdin = child
                .stdin
                .take()
                .ok_or("Could not open credential input")?;
            stdin
                .write_all(value.as_bytes())
                .await
                .map_err(|_| "Could not send credential on stdin")?;
            stdin
                .shutdown()
                .await
                .map_err(|_| "Could not close credential input")?;
            drop(stdin);
        }
        let output = child
            .wait_with_output()
            .await
            .map_err(|e| format!("pkchome failed: {e}"))?;
        if output.status.success() {
            Ok(())
        } else {
            Err(error_output(
                &output.stderr,
                &output.stdout,
                secret,
                format!("pkchome exited with {}", output.status),
            ))
        }
    })
    .await
    .map_err(|_| {
        "pkchome timed out after 5 minutes; check Dashboard before trying again".to_string()
    })?;
    runtime.wake.notify_one();
    result
}
#[tauri::command]
pub async fn search(
    app: tauri::AppHandle,
    library: String,
    query: String,
) -> Result<serde_json::Value, String> {
    name(&library)?;
    let query = query.trim();
    if query.is_empty() || query.len() > 8000 {
        return Err("Enter a question of at most 8,000 bytes".into());
    }
    let runtime = app.state::<Runtime>();
    // Read current disk state to prevent stale UI selection or an arbitrary port/tenant.
    let shallow = poller::shallow(&runtime.home, &runtime.login_path).await;
    let selected = shallow
        .libraries
        .iter()
        .find(|l| l.status.name == library && l.status.current)
        .ok_or("Choose the current library in Settings before searching")?;
    if !selected.status.engine.up {
        return Err("The engine is down. Start it from Dashboard.".into());
    }
    let url = format!(
        "http://127.0.0.1:{}/v1/users/{}/recall",
        selected.status.engine.port, selected.tenant
    );
    let response = runtime.client.post(url).timeout(Duration::from_secs(90))
        .json(&serde_json::json!({ "query": query, "mode": "fast", "limit": 8, "answer_style": "concise", "visitor_class": "silent" }))
        .send().await.map_err(|e| format!("Search could not reach the engine: {e}"))?;
    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        return Err(format!(
            "Search failed ({status}): {}",
            text.chars().take(1600).collect::<String>()
        ));
    }
    let mut answer: serde_json::Value = response
        .json()
        .await
        .map_err(|_| "Engine returned an invalid recall document")?;
    let object = answer
        .as_object_mut()
        .ok_or("Engine returned an invalid recall document")?;
    if !object.get("answer").is_some_and(|v| v.is_string())
        || !object.get("used_claims").is_some_and(|v| v.is_array())
        || !object.get("used_windows").is_some_and(|v| v.is_array())
    {
        return Err("Engine returned an invalid recall document".into());
    }
    // The fast response carries canonical paths; the console's URL uses document IDs.
    // Resolve them from the public projection rather than inventing IDs from paths.
    let dataset_url = format!(
        "http://127.0.0.1:{}/v1/users/{}/dataset?audit=false",
        selected.status.engine.port, selected.tenant
    );
    let mut ids = serde_json::Map::new();
    if let Ok(response) = runtime.client.get(dataset_url).send().await {
        if response.status().is_success() {
            if let Ok(dataset) = response.json::<serde_json::Value>().await {
                if let Some(documents) = dataset
                    .pointer("/documents/documents")
                    .and_then(|v| v.as_array())
                {
                    for doc in documents {
                        if let (Some(path), Some(id)) = (
                            doc.get("path").and_then(|v| v.as_str()),
                            doc.get("document_id").and_then(|v| v.as_str()),
                        ) {
                            ids.insert(path.into(), id.into());
                        }
                    }
                }
            }
        }
    }
    object.insert("document_ids".into(), ids.into());
    Ok(answer)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn watch_and_sync_commands_pin_library_and_preserve_path_as_one_argument() {
        let action = Action::WatchAdd {
            library: "notes".into(),
            path: "/synthetic/a path/$(literal)".into(),
        };
        let (args, stdin) = arguments(&action).unwrap();
        assert_eq!(
            args,
            [
                "watch",
                "add",
                "/synthetic/a path/$(literal)",
                "--library",
                "notes"
            ]
        );
        assert!(stdin.is_none());
        assert_eq!(
            arguments(&Action::Sync {
                library: "notes".into()
            })
            .unwrap()
            .0,
            ["sync", "--library", "notes", "--json"]
        );
        assert!(arguments(&Action::SyncInterval { minutes: 0 }).is_err());
        assert!(arguments(&Action::WatchRemove {
            library: "../notes".into(),
            path: "/synthetic".into()
        })
        .is_err());
    }

    #[test]
    fn credential_is_only_stdin_even_when_it_contains_shell_metacharacters() {
        let action = Action::Credential {
            key: "OPENROUTER_API_KEY".into(),
            value: "synthetic-$(never-execute) `literal`".into(),
        };
        let (args, stdin) = arguments(&action).unwrap();
        assert_eq!(
            args,
            ["credentials", "set", "OPENROUTER_API_KEY", "--from-stdin"]
        );
        assert_eq!(stdin, Some("synthetic-$(never-execute) `literal`"));
    }

    #[test]
    fn a_refusal_states_its_reason_without_carrying_the_submitted_value_back() {
        let action = Action::Credential {
            key: "OPENROUTER_API_KEY".into(),
            value: " synthetic-key-value ".into(),
        };
        let (_, stdin) = arguments(&action).unwrap();
        // The tool trims what it reads on stdin, so its words may quote either form.
        assert_eq!(
            error_output(
                b"refused: OPENROUTER_API_KEY was not stored \xe2\x80\x94 \
                  openrouter rejected 'synthetic-key-value' (401 Unauthorized)",
                b"",
                stdin,
                "failed".into(),
            ),
            "refused: OPENROUTER_API_KEY was not stored \u{2014} \
             openrouter rejected '\u{2022}\u{2022}\u{2022}' (401 Unauthorized)"
        );
        assert_eq!(
            error_output(b"echoed [ synthetic-key-value ]", b"", stdin, "failed".into()),
            "echoed [\u{2022}\u{2022}\u{2022}]"
        );
        // Silence still says something, and a tool that speaks on stdout is still heard.
        assert_eq!(error_output(b"", b"", None, "failed".into()), "failed");
        assert_eq!(
            error_output(b"", b"refused: no reason on stderr", None, "failed".into()),
            "refused: no reason on stderr"
        );
    }

    #[test]
    fn arbitrary_commands_library_paths_and_credential_lines_are_refused() {
        assert!(
            serde_json::from_str::<Action>(r#"{"kind":"exec","argv":["touch","unexpected"]}"#)
                .is_err()
        );
        assert!(arguments(&Action::UseLibrary {
            library: "../other".into()
        })
        .is_err());
        assert!(arguments(&Action::Backend {
            library: "notes".into(),
            backend: "shell".into()
        })
        .is_err());
        assert!(arguments(&Action::Credential {
            key: "KEY".into(),
            value: "first\nSECOND=unexpected".into()
        })
        .is_err());
    }

    #[test]
    fn library_configuration_commands_always_carry_an_explicit_selection() {
        let action = Action::SemanticRetrieval {
            library: "notes".into(),
            enabled: false,
        };
        let (args, stdin) = arguments(&action).unwrap();
        assert_eq!(
            args,
            [
                "config",
                "set",
                "semantic_retrieval",
                "off",
                "--library",
                "notes"
            ]
        );
        assert!(stdin.is_none());
    }
}
