use crate::state::*;
use serde::Deserialize;
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::atomic::Ordering,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::{Emitter, Manager};
use tokio::{net::TcpStream, process::Command, time::timeout};

#[derive(Default, Deserialize)]
pub struct Install {
    #[serde(default)]
    pub pkchome: String,
    #[serde(default)]
    pub version: String,
}
#[derive(Default, Deserialize)]
pub struct Infra {
    #[serde(default)]
    pub ports: BTreeMap<String, u16>,
}
#[derive(Default, Deserialize)]
pub struct Config {
    #[serde(default)]
    pub install: Install,
    #[serde(default)]
    pub infra: Infra,
    #[serde(default)]
    pub sync: SyncConfig,
}
#[derive(Deserialize)]
struct Watch {
    path: String,
}
#[derive(Deserialize)]
struct LibraryFile {
    name: String,
    tenant: String,
    engine: Engine,
    #[serde(default)]
    choices: Choices,
    #[serde(default)]
    steps: Steps,
    last_used: Option<String>,
    #[serde(default)]
    watch: Vec<Watch>,
}
pub fn home_path() -> PathBuf {
    let base = dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    let path = match std::env::var_os("PKC_HOME") {
        Some(raw) => {
            let value = raw.to_string_lossy();
            if value == "~" {
                base
            } else if let Some(rest) = value.strip_prefix("~/") {
                base.join(rest)
            } else {
                PathBuf::from(raw)
            }
        }
        None => base.join(".pkc"),
    };
    let absolute = if path.is_absolute() {
        path
    } else {
        std::env::current_dir().unwrap_or_default().join(path)
    };
    absolute.canonicalize().unwrap_or(absolute)
}
pub async fn config(home: &Path) -> Result<Config, String> {
    let text = tokio::fs::read_to_string(home.join("config.yaml"))
        .await
        .map_err(|_| "Cannot read home configuration".to_string())?;
    // Parser errors can quote config lines containing infra secrets. Do not return them.
    serde_yaml::from_str(&text).map_err(|_| "Invalid home configuration".to_string())
}
pub fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 32
        && name.as_bytes()[0].is_ascii_lowercase()
        && name
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
}
pub async fn tcp(port: u16) -> bool {
    matches!(
        timeout(
            Duration::from_millis(350),
            TcpStream::connect(("127.0.0.1", port))
        )
        .await,
        Ok(Ok(_))
    )
}
async fn docker(path: &str) -> bool {
    let mut cmd = Command::new("docker");
    cmd.env("PATH", path)
        .args(["info", "--format", "{{.ServerVersion}}"])
        .stdin(std::process::Stdio::null())
        .kill_on_drop(true);
    #[cfg(windows)]
    cmd.creation_flags(0x08000000);
    matches!(timeout(Duration::from_secs(2), cmd.output()).await, Ok(Ok(out)) if out.status.success())
}
async fn pid_alive(pid: Option<i32>) -> bool {
    let Some(pid) = pid.filter(|p| *p > 0) else {
        return false;
    };
    #[cfg(unix)]
    {
        // Signal 0 probes existence without signalling or modifying the process.
        unsafe {
            libc::kill(pid, 0) == 0
                || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
        }
    }
    #[cfg(windows)]
    {
        let result = timeout(
            Duration::from_secs(1),
            Command::new("tasklist")
                .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
                .creation_flags(0x08000000)
                .kill_on_drop(true)
                .output(),
        )
        .await;
        matches!(result, Ok(Ok(out)) if out.status.success() && String::from_utf8_lossy(&out.stdout).contains(&format!("\"{pid}\"")))
    }
}
pub async fn shallow(home: &Path, login_path: &str) -> Shallow {
    let mut result = Shallow {
        configured: home.join("config.yaml").exists(),
        home: HomeInfo {
            path: home.display().to_string(),
            version: String::new(),
        },
        ..Default::default()
    };
    if !result.configured {
        return result;
    }
    let (config, docker_up) = tokio::join!(config(home), docker(login_path));
    result.docker.reachable = docker_up;
    let config = match config {
        Ok(config) => config,
        Err(error) => {
            result.errors.push(error);
            return result;
        }
    };
    result.home.version = config.install.version;
    result.sync_config = config.sync;
    let mut probes = tokio::task::JoinSet::new();
    for name in ["postgres", "qdrant", "meili", "rustfs"] {
        let port = config.infra.ports.get(name).copied().filter(|p| *p > 0);
        probes.spawn(async move {
            (
                name,
                Service {
                    port,
                    up: match port {
                        Some(p) => Some(tcp(p).await),
                        None => None,
                    },
                },
            )
        });
    }
    while let Some(Ok((name, service))) = probes.join_next().await {
        result.services.insert(name.into(), service);
    }
    let current = tokio::fs::read_to_string(home.join("current"))
        .await
        .unwrap_or_default();
    let root = home.join("libraries");
    let mut entries = match tokio::fs::read_dir(&root).await {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return result,
        Err(_) => {
            result.errors.push("Cannot read libraries".into());
            return result;
        }
    };
    let mut engines = tokio::task::JoinSet::new();
    while let Ok(Some(entry)) = entries.next_entry().await {
        let name = entry.file_name().to_string_lossy().to_string();
        if !valid_name(&name) || !entry.path().join("library.yaml").exists() {
            continue;
        }
        let home = home.to_owned();
        let current = current.trim().to_owned();
        engines.spawn(async move {
            let text = tokio::fs::read_to_string(entry.path().join("library.yaml"))
                .await
                .map_err(|_| format!("Cannot read library {name}"))?;
            let file: LibraryFile =
                serde_yaml::from_str(&text).map_err(|_| format!("Invalid library {name}"))?;
            if file.name != name || file.tenant != format!("lib-{name}") || file.engine.port == 0 {
                return Err(format!("Invalid identity or port for library {name}"));
            }
            let pid_file = home.join("run").join(format!("{name}.pid"));
            let pid = tokio::fs::read_to_string(&pid_file)
                .await
                .ok()
                .and_then(|s| s.trim().parse::<i32>().ok())
                .filter(|p| *p > 0);
            let (alive, tcp_up) = tokio::join!(pid_alive(pid), tcp(file.engine.port));
            let uptime = if alive {
                tokio::fs::metadata(pid_file)
                    .await
                    .ok()
                    .and_then(|m| m.modified().ok())
                    .and_then(|t| SystemTime::now().duration_since(t).ok())
                    .map(|d| d.as_secs_f64())
            } else {
                None
            };
            Ok(ShallowLibrary {
                status: LibraryStatus {
                    name: name.clone(),
                    current: name == current,
                    engine: Engine {
                        pid,
                        up: alive && tcp_up,
                        port: file.engine.port,
                        uptime,
                    },
                    engine_dir: entry.path().join("engine").display().to_string(),
                    steps: file.steps,
                    last_used: file.last_used,
                    ..Default::default()
                },
                tenant: file.tenant,
                choices: file.choices,
                pid_alive: alive,
                tcp_up,
                watching: file.watch.into_iter().map(|w| w.path).collect(),
            })
        });
    }
    while let Some(row) = engines.join_next().await {
        match row {
            Ok(Ok(lib)) => result.libraries.push(lib),
            Ok(Err(error)) => result.errors.push(error),
            Err(_) => result.errors.push("Library probe failed".into()),
        }
    }
    result
        .libraries
        .sort_by(|a, b| a.status.name.cmp(&b.status.name));
    result.errors.sort();
    result
}
pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
async fn deep(runtime: &Runtime, shallow: &Shallow) -> BTreeMap<String, StatusDocument> {
    let mut tasks = tokio::task::JoinSet::new();
    for library in &shallow.libraries {
        if !library.tcp_up {
            continue;
        }
        let name = library.status.name.clone();
        let url = format!(
            "http://127.0.0.1:{}/home/status",
            library.status.engine.port
        );
        let client = runtime.client.clone();
        let expected_home = shallow.home.path.clone();
        tasks.spawn(async move {
            // The engine serves its last computed document instantly; five seconds is for a
            // machine that is busy, not for the document's own probes.
            let document = timeout(Duration::from_secs(5), async {
                let response = client.get(url).send().await.ok()?.error_for_status().ok()?;
                let doc = response.json::<StatusDocument>().await.ok()?;
                // A listener on a reused port is not an authority over this home.
                (doc.home.path == expected_home && doc.libraries.iter().any(|l| l.name == name))
                    .then_some(doc)
            })
            .await
            .ok()
            .flatten();
            (name, document)
        });
    }
    let mut result = BTreeMap::new();
    while let Some(row) = tasks.join_next().await {
        if let Ok((name, Some(doc))) = row {
            result.insert(name, doc);
        }
    }
    result
}
fn publish(app: &tauri::AppHandle, next: Snapshot) {
    let runtime = app.state::<Runtime>();
    let changed = {
        let mut cache = runtime.cache.write().unwrap();
        let changed = next.changed_from(&cache);
        *cache = next.clone();
        changed
    };
    if changed {
        crate::panel::update_icon(app, next.shallow.health());
        let _ = app.emit_to("panel", "state", next);
    }
}
pub async fn run(app: tauri::AppHandle) {
    let mut attempts = BTreeMap::new();
    loop {
        let started = tokio::time::Instant::now();
        let runtime = app.state::<Runtime>();
        let shallow = shallow(&runtime.home, &runtime.login_path).await;
        // Publish health immediately; a slow deep endpoint cannot delay the red icon.
        let mut previous = runtime.cache.read().unwrap().deep.clone();
        previous.retain(|name, _| {
            shallow
                .libraries
                .iter()
                .any(|l| l.status.name == *name && l.tcp_up)
        });
        publish(
            &app,
            Snapshot {
                shallow: shallow.clone(),
                deep: previous,
                fetched_at: now_ms(),
            },
        );
        let deep = deep(&runtime, &shallow).await;
        for library in &shallow.libraries {
            let name = &library.status.name;
            let sync = deep
                .get(name)
                .and_then(|doc| doc.libraries.iter().find(|row| row.name == *name))
                .and_then(|row| row.sync.as_ref());
            if sync_due(
                &shallow.sync_config,
                library.status.engine.up,
                sync,
                now_ms(),
                attempts.get(name).copied(),
            ) {
                attempts.insert(name.clone(), now_ms());
                if let Err(error) = request_sync(&runtime.client, library.status.engine.port).await
                {
                    eprintln!("Sync for {name}: {error}");
                }
            }
        }
        publish(
            &app,
            Snapshot {
                shallow,
                deep,
                fetched_at: now_ms(),
            },
        );
        let seconds = if runtime.panel_open.load(Ordering::Relaxed) {
            2
        } else {
            5
        };
        tokio::select! {
            _ = tokio::time::sleep_until(started + Duration::from_secs(seconds)) => {},
            _ = runtime.wake.notified() => {},
        }
    }
}

pub fn sync_due(
    config: &SyncConfig,
    engine_up: bool,
    status: Option<&SyncStatus>,
    now: u64,
    last_attempt: Option<u64>,
) -> bool {
    let Some(status) = status else {
        return false;
    };
    let interval = config.interval_minutes.max(1).saturating_mul(60_000);
    config.enabled
        && engine_up
        && !status.running
        && !status.watching.is_empty()
        && status.next_due_ms.is_some_and(|due| now >= due)
        && last_attempt.is_none_or(|last| now.saturating_sub(last) >= interval)
}

pub fn sync_request(client: &reqwest::Client, port: u16) -> reqwest::RequestBuilder {
    client.post(format!("http://127.0.0.1:{port}/home/actions/sync"))
}

pub async fn request_sync(client: &reqwest::Client, port: u16) -> Result<(), String> {
    let response = sync_request(client, port)
        .send()
        .await
        .map_err(|_| "Could not reach the engine for sync")?
        .error_for_status()
        .map_err(|_| "Engine refused sync")?;
    let body: serde_json::Value = response.json().await.map_err(|_| "Invalid sync response")?;
    if body.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return Err("Engine could not start sync; check its actions log".into());
    }
    Ok(())
}

pub async fn sync_now(runtime: &Runtime, name: &str) -> Result<(), String> {
    let shallow = shallow(&runtime.home, &runtime.login_path).await;
    let library = shallow
        .libraries
        .iter()
        .find(|l| l.status.name == name && l.status.engine.up)
        .ok_or("Start this library's engine before syncing")?;
    let documents = deep(runtime, &shallow).await;
    let row = documents
        .get(name)
        .and_then(|doc| doc.libraries.iter().find(|l| l.name == name))
        .ok_or("The library's status is unavailable")?;
    if row.sync.as_ref().is_some_and(|s| s.running) {
        return Err("Sync is already running for this library".into());
    }
    request_sync(&runtime.client, library.status.engine.port).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sync_due_requires_enabled_live_idle_library_and_elapsed_interval() {
        let mut config = SyncConfig::default();
        let mut sync = SyncStatus {
            watching: vec!["/synthetic/momo".into()],
            next_due_ms: Some(900_000),
            ..Default::default()
        };
        assert!(!sync_due(&config, true, Some(&sync), 899_999, None));
        assert!(sync_due(&config, true, Some(&sync), 900_000, None));
        assert!(!sync_due(&config, false, Some(&sync), 900_000, None));
        assert!(!sync_due(&config, true, None, 900_000, None));
        assert!(!sync_due(&config, true, Some(&sync), 900_000, Some(1)));
        assert!(sync_due(&config, true, Some(&sync), 900_001, Some(1)));
        sync.running = true;
        assert!(!sync_due(&config, true, Some(&sync), 900_000, None));
        sync.running = false;
        config.enabled = false;
        assert!(!sync_due(&config, true, Some(&sync), 900_000, None));
        config.enabled = true;
        sync.watching.clear();
        assert!(!sync_due(&config, true, Some(&sync), 900_000, None));
        sync.watching.push("/synthetic/momo".into());
        sync.next_due_ms = Some(0);
        assert!(sync_due(&config, true, Some(&sync), 1, None));
    }

    #[test]
    fn sync_action_is_a_post_to_the_selected_engine_with_no_transcript() {
        let request = sync_request(&reqwest::Client::new(), 18123)
            .build()
            .unwrap();
        assert_eq!(request.method(), reqwest::Method::POST);
        assert_eq!(
            request.url().as_str(),
            "http://127.0.0.1:18123/home/actions/sync"
        );
        assert!(request.body().is_none());
    }

    #[test]
    fn config_parsing_projects_only_the_fields_the_tray_needs() {
        let config: Config = serde_yaml::from_str("install:\n  pkchome: '/a path/pkchome'\n  version: '1'\ninfra:\n  ports: {postgres: 15432}\n  pg_password: synthetic-secret\n").unwrap();
        assert_eq!(config.install.pkchome, "/a path/pkchome");
        assert_eq!(config.infra.ports["postgres"], 15432);
    }

    #[tokio::test]
    async fn a_missing_home_needs_no_docker_or_engine() {
        let path = std::env::temp_dir().join(format!(
            "pkc-absent-test-{}-{}",
            std::process::id(),
            now_ms()
        ));
        let observation = shallow(&path, "").await;
        assert!(!observation.configured);
        assert_eq!(observation.health(), Health::Grey);
        assert!(observation.libraries.is_empty());
        assert!(!path.exists());
    }
}

#[cfg(test)]
mod e2e_shapes {
    //! The two documents a real cold start produced (paths replaced), so the parsers are
    //! pinned to what `pkchome` writes and serves, not to what the tray hoped for.
    use super::*;

    const LIBRARY_YAML: &str = r#"name: notes
tenant: lib-notes
created: '2026-09-07T11:38:50.966153+00:00'
engine:
  port: 43022
choices:
  backend: codex
  language: zh
  semantic_retrieval: false
  embedding: openrouter:openai/text-embedding-3-small
steps:
  infra: '2026-09-07T11:39:37.097700+00:00'
  credentials: null
  skill: '2026-09-07T11:39:01.668286+00:00'
last_used: '2026-09-07T11:39:35.609106+00:00'
bindings: []
"#;
    const STATUS_JSON: &str = r#"{"home": {"path": "/Users/mei/.pkc", "version": "0.1.0"}, "docker": {"reachable": true}, "services": {"postgres": {"port": 47830, "up": true}, "qdrant": {"port": 51170, "up": true}, "meili": {"port": 36843, "up": true}, "rustfs": {"port": 36007, "up": true}}, "libraries": [{"name": "notes", "tenant": "lib-notes", "current": true, "engine": {"pid": 13052, "up": true, "port": 43022, "uptime": 115.74450588226318}, "queue": {"pending": 0, "failed": 0, "last_compile_at": null}, "key": false, "engine_dir": "/Users/mei/.pkc/libraries/notes/engine", "canonical_head": null, "skill_fresh": true, "steps": {"infra": "2026-09-07T11:39:37.097700+00:00", "credentials": null, "profile": true, "skill": "2026-09-07T11:39:01.668286+00:00", "first_compile": null}, "last_used": "2026-09-07T11:39:35.609106+00:00"}]}"#;

    #[test]
    fn parses_a_real_library_yaml_and_status_document() {
        let file: Result<LibraryFile, _> = serde_yaml::from_str(LIBRARY_YAML);
        assert!(file.is_ok(), "library.yaml: {:?}", file.err());
        let doc: Result<StatusDocument, _> = serde_json::from_str(STATUS_JSON);
        assert!(doc.is_ok(), "status: {:?}", doc.err());
        let doc = doc.unwrap();
        assert_eq!(doc.libraries[0].steps.profile, Some(StepMark::Done(true)));
    }
}
