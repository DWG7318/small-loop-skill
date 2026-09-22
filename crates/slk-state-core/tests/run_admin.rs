use serde_json::json;

use slk_state_core::auth::Credential;
use slk_state_core::model::{
    AdoptMethodContractRequest, CellDefinition, EndpointIdentity, GoDefinition, InitRunRequest,
    MethodCompatibilityAssertions, OverwatcherAssertion, OwnerAuthorizationEvidence, OwnerDecision,
    PreservedAssertion, ProjectIdentity, ReconcileRunIdentitiesRequest, RegisterRoleRequest, Role,
    RoleIdentity,
};
use slk_state_core::write::StateStore;

const CANONICAL: &str = "run-r3b";
const SOURCES: [&str; 4] = ["run-original", "run-r2", "run-r3", "run-r3a"];

#[test]
fn reconciliation_archives_only_explicit_sources_and_preserves_engineering_history() {
    let fixture = FiveRunFixture::new();
    let before = SOURCES
        .iter()
        .chain(std::iter::once(&CANONICAL))
        .map(|run_id| {
            (
                (*run_id).to_string(),
                fixture.store.query_run(run_id).unwrap(),
            )
        })
        .collect::<Vec<_>>();

    let request = fixture.request("receipt-001");
    let result = fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, request.clone())
        .unwrap();
    assert_eq!(result.receipt_id, "receipt-001");
    assert_eq!(result.canonical_run_id, CANONICAL);

    let runs = fixture.store.list_runs(Some("project-lcas")).unwrap();
    assert_eq!(
        runs.iter()
            .filter(|run| run.run_id != "run-unmentioned")
            .filter(|run| run.identity_state == "CURRENT")
            .map(|run| run.run_id.as_str())
            .collect::<Vec<_>>(),
        vec![CANONICAL]
    );
    assert_eq!(
        runs.iter()
            .filter(|run| run.run_id != "run-unmentioned")
            .filter(|run| run.identity_state == "HISTORY")
            .count(),
        4
    );

    for (run_id, old) in before {
        let new = fixture.store.query_run(&run_id).unwrap();
        assert_eq!(new.go_nodes, old.go_nodes);
        assert_eq!(new.roles, old.roles);
        assert_eq!(new.plan_revisions, old.plan_revisions);
        assert_eq!(new.events, old.events);
        assert_eq!(new.token_history, old.token_history);
        assert_eq!(new.evidence, old.evidence);
        if run_id == CANONICAL {
            assert_eq!(new.summary.identity_state, "CURRENT");
            assert_eq!(new.token_history.last().unwrap().token_sequence, 10);
            assert_eq!(new.reconciliation_receipts.len(), 1);
            assert_eq!(
                new.reconciliation_receipts[0].source_run_ids,
                SOURCES.map(str::to_string)
            );
        } else {
            assert_eq!(new.summary.identity_state, "HISTORY");
            assert_eq!(new.summary.superseded_by_run_id.as_deref(), Some(CANONICAL));
        }
    }

    let replay = fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, request)
        .unwrap();
    assert_eq!(replay.status, "IDEMPOTENT_REPLAY");
}

#[test]
fn reconciliation_fails_closed_for_owner_scope_snapshot_and_identity_errors() {
    let fixture = FiveRunFixture::new();
    let mut wrong_decision = fixture.request("receipt-wrong-decision");
    wrong_decision.owner_authorization.decision = OwnerDecision::ApproveMethodContractAdoption;
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, wrong_decision)
        .is_err());

    let fixture = FiveRunFixture::new();
    let mut malformed_hash = fixture.request("receipt-malformed-hash");
    malformed_hash.owner_authorization.content_sha256 = "not-a-sha256".into();
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, malformed_hash)
        .is_err());

    let fixture = FiveRunFixture::new();
    let mut duplicate_source = fixture.request("receipt-duplicate-source");
    duplicate_source
        .source_snapshots
        .push(duplicate_source.source_snapshots[0].clone());
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, duplicate_source)
        .is_err());

    let fixture = FiveRunFixture::new();
    let mut canonical_as_source = fixture.request("receipt-canonical-source");
    canonical_as_source
        .source_snapshots
        .push(canonical_as_source.canonical_snapshot.clone());
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, canonical_as_source)
        .is_err());

    let fixture = FiveRunFixture::new();
    let mut stale = fixture.request("receipt-stale");
    stale.source_snapshots[0].event_count += 1;
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, stale)
        .is_err());

    let fixture = FiveRunFixture::new();
    let mut stale_token = fixture.request("receipt-stale-token");
    stale_token.source_snapshots[0].token_sequence += 1;
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, stale_token)
        .is_err());

    let fixture = FiveRunFixture::new();
    let mut stale_identity = fixture.request("receipt-stale-identity");
    stale_identity.source_snapshots[0].token_holder_role_instance_id = "invented-role".into();
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, stale_identity)
        .is_err());

    let fixture = FiveRunFixture::new();
    let mut wrong_project = fixture.request("receipt-wrong-project");
    wrong_project.source_snapshots[0].project_id = "other-project".into();
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, wrong_project)
        .is_err());

    let fixture = FiveRunFixture::new();
    let mut empty = fixture.request("receipt-empty");
    empty.source_snapshots.clear();
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, empty)
        .is_err());
}

#[test]
fn reconciliation_does_not_infer_runs_from_similar_titles_or_allow_conflicting_replay() {
    let fixture = FiveRunFixture::new();
    let request = fixture.request("receipt-replay");
    fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, request)
        .unwrap();

    let mut conflicting = fixture.request("receipt-replay");
    conflicting.reason = "changed payload under the same receipt id".into();
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, conflicting)
        .is_err());

    let already_reconciled = fixture.request("receipt-second-reconciliation");
    assert!(fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, already_reconciled)
        .is_err());

    let unmentioned = fixture.store.query_run("run-unmentioned").unwrap();
    assert_eq!(unmentioned.summary.closure_state, "open");
    assert_eq!(unmentioned.summary.identity_state, "CURRENT");
}

#[test]
fn reconciliation_projection_fails_closed_if_receipt_metadata_is_tampered() {
    let fixture = FiveRunFixture::new();
    fixture
        .store
        .reconcile_run_identities(
            &fixture.canonical_supervisor,
            fixture.request("receipt-metadata"),
        )
        .unwrap();
    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    database
        .execute(
            "UPDATE runs SET archive_reason='tampered' WHERE run_id='run-original'",
            [],
        )
        .unwrap();
    drop(database);

    let source = fixture.store.query_run("run-original").unwrap();
    assert_eq!(source.summary.identity_state, "ORPHANED_IDENTITY");
}

#[test]
fn method_adoption_preserves_origin_token_and_engineering_history() {
    let fixture = FiveRunFixture::new();
    let reconcile = fixture.request("receipt-before-adoption");
    fixture
        .store
        .reconcile_run_identities(&fixture.canonical_supervisor, reconcile)
        .unwrap();
    let before = fixture.store.query_run(CANONICAL).unwrap();
    let request = fixture.adoption_request("adoption-001", Some("receipt-before-adoption"));

    let applied = fixture
        .store
        .adopt_method_contract(&fixture.canonical_supervisor, request.clone())
        .unwrap();
    assert_eq!(applied.receipt_id, "adoption-001");
    assert_eq!(applied.effective_version, "4.2.2");

    let after = fixture.store.query_run(CANONICAL).unwrap();
    assert_eq!(after.summary.origin_slk_version, "4.1.1");
    assert_eq!(after.summary.slk_version, "4.2.2");
    assert_eq!(after.events, before.events);
    assert_eq!(after.roles, before.roles);
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.token_history.last().unwrap().token_sequence, 10);
    assert_eq!(after.go_nodes, before.go_nodes);
    assert_eq!(after.evidence, before.evidence);
    assert_eq!(after.method_adoption_receipts.len(), 1);
    assert_eq!(
        after.method_adoption_receipts[0]
            .reconciliation_receipt_id
            .as_deref(),
        Some("receipt-before-adoption")
    );

    let mut conflicting = request.clone();
    conflicting.reason = "different reason".into();
    let replay = fixture
        .store
        .adopt_method_contract(&fixture.canonical_supervisor, request)
        .unwrap();
    assert_eq!(replay.status, "IDEMPOTENT_REPLAY");
    assert!(fixture
        .store
        .adopt_method_contract(&fixture.canonical_supervisor, conflicting)
        .is_err());
}

#[test]
fn method_adoption_fails_closed_for_unsupported_stale_or_unproven_requests() {
    let fixture = FiveRunFixture::new();
    fixture
        .store
        .reconcile_run_identities(
            &fixture.canonical_supervisor,
            fixture.request("receipt-for-adoption-errors"),
        )
        .unwrap();

    let mut unsupported =
        fixture.adoption_request("adoption-unsupported", Some("receipt-for-adoption-errors"));
    unsupported.to_version = "4.3.0".into();
    assert!(fixture
        .store
        .adopt_method_contract(&fixture.canonical_supervisor, unsupported)
        .is_err());

    let mut stale = fixture.adoption_request("adoption-stale", Some("receipt-for-adoption-errors"));
    stale.expected_snapshot.token_sequence += 1;
    assert!(fixture
        .store
        .adopt_method_contract(&fixture.canonical_supervisor, stale)
        .is_err());

    let missing_receipt = fixture.adoption_request("adoption-missing", Some("does-not-exist"));
    assert!(fixture
        .store
        .adopt_method_contract(&fixture.canonical_supervisor, missing_receipt)
        .is_err());

    let mut wrong_decision = fixture.adoption_request(
        "adoption-wrong-decision",
        Some("receipt-for-adoption-errors"),
    );
    wrong_decision.owner_authorization.decision = OwnerDecision::ApproveRunIdentityReconciliation;
    assert!(fixture
        .store
        .adopt_method_contract(&fixture.canonical_supervisor, wrong_decision)
        .is_err());

    let fixture = FiveRunFixture::new();
    fixture
        .store
        .reconcile_run_identities(
            &fixture.canonical_supervisor,
            fixture.request("receipt-silent-version"),
        )
        .unwrap();
    let silent = fixture.adoption_request("adoption-silent", Some("receipt-silent-version"));
    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    database
        .execute(
            "UPDATE runs SET slk_version='4.2.0' WHERE run_id='run-r3b'",
            [],
        )
        .unwrap();
    drop(database);
    assert!(fixture
        .store
        .adopt_method_contract(&fixture.canonical_supervisor, silent)
        .is_err());
}

struct FiveRunFixture {
    _root: tempfile::TempDir,
    store: StateStore,
    canonical_supervisor: Credential,
}

impl FiveRunFixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let store = StateStore::new(root.path());
        let mut canonical_supervisor = None;

        for run_id in SOURCES
            .iter()
            .chain(std::iter::once(&CANONICAL))
            .chain(std::iter::once(&"run-unmentioned"))
        {
            let initialized = store.init_run(init_request(run_id)).unwrap();
            if *run_id == CANONICAL {
                canonical_supervisor = Some(initialized.supervisor_credential.clone());
            }
            if *run_id != "run-r3" {
                let checker = store
                    .register_role(
                        &initialized.supervisor_credential,
                        role_request(run_id, "checker", Role::Checker),
                    )
                    .unwrap();
                store
                    .register_role(
                        &checker.credential,
                        role_request(run_id, "worker", Role::Worker),
                    )
                    .unwrap();
            }
        }

        let connection = slk_state_core::schema::open_database(root.path()).unwrap();
        connection
            .execute(
                "UPDATE runs SET slk_version='4.1.1', origin_slk_version='4.1.1'",
                [],
            )
            .unwrap();
        seed_canonical_t010(&connection);

        Self {
            _root: root,
            store,
            canonical_supervisor: canonical_supervisor.unwrap(),
        }
    }

    fn request(&self, receipt_id: &str) -> ReconcileRunIdentitiesRequest {
        ReconcileRunIdentitiesRequest {
            receipt_id: receipt_id.into(),
            canonical_run_id: CANONICAL.into(),
            canonical_snapshot: self.store.run_state_snapshot(CANONICAL).unwrap(),
            source_snapshots: SOURCES
                .iter()
                .map(|run_id| self.store.run_state_snapshot(run_id).unwrap())
                .collect(),
            owner_authorization: OwnerAuthorizationEvidence {
                source_thread_id: "owner-thread-001".into(),
                message_id: "owner-message-001".into(),
                content_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                    .into(),
                decision: OwnerDecision::ApproveRunIdentityReconciliation,
                occurred_at: "2026-09-22T10:00:00Z".into(),
            },
            reason: "Owner selected R3B as the only canonical Run".into(),
            occurred_at: "2026-09-22T10:01:00Z".into(),
        }
    }

    fn adoption_request(
        &self,
        receipt_id: &str,
        reconciliation_receipt_id: Option<&str>,
    ) -> AdoptMethodContractRequest {
        AdoptMethodContractRequest {
            receipt_id: receipt_id.into(),
            run_id: CANONICAL.into(),
            expected_snapshot: self.store.run_state_snapshot(CANONICAL).unwrap(),
            from_version: "4.1.1".into(),
            to_version: "4.2.2".into(),
            owner_authorization: OwnerAuthorizationEvidence {
                source_thread_id: "owner-thread-001".into(),
                message_id: "owner-message-adoption".into(),
                content_sha256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
                    .into(),
                decision: OwnerDecision::ApproveMethodContractAdoption,
                occurred_at: "2026-09-22T10:02:00Z".into(),
            },
            reconciliation_receipt_id: reconciliation_receipt_id.map(str::to_string),
            compatibility: MethodCompatibilityAssertions {
                topology: PreservedAssertion::Preserved,
                role_bindings: PreservedAssertion::Preserved,
                token: PreservedAssertion::Preserved,
                engineering_history: PreservedAssertion::Preserved,
                overwatcher: OverwatcherAssertion::Absent,
            },
            reason: "Adopt the validated 4.2.2 administration contract".into(),
            occurred_at: "2026-09-22T10:03:00Z".into(),
        }
    }
}

fn init_request(run_id: &str) -> InitRunRequest {
    InitRunRequest {
        project: ProjectIdentity {
            project_id: "project-lcas".into(),
            name: "LCaS".into(),
            repository_url: None,
            last_known_path: "D:/LCaS".into(),
        },
        run_id: run_id.into(),
        predecessor_run_id: None,
        run_name: Some("GUI Windows Stability".into()),
        run_description: Some("Independent historical attempt".into()),
        source_kind: Some("solo".into()),
        source_project_name: None,
        goal: "Stabilize GUI windows".into(),
        boundaries: json!({"write_scope":["src/"]}),
        go_nodes: vec![GoDefinition {
            go_id: "GO-001".into(),
            ordinal: 1,
            title: "GO".into(),
            objective: "Complete the work".into(),
        }],
        cell_nodes: vec![CellDefinition {
            go_id: "GO-001".into(),
            cell_id: "CELL-001".into(),
            ordinal: 1,
            title: "CELL".into(),
            objective: "Implement one bounded change".into(),
        }],
        supervisor: role(run_id, "supervisor", Role::Supervisor),
        supervisor_endpoint: endpoint(run_id, "supervisor"),
        occurred_at: "2026-09-20T00:00:00Z".into(),
    }
}

fn role_request(run_id: &str, suffix: &str, role_kind: Role) -> RegisterRoleRequest {
    RegisterRoleRequest {
        event_id: format!("register-{run_id}-{suffix}"),
        run_id: run_id.into(),
        identity: role(run_id, suffix, role_kind),
        endpoint: endpoint(run_id, suffix),
        occurred_at: "2026-09-20T00:00:01Z".into(),
    }
}

fn role(run_id: &str, suffix: &str, role: Role) -> RoleIdentity {
    RoleIdentity {
        role_instance_id: format!("{run_id}-{suffix}"),
        role,
        agent_runtime: match role {
            Role::Supervisor | Role::Overwatcher => "codex",
            Role::Checker => "ocrv",
            Role::Worker => "dsh",
        }
        .into(),
        provider: match role {
            Role::Supervisor | Role::Overwatcher => "openai",
            Role::Checker => "dashscope-tokenplan",
            Role::Worker => "deepseek",
        }
        .into(),
        model: match role {
            Role::Supervisor | Role::Overwatcher => "gpt-5.6-sol",
            Role::Checker => "qwen3.8-max",
            Role::Worker => "deepseek-v4-flash",
        }
        .into(),
        reasoning: match role {
            Role::Supervisor | Role::Overwatcher => "xhigh",
            Role::Checker | Role::Worker => "provider-default",
        }
        .into(),
        session_id: format!("session-{run_id}-{suffix}"),
    }
}

fn endpoint(run_id: &str, suffix: &str) -> EndpointIdentity {
    EndpointIdentity {
        endpoint_version: 1,
        transport_adapter: match suffix {
            "checker" => "ocrv-checker",
            "worker" => "dsh-worker",
            _ => "codex-app-server",
        }
        .into(),
        host_identity: "host-a".into(),
        session_id: format!("session-{run_id}-{suffix}"),
        native_address: json!({"session_id":format!("session-{run_id}-{suffix}")}),
    }
}

fn seed_canonical_t010(connection: &rusqlite::Connection) {
    let supervisor = format!("{CANONICAL}-supervisor");
    for sequence in 2..=10_u64 {
        connection
            .execute(
                "INSERT INTO token_events
                 (event_id, run_id, token_sequence, from_role_instance_id,
                  to_role_instance_id, go_id, cell_id, message_id, endpoint_version,
                  event_type, payload_type, payload_sha256, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, ?4, 'GO-001', 'CELL-001', ?5, 1,
                         'TOKEN_HANDED_OFF', 'TEST_FIXTURE', ?6, ?7)",
                rusqlite::params![
                    format!("{CANONICAL}-token-{sequence}"),
                    CANONICAL,
                    sequence,
                    supervisor,
                    format!("message-{sequence}"),
                    format!("sha-{sequence}"),
                    format!("2026-09-20T00:00:{sequence:02}Z"),
                ],
            )
            .unwrap();
    }
}
