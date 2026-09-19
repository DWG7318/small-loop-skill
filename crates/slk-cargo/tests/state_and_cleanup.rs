use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::json;
use slk_cargo::{
    acquire_run_lease, cleanup_run, run_cargo_with_state, CargoInvocation, OutputSink, RunPaths,
    RunnerConfig, StateContext,
};
use slk_state_core::auth::Credential;
use slk_state_core::model::{
    CellDefinition, EndpointIdentity, GoDefinition, InitRunRequest, ProjectIdentity, Role,
    RoleIdentity,
};
use slk_state_core::write::StateStore;
use tempfile::{tempdir, TempDir};

#[derive(Default)]
struct Capture {
    stderr: Vec<u8>,
}

impl OutputSink for Capture {
    fn stdout(&mut self, _bytes: &[u8]) {}

    fn stderr(&mut self, bytes: &[u8]) {
        self.stderr.extend_from_slice(bytes);
    }
}

struct Fixture {
    _root: TempDir,
    data_root: PathBuf,
    store: StateStore,
    credential: Credential,
}

impl Fixture {
    fn new() -> Self {
        let root = tempdir().unwrap();
        let data_root = root.path().to_path_buf();
        let store = StateStore::new(&data_root);
        let initialized = store.init_run(init_request()).unwrap();
        Self {
            _root: root,
            data_root,
            store,
            credential: initialized.supervisor_credential,
        }
    }

    fn context(&self, credential: Credential) -> StateContext {
        StateContext::new(
            &self.data_root,
            credential,
            "run-a",
            Some("GO-001".into()),
            Some("CELL-001".into()),
            Some(1),
        )
    }
}

fn init_request() -> InitRunRequest {
    InitRunRequest {
        project: ProjectIdentity {
            project_id: "project-a".into(),
            name: "Project A".into(),
            repository_url: None,
            last_known_path: "D:/ProjectA".into(),
        },
        run_id: "run-a".into(),
        goal: "Keep Cargo work moving".into(),
        boundaries: json!({"write_scope":["src/"]}),
        go_nodes: vec![GoDefinition {
            go_id: "GO-001".into(),
            ordinal: 1,
            title: "GO".into(),
            objective: "Complete Cargo work".into(),
        }],
        cell_nodes: vec![CellDefinition {
            go_id: "GO-001".into(),
            cell_id: "CELL-001".into(),
            ordinal: 1,
            title: "CELL".into(),
            objective: "Run Cargo".into(),
        }],
        supervisor: RoleIdentity {
            role_instance_id: "supervisor-a".into(),
            role: Role::Supervisor,
            agent_runtime: "codex".into(),
            provider: "openai".into(),
            model: "model".into(),
            reasoning: "high".into(),
            session_id: "session-supervisor".into(),
        },
        supervisor_endpoint: EndpointIdentity {
            endpoint_version: 1,
            transport_adapter: "native-cli".into(),
            host_identity: "host-a".into(),
            session_id: "session-supervisor".into(),
            native_address: json!({"thread_id":"thread-supervisor"}),
        },
        occurred_at: "2026-09-20T00:00:00Z".into(),
    }
}

fn fake_cargo_script(root: &Path) -> PathBuf {
    let path = root.join("fake_state_cargo.py");
    fs::write(
        &path,
        r#"import pathlib
import sys
import time

mode = sys.argv[1]
marker = pathlib.Path(sys.argv[2])
first = not marker.exists()
if first:
    marker.write_text("seen", encoding="utf-8")
if mode == "once" and first:
    print("Blocking waiting for file lock on build directory", file=sys.stderr, flush=True)
    time.sleep(5)
elif mode == "always":
    print("Blocking waiting for file lock on build directory", file=sys.stderr, flush=True)
    time.sleep(5)
else:
    print("ok", flush=True)
"#,
    )
    .unwrap();
    path
}

fn invocation(script: &Path, mode: &str, marker: &Path) -> CargoInvocation {
    CargoInvocation::new(
        "python",
        vec![
            script.as_os_str().to_owned(),
            OsString::from(mode),
            marker.as_os_str().to_owned(),
        ],
        None,
    )
    .unwrap()
}

fn config() -> RunnerConfig {
    RunnerConfig::new(Duration::from_millis(70))
}

#[test]
fn successful_recovery_records_both_events_without_moving_the_token() {
    let fixture = Fixture::new();
    let before = fixture.store.current_token("run-a").unwrap();
    let paths = RunPaths::new(&fixture.data_root, "project-a", "run-a").unwrap();
    let script = fake_cargo_script(&fixture.data_root);
    let context = fixture.context(fixture.credential.clone());
    let mut capture = Capture::default();

    let result = run_cargo_with_state(
        &invocation(&script, "once", &fixture.data_root.join("once.marker")),
        &paths,
        &config(),
        &mut capture,
        Some(&context),
    )
    .unwrap();

    assert!(result.success());
    assert!(result.state_warnings().is_empty());
    assert_eq!(fixture.store.current_token("run-a").unwrap(), before);
    let run = fixture.store.query_run("run-a").unwrap();
    let events = run
        .events
        .iter()
        .filter(|event| event.event_type.starts_with("RESOURCE_"))
        .collect::<Vec<_>>();
    assert_eq!(
        events
            .iter()
            .map(|event| event.event_type.as_str())
            .collect::<Vec<_>>(),
        ["RESOURCE_CONTENDED", "RESOURCE_RECOVERED"]
    );
    for event in events {
        assert_eq!(event.author_role_instance_id, "supervisor-a");
        assert_eq!(event.go_id.as_deref(), Some("GO-001"));
        assert_eq!(event.cell_id.as_deref(), Some("CELL-001"));
        assert_eq!(event.attempt, Some(1));
    }
}

#[test]
fn failed_retry_never_records_a_false_recovered_event() {
    let fixture = Fixture::new();
    let paths = RunPaths::new(&fixture.data_root, "project-a", "run-a").unwrap();
    let script = fake_cargo_script(&fixture.data_root);
    let context = fixture.context(fixture.credential.clone());
    let mut capture = Capture::default();

    let result = run_cargo_with_state(
        &invocation(&script, "always", &fixture.data_root.join("always.marker")),
        &paths,
        &config(),
        &mut capture,
        Some(&context),
    )
    .unwrap();

    assert!(!result.success());
    let run = fixture.store.query_run("run-a").unwrap();
    assert_eq!(
        run.events
            .iter()
            .filter(|event| event.event_type == "RESOURCE_CONTENDED")
            .count(),
        1
    );
    assert!(!run
        .events
        .iter()
        .any(|event| event.event_type == "RESOURCE_RECOVERED"));
}

#[test]
fn state_write_failure_is_a_warning_and_does_not_change_cargo_success() {
    let fixture = Fixture::new();
    let paths = RunPaths::new(&fixture.data_root, "project-a", "run-a").unwrap();
    let script = fake_cargo_script(&fixture.data_root);
    let context = fixture.context(Credential::from_secret("invalid"));
    let mut capture = Capture::default();

    let result = run_cargo_with_state(
        &invocation(&script, "once", &fixture.data_root.join("invalid.marker")),
        &paths,
        &config(),
        &mut capture,
        Some(&context),
    )
    .unwrap();

    assert!(result.success());
    assert!(!result.state_warnings().is_empty());
    assert!(String::from_utf8_lossy(&capture.stderr).contains("SLK_CARGO_STATE_WARNING"));
}

#[test]
fn cleanup_refuses_active_lease_then_removes_only_the_exact_run() {
    let root = tempdir().unwrap();
    let current = RunPaths::new(root.path(), "project-a", "run-a").unwrap();
    let sibling = RunPaths::new(root.path(), "project-a", "run-b").unwrap();
    fs::create_dir_all(current.primary_target()).unwrap();
    fs::create_dir_all(sibling.primary_target()).unwrap();
    fs::write(current.primary_target().join("current.bin"), b"current").unwrap();
    fs::write(sibling.primary_target().join("sibling.bin"), b"sibling").unwrap();
    fs::create_dir_all(root.path().join("cargo-home")).unwrap();
    fs::write(root.path().join("cargo-home/cache"), b"cache").unwrap();
    fs::write(root.path().join("evidence.json"), b"evidence").unwrap();

    let lease = acquire_run_lease(&current).unwrap();
    assert_eq!(
        cleanup_run(&current).unwrap_err().code(),
        "SLK_CARGO_ACTIVE"
    );
    drop(lease);

    assert!(cleanup_run(&current).unwrap());
    assert!(!current.run_root().exists());
    assert!(sibling.primary_target().join("sibling.bin").is_file());
    assert!(root.path().join("cargo-home/cache").is_file());
    assert!(root.path().join("evidence.json").is_file());
    assert!(!cleanup_run(&current).unwrap());
}
