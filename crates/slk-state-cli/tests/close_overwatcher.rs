use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use slk_state_core::{auth::Credential, model::*, write::StateStore};
use std::{fs, process::Command};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

struct Fixture {
    root: tempfile::TempDir,
    store: StateStore,
    supervisor: Credential,
    overwatcher: Credential,
    proof: String,
}

fn now() -> String {
    OffsetDateTime::now_utc().format(&Rfc3339).unwrap()
}

impl Fixture {
    fn new(status: Value) -> Self {
        let root = tempfile::tempdir().unwrap();
        let store = StateStore::new(root.path());
        let init: InitRunRequest = serde_json::from_value(json!({
            "project":{"project_id":"project-a","name":"Synthetic","repository_url":null,"last_known_path":"synthetic"},
            "run_id":"run-a","goal":"Synthetic CLI test","boundaries":{},
            "go_nodes":[{"go_id":"GO-001","ordinal":1,"title":"GO","objective":"test"}],
            "cell_nodes":[{"go_id":"GO-001","cell_id":"CELL-001","ordinal":1,"title":"CELL","objective":"test"}],
            "supervisor":{"role_instance_id":"supervisor-a","role":"supervisor","agent_runtime":"codex","provider":"openai","model":"gpt-6.1-sol","reasoning":"xhigh","session_id":"parent-a"},
            "supervisor_endpoint":{"endpoint_version":1,"transport_adapter":"codex-app-server","host_identity":"host-a","session_id":"parent-a","native_address":{"thread_id":"parent-a"}},
            "occurred_at":now()
        })).unwrap();
        let supervisor = store.init_run(init).unwrap().supervisor_credential;
        let db = slk_state_core::schema::open_database(root.path()).unwrap();
        db.execute(
            "UPDATE runs SET slk_version='4.5.4' WHERE run_id='run-a'",
            [],
        )
        .unwrap();
        let address = json!({"kind":"supervisor_subagent","parent":{"agent_runtime":"codex","host_identity":"host-a","session_id":"parent-a"},"agent_id":"/root/ow"});
        let at = now();
        let call = |name: &str, id: &str, args: Value| json!({"timestamp":at,"type":"response_item","payload":{"type":"function_call","namespace":"collaboration","name":name,"call_id":id,"arguments":args.to_string()}});
        let output = |id: &str, result: Value| json!({"timestamp":at,"type":"response_item","payload":{"type":"function_call_output","call_id":id,"output":result.to_string()}});
        let records = vec![
            json!({"type":"session_meta","payload":{"id":"parent-a"}}),
            call("spawn_agent", "call_spawn", json!({"task_name":"ow"})),
            output("call_spawn", json!({"task_name":"/root/ow"})),
            call("list_agents", "call_initial", json!({})),
            output(
                "call_initial",
                json!({"agents":[{"agent_name":"/root/ow","agent_status":"running"}]}),
            ),
            call("list_agents", "call_final", json!({})),
            output(
                "call_final",
                json!({"agents":[{"agent_name":"/root/ow","agent_status":status}]}),
            ),
        ];
        let source = root.path().join("rollout-parent-a.jsonl");
        fs::write(
            &source,
            records
                .iter()
                .map(|r| r.to_string() + "\n")
                .collect::<String>(),
        )
        .unwrap();
        let request = json!({"schema_version":"slk.subagent-overwatcher-request/v1","method_version":"4.5.4","run_id":"run-a","role_instance_id":"overwatcher-a","endpoint_ref":"endpoint-a","native_address":address,"native_execution_id":"codex-subagent-spawn:call_spawn","native_source_path":source});
        let request_bytes = serde_json::to_vec(&request).unwrap();
        fs::write(
            root.path().join("subagent-overwatcher-request.json"),
            &request_bytes,
        )
        .unwrap();
        let mut proof = request;
        proof["schema_version"] = json!("slk.subagent-overwatcher-proof/v1");
        proof["request_sha256"] = json!(format!("{:x}", Sha256::digest(&request_bytes)));
        proof["canonical_task_id"] = json!("codex-subagent-spawn-call_spawn");
        proof["native_task_id"] = json!("codex-subagent:parent-a:call_spawn:/root/ow");
        proof["sample_call_id"] = json!("call_initial");
        proof["agent_status"] = json!("RUNNING");
        proof["checked_at"] = json!(at);
        for (prefix, index) in [("spawn", 1), ("sample", 3)] {
            for (part, offset) in [("call", 0), ("output", 1)] {
                proof[format!("{prefix}_{part}_sha256")] = json!(format!(
                    "{:x}",
                    Sha256::digest(records[index + offset].to_string().as_bytes())
                ));
                proof[format!(
                    "{prefix}_{}_timestamp",
                    if part == "call" { "query" } else { "output" }
                )] = json!(at);
            }
        }
        let start = json!({"schema_version":"slk.native-start/v2","status":"STARTED","adapter":"codex-overwatcher","run_id":"run-a","cell_id":"RUN-OVERWATCH","message_id":"codex-subagent-spawn-call_spawn","request_sha256":proof["request_sha256"],"native_request_sha256":proof["spawn_call_sha256"],"observed_at":at,"process":{"pid":1,"creation_time":"synthetic"},"native_task":{"kind":"codex-subagent","id":proof["native_task_id"],"status":"RUNNING"}});
        let start_bytes = serde_json::to_vec(&start).unwrap();
        fs::write(root.path().join("started.json"), &start_bytes).unwrap();
        proof["started_sha256"] = json!(format!("{:x}", Sha256::digest(start_bytes)));
        let proof_path = root.path().join("subagent-overwatcher-proof.json");
        fs::write(&proof_path, serde_json::to_vec(&proof).unwrap()).unwrap();
        let binding: BindOverwatcherRequest = serde_json::from_value(json!({
            "event_id":"bind-ow","run_id":"run-a","identity":{"role_instance_id":"overwatcher-a","role":"overwatcher","agent_runtime":"codex","provider":"openai","model":"gpt-6-luna","reasoning":"xhigh","session_id":"/root/ow"},
            "endpoint":{"endpoint_version":1,"transport_adapter":"codex-app-server","host_identity":"host-a","session_id":"/root/ow","native_address":address},
            "observation_mode":"FOREGROUND_ACTIVE_TURN","cadence_seconds":600,"foreground_turn_id":"codex-subagent-spawn:call_spawn","native_active_session_evidence_ref":proof_path,"binding_revision":1,"canonical_task_id":"codex-subagent-spawn-call_spawn","reason":"Synthetic","occurred_at":at
        })).unwrap();
        let overwatcher = store
            .bind_overwatcher(&supervisor, binding)
            .unwrap()
            .credential;
        // Isolated terminal engineering fixture, independently of native exit proof.
        db.execute("UPDATE runs SET closure_state='closed',state='archived',archived_at='2026-10-18T00:00:00Z' WHERE run_id='run-a'", []).unwrap();
        slk_state_core::config::configure_at(&root.path().join("config.json"), root.path())
            .unwrap();
        Self {
            root,
            store,
            supervisor,
            overwatcher,
            proof: proof_path.to_string_lossy().into_owned(),
        }
    }

    fn request(&self) -> Value {
        json!({"event_id":"close-ow","run_id":"run-a","archive_evidence_ref":self.proof,"final_cycle_id":null,"runtime_revision":self.store.query_run("run-a").unwrap().runtime_snapshot.unwrap().runtime_revision,"occurred_at":now()})
    }

    fn run(
        &self,
        request: Value,
        role: Option<&Credential>,
        ow: Option<&Credential>,
    ) -> (bool, Value) {
        self.command("close-overwatcher", request, role, ow)
    }

    fn command(
        &self,
        command: &str,
        request: Value,
        role: Option<&Credential>,
        ow: Option<&Credential>,
    ) -> (bool, Value) {
        let path = self.root.path().join("close.json");
        fs::write(&path, serde_json::to_vec(&request).unwrap()).unwrap();
        let mut cmd = Command::new(env!("CARGO_BIN_EXE_slk-state"));
        cmd.args([command, "--request"])
            .arg(path)
            .env("SLK_CONFIG_PATH", self.root.path().join("config.json"))
            .env_remove("SLK_ROLE_CREDENTIAL")
            .env_remove("SLK_OVERWATCHER_CREDENTIAL");
        if let Some(c) = role {
            cmd.env("SLK_ROLE_CREDENTIAL", c.expose_secret());
        }
        if let Some(c) = ow {
            cmd.env("SLK_OVERWATCHER_CREDENTIAL", c.expose_secret());
        }
        let out = cmd.output().unwrap();
        (
            out.status.success(),
            serde_json::from_slice(if out.status.success() {
                &out.stdout
            } else {
                &out.stderr
            })
            .unwrap(),
        )
    }
}

#[test]
fn summary_cli_records_replays_corrects_and_exports_without_engineering_changes() {
    let f = Fixture::new(json!("interrupted"));
    let before = f.store.query_run("run-a").unwrap();
    let request = json!({"run_id":"run-a","original_id":"closeout-one","body":"完成：验证通过。\nNo further work.","recorded_at":now(),"device_signature":{"computer_name":"test-host","ip_address":null,"os_version":"test-os"}});
    let (ok, first) = f.command(
        "record-closeout-summary",
        request.clone(),
        Some(&f.supervisor),
        None,
    );
    assert!(ok, "{first}");
    assert_eq!(first["status"], "summary_recorded");
    assert_eq!(first["closeout_summary"]["source_revision"], 1);
    assert_eq!(first["closeout_summary"]["authored_by"], "supervisor-a");
    let summary = &first["closeout_summary"];
    let canonical=format!("{{\"body\":{},\"authored_by\":{},\"recorded_at\":{},\"source_id\":{},\"source_revision\":{}}}",summary["body"],summary["authored_by"],summary["recorded_at"],summary["source_id"],summary["source_revision"]);
    assert_eq!(
        summary["content_sha256"],
        format!("{:x}", Sha256::digest(canonical.as_bytes()))
    );
    let (ok, replay) = f.command(
        "record-closeout-summary",
        request.clone(),
        Some(&f.supervisor),
        None,
    );
    assert!(ok, "{replay}");
    assert_eq!(replay["status"], "summary_replayed");
    assert_eq!(replay["closeout_summary"], first["closeout_summary"]);
    let mut conflict = request.clone();
    conflict["device_signature"]["computer_name"] = json!("changed");
    assert!(
        !f.command(
            "record-closeout-summary",
            conflict,
            Some(&f.supervisor),
            None
        )
        .0
    );
    let mut correction = request.clone();
    correction["original_id"] = json!("closeout-two");
    correction["body"] = json!("Corrected concise conclusion");
    let (ok, second) = f.command(
        "record-closeout-summary",
        correction,
        Some(&f.supervisor),
        None,
    );
    assert!(ok, "{second}");
    assert_eq!(second["closeout_summary"]["source_revision"], 2);
    assert_ne!(
        second["closeout_summary"]["source_id"],
        first["closeout_summary"]["source_id"]
    );
    let after = f.store.query_run("run-a").unwrap();
    let projected = serde_json::to_value(&after).unwrap();
    assert_eq!(projected["closeout_summary"], second["closeout_summary"]);
    assert_eq!(projected["device_signature"], request["device_signature"]);
    assert_eq!(after.runtime_snapshot, before.runtime_snapshot);
    assert_eq!(after.events, before.events);
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.plan_revisions, before.plan_revisions);
    assert_eq!(after.summary, before.summary);
    assert_eq!(after.evidence.len(), before.evidence.len() + 2);
    let export = fs::read_to_string(f.store.export_run("run-a").unwrap()).unwrap();
    assert!(export.contains("Corrected concise conclusion"));
    assert!(export.contains(
        second["closeout_summary"]["content_sha256"]
            .as_str()
            .unwrap()
    ));
    let replay_old = f.command(
        "record-closeout-summary",
        request.clone(),
        Some(&f.supervisor),
        None,
    );
    assert_eq!(replay_old.1["closeout_summary"], first["closeout_summary"]);
    // Wrong role never gains authority through a valid-looking authored_by field.
    assert!(
        !f.command(
            "record-closeout-summary",
            request.clone(),
            Some(&f.overwatcher),
            None
        )
        .0
    );
    let mut spoof = request;
    spoof["authored_by"] = json!("supervisor-a");
    assert!(
        !f.command("record-closeout-summary", spoof, Some(&f.supervisor), None)
            .0
    );
    let latest = after
        .evidence
        .iter()
        .find(|e| e.evidence_id == second["closeout_summary"]["source_id"].as_str().unwrap())
        .unwrap();
    fs::write(f.root.path().join(&latest.stored_path), b"corrupt original").unwrap();
    let damaged = serde_json::to_value(f.store.query_run("run-a").unwrap()).unwrap();
    assert!(damaged.get("closeout_summary").is_none());
    assert!(damaged.get("device_signature").is_none());
}

#[test]
fn old_run_omits_summary_and_generic_evidence_cannot_spoof_reserved_type() {
    let f = Fixture::new(json!("interrupted"));
    let projected = serde_json::to_value(f.store.query_run("run-a").unwrap()).unwrap();
    assert!(projected.get("closeout_summary").is_none());
    assert!(projected.get("device_signature").is_none());
    let source = f.root.path().join("spoof.json");
    fs::write(&source, b"{}").unwrap();
    let request = json!({"evidence_id":"spoof","run_id":"run-a","go_id":null,"cell_id":null,"evidence_type":"run_closeout_summary","source_path":source,"occurred_at":now()});
    let (ok, body) = f.command("register-evidence", request, Some(&f.supervisor), None);
    assert!(
        !ok,
        "reserved evidence must use authenticated producer: {body}"
    );
}

#[test]
fn creator_supervisor_cli_closes_exact_ended_child() {
    let fixture = Fixture::new(json!("interrupted"));
    let (ok, body) = fixture.run(fixture.request(), Some(&fixture.supervisor), None);
    assert!(ok, "{body}");
}

#[test]
fn creator_close_cli_rejects_missing_wrong_role_stale_wrong_run_and_active_child() {
    for variant in [
        "missing",
        "wrong-role",
        "stale",
        "wrong-run",
        "active",
        "empty-cycle",
    ] {
        let fixture = Fixture::new(if variant == "active" {
            json!("running")
        } else {
            json!("interrupted")
        });
        let mut request = fixture.request();
        let before = fixture.store.query_run("run-a").unwrap().runtime_snapshot;
        if variant == "stale" {
            request["runtime_revision"] = json!(0);
        }
        if variant == "wrong-run" {
            request["run_id"] = json!("other-run");
        }
        if variant == "empty-cycle" {
            request["final_cycle_id"] = json!("");
        }
        let role = if variant == "missing" {
            None
        } else if variant == "wrong-role" {
            Some(&fixture.overwatcher)
        } else {
            Some(&fixture.supervisor)
        };
        let (ok, body) = fixture.run(request, role, Some(&fixture.overwatcher));
        assert!(!ok, "{variant}: {body}");
        if variant == "missing" {
            assert_eq!(body["code"], "SLK_ROLE_CREDENTIAL_REQUIRED");
        }
        assert_eq!(
            fixture.store.query_run("run-a").unwrap().runtime_snapshot,
            before
        );
    }
}

#[test]
fn final_cycle_cli_uses_only_overwatcher_credential() {
    let fixture = Fixture::new(json!("interrupted"));
    let mut request = fixture.request();
    request["final_cycle_id"] = json!("final-cycle");
    let (ok, body) = fixture.run(request.clone(), Some(&fixture.supervisor), None);
    assert!(!ok);
    assert_eq!(body["code"], "SLK_OVERWATCHER_CREDENTIAL_REQUIRED");
    let db = slk_state_core::schema::open_database(fixture.root.path()).unwrap();
    db.execute("INSERT INTO overwatch_cycles (cycle_id,run_id,plan_revision,overwatcher_role_instance_id,session_id,foreground_turn_id,cycle_sequence,cadence_seconds,token_sequence,token_holder_role_instance_id,latest_event_id,checklist_json,anomaly_codes_json,evidence_refs_json,native_active_session_evidence_ref,started_at,completed_at,next_cycle_at,payload_sha256,binding_revision,runtime_revision,native_liveness) VALUES ('final-cycle','run-a',1,'overwatcher-a','/root/ow','codex-subagent-spawn:call_spawn',1,600,1,'supervisor-a','bind-ow','{}','[]','[]','synthetic','2026-10-18T00:00:00Z','2026-10-18T00:00:01Z','2026-10-18T00:10:01Z','synthetic',1,?1,'IN_PROGRESS')",[request["runtime_revision"].as_u64().unwrap()]).unwrap();
    let (ok, body) = fixture.run(
        request,
        Some(&fixture.supervisor),
        Some(&fixture.overwatcher),
    );
    assert!(ok, "{body}");
}
