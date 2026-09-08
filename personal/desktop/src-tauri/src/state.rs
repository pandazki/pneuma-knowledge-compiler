//! Wire contract: single-machine-edition design §§4.11, 6 and 9.
//! Nullable observations stay unknown; credentials never enter this document.
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{atomic::AtomicBool, RwLock},
};
use tokio::sync::Notify;

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct HomeInfo {
    pub path: String,
    #[serde(default)]
    pub version: String,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Docker {
    pub reachable: bool,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Service {
    pub port: Option<u16>,
    pub up: Option<bool>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Engine {
    pub pid: Option<i32>,
    #[serde(default)]
    pub up: bool,
    pub port: u16,
    pub uptime: Option<f64>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Queue {
    pub pending: u64,
    pub failed: u64,
    pub last_compile_at: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SyncConfig {
    #[serde(default = "sync_interval")]
    pub interval_minutes: u64,
    #[serde(default = "sync_enabled")]
    pub enabled: bool,
}
fn sync_interval() -> u64 {
    15
}
fn sync_enabled() -> bool {
    true
}
impl Default for SyncConfig {
    fn default() -> Self {
        Self {
            interval_minutes: 15,
            enabled: true,
        }
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct SyncResult {
    pub scanned: u64,
    pub new: u64,
    pub increments: u64,
    pub held: u64,
    pub unchanged: u64,
    pub rewritten: u64,
    pub ingested: u64,
    pub skipped: u64,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct SyncStatus {
    pub last_run_at: Option<String>,
    pub last_result: Option<SyncResult>,
    pub watching: Vec<String>,
    pub next_due: Option<String>,
    pub next_due_ms: Option<u64>,
    pub running: bool,
    pub held: u64,
}
/// A step is recorded as an ISO timestamp, or derived at read time as a bare `true`
/// (design §5: profile and first compile are observed, never written). Both mean done.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(untagged)]
pub enum StepMark {
    Stamp(String),
    Done(bool),
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Steps {
    pub infra: Option<StepMark>,
    pub credentials: Option<StepMark>,
    pub profile: Option<StepMark>,
    pub skill: Option<StepMark>,
    pub first_compile: Option<StepMark>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct LibraryStatus {
    pub name: String,
    #[serde(default)]
    pub current: bool,
    pub engine: Engine,
    pub queue: Option<Queue>,
    pub key: Option<bool>,
    #[serde(default)]
    pub engine_dir: String,
    pub canonical_head: Option<String>,
    pub skill_fresh: Option<bool>,
    #[serde(default)]
    pub steps: Steps,
    pub last_used: Option<String>,
    pub sync: Option<SyncStatus>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct StatusDocument {
    pub home: HomeInfo,
    pub docker: Docker,
    #[serde(default)]
    pub services: BTreeMap<String, Service>,
    #[serde(default)]
    pub libraries: Vec<LibraryStatus>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Choices {
    #[serde(default = "default_backend")]
    pub backend: String,
    #[serde(default)]
    pub semantic_retrieval: bool,
    #[serde(default = "default_embedding")]
    pub embedding: String,
    // A library.yaml written before the posture became a choice carries today's behaviour.
    #[serde(default = "default_unattended")]
    pub unattended: bool,
}
fn default_backend() -> String {
    "codex".into()
}
fn default_embedding() -> String {
    "openrouter:openai/text-embedding-3-small".into()
}
fn default_unattended() -> bool {
    true
}
impl Default for Choices {
    fn default() -> Self {
        Self {
            backend: default_backend(),
            semantic_retrieval: false,
            embedding: default_embedding(),
            unattended: default_unattended(),
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ShallowLibrary {
    #[serde(flatten)]
    pub status: LibraryStatus,
    pub tenant: String,
    pub choices: Choices,
    pub pid_alive: bool,
    pub tcp_up: bool,
    #[serde(default)]
    pub watching: Vec<String>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Shallow {
    pub configured: bool,
    pub home: HomeInfo,
    pub docker: Docker,
    pub services: BTreeMap<String, Service>,
    pub libraries: Vec<ShallowLibrary>,
    pub errors: Vec<String>,
    #[serde(default)]
    pub sync_config: SyncConfig,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Snapshot {
    pub shallow: Shallow,
    pub deep: BTreeMap<String, StatusDocument>,
    /// Unix milliseconds of this observation, including unchanged polls.
    pub fetched_at: u64,
}
impl Snapshot {
    pub fn changed_from(&self, old: &Self) -> bool {
        // Passage of time alone must not trigger a state event. UI clocks derive uptime
        // from fetched_at. All actual health/config/provenance changes still compare.
        let normalize = |mut value: Self| {
            value.fetched_at = 0;
            for lib in &mut value.shallow.libraries {
                lib.status.engine.uptime = None;
            }
            for doc in value.deep.values_mut() {
                for lib in &mut doc.libraries {
                    lib.engine.uptime = None;
                }
            }
            value
        };
        normalize(self.clone()) != normalize(old.clone())
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Health {
    Grey,
    Green,
    Amber,
    Red,
}
impl Shallow {
    pub fn health(&self) -> Health {
        if !self.configured {
            return Health::Grey;
        }
        if !self.docker.reachable {
            return Health::Red;
        }
        if !self.errors.is_empty()
            || self.services.len() != 4
            || self.services.values().any(|s| s.up != Some(true))
            || self.libraries.iter().any(|l| !l.status.engine.up)
        {
            Health::Amber
        } else {
            Health::Green
        }
    }
}
pub struct Runtime {
    pub home: PathBuf,
    pub login_path: String,
    pub client: reqwest::Client,
    pub cache: RwLock<Snapshot>,
    pub panel_open: AtomicBool,
    /// When the panel was last ordered on screen (unix ms); a focus loss inside the first
    /// moments after showing is the show itself settling, not the Owner clicking away.
    pub shown_at_ms: std::sync::atomic::AtomicU64,
    pub wants_open: AtomicBool,
    pub ready: AtomicBool,
    pub wake: Notify,
    pub action_lock: tokio::sync::Mutex<()>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn healthy() -> Snapshot {
        let mut snapshot = Snapshot::default();
        snapshot.shallow.configured = true;
        snapshot.shallow.docker.reachable = true;
        for name in ["postgres", "qdrant", "meili", "rustfs"] {
            snapshot.shallow.services.insert(
                name.into(),
                Service {
                    port: Some(18000),
                    up: Some(true),
                },
            );
        }
        snapshot
    }

    #[test]
    fn colors_need_no_deep_document() {
        assert_eq!(Snapshot::default().shallow.health(), Health::Grey);
        let mut state = healthy();
        assert_eq!(state.shallow.health(), Health::Green);
        state.shallow.services.get_mut("postgres").unwrap().up = Some(false);
        assert_eq!(state.shallow.health(), Health::Amber);
        state.shallow.docker.reachable = false;
        assert_eq!(state.shallow.health(), Health::Red);
    }

    #[test]
    fn elapsed_time_is_not_an_event_but_health_and_queue_changes_are() {
        let mut before = healthy();
        before.deep.insert(
            "notes".into(),
            StatusDocument {
                libraries: vec![LibraryStatus {
                    name: "notes".into(),
                    engine: Engine {
                        port: 18100,
                        up: true,
                        uptime: Some(10.0),
                        ..Default::default()
                    },
                    ..Default::default()
                }],
                ..Default::default()
            },
        );
        let mut after = before.clone();
        after.fetched_at += 5000;
        after.deep.get_mut("notes").unwrap().libraries[0]
            .engine
            .uptime = Some(15.0);
        assert!(!after.changed_from(&before));
        after.deep.get_mut("notes").unwrap().libraries[0].queue = Some(Queue {
            failed: 1,
            ..Default::default()
        });
        assert!(after.changed_from(&before));
    }

    #[test]
    fn deep_response_cannot_forward_undeclared_secrets_to_the_webview() {
        let doc: StatusDocument = serde_json::from_value(serde_json::json!({
            "home": {"path": "/synthetic", "version": "1", "credentials": "synthetic-secret"},
            "docker": {"reachable": true}, "credentials": "synthetic-secret"
        }))
        .unwrap();
        assert!(!serde_json::to_string(&doc)
            .unwrap()
            .contains("synthetic-secret"));
    }
}
