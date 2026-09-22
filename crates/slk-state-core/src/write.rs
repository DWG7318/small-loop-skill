//! Atomic Run, role, work-event, and SLK TOKEN transactions.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use rusqlite::{
    params, Connection, ErrorCode, OptionalExtension, Transaction, TransactionBehavior,
};
use sha2::{Digest, Sha256};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

use crate::auth::{
    authorize_event, authorize_overwatcher, authorize_role, issue_credential,
    new_credential_material, revoke_credential, AuthorizedActor, Credential, IssuedCredential,
    StateError,
};
use crate::model::{
    AdoptMethodContractRequest, BindOverwatcherRequest, CloseOverwatcherRequest,
    CommitDeliveryStartRequest, EventType, EvidenceReference, InitRunRequest, NativeLiveness,
    OperationalObservationRequest, OverwatchCheckResult, OverwatchCycleRequest,
    OverwatcherAssertion, OverwatcherReplacementMode, OwnerAuthorizationEvidence, OwnerDecision,
    RebindSessionRequest, ReconcileRunIdentitiesRequest, RecordOverwatcherStatusRequest,
    RegisterRoleRequest, ReplaceOverwatcherRequest, ReplaceRoleRequest, RevisePlanRequest, Role,
    RunStateSnapshot, RuntimeSnapshot, TokenHandoffRequest, WriteRequest,
};
use crate::schema::{open_database, SchemaError};

const TRANSACTION_ATTEMPTS: usize = 3;
type OverwatchCycleBindingRow = (String, String, i64, String, String, u64, String, String);
type ActiveOverwatcherGateRow = (Option<i64>, Option<String>, String, u64, String, String);

#[derive(Debug, Clone)]
pub struct StateStore {
    pub(crate) data_root: PathBuf,
}

#[derive(Debug, Clone)]
pub struct InitializedRun {
    pub supervisor_credential: Credential,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CurrentToken {
    pub sequence: u64,
    pub owner_role_instance_id: String,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReconciliationResult {
    pub status: String,
    pub receipt_id: String,
    pub canonical_run_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MethodAdoptionResult {
    pub status: String,
    pub receipt_id: String,
    pub run_id: String,
    pub effective_version: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeliveryStartResult {
    pub status: String,
    pub runtime_revision: u64,
    pub token: CurrentToken,
    pub event_id: String,
    pub message_id: String,
}

impl StateStore {
    pub fn new(data_root: impl AsRef<Path>) -> Self {
        Self {
            data_root: data_root.as_ref().to_path_buf(),
        }
    }

    pub fn init_run(&self, request: InitRunRequest) -> Result<InitializedRun, StateError> {
        validate_linear_plan(&request)?;
        validate_engineering_role_binding(&request.supervisor, &request.supervisor_endpoint)?;
        let snapshot = serde_json::to_string(&request)?;
        let payload_sha256 = sha256_hex(snapshot.as_bytes());
        self.with_immediate_transaction(|transaction| {
            let exists: Option<i64> = transaction
                .query_row(
                    "SELECT 1 FROM runs WHERE run_id=?1",
                    [&request.run_id],
                    |row| row.get(0),
                )
                .optional()?;
            if exists.is_some() {
                return Err(StateError::RunAlreadyExists(request.run_id.clone()));
            }

            if let Some(predecessor_run_id) = request.predecessor_run_id.as_deref() {
                let predecessor: Option<(String, String)> = transaction
                    .query_row(
                        "SELECT project_id, closure_state FROM runs WHERE run_id=?1",
                        [predecessor_run_id],
                        |row| Ok((row.get(0)?, row.get(1)?)),
                    )
                    .optional()?;
                if predecessor.as_ref()
                    != Some(&(request.project.project_id.clone(), "open".to_string()))
                {
                    return Err(StateError::InvalidPlan(
                        "predecessor must be an open Run in the same project".into(),
                    ));
                }
            }

            transaction.execute(
                "INSERT INTO projects (project_id, name, repository_url, last_known_path, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5)
                 ON CONFLICT(project_id) DO UPDATE SET
                   name=excluded.name,
                   repository_url=excluded.repository_url,
                   last_known_path=excluded.last_known_path",
                params![
                    request.project.project_id,
                    request.project.name,
                    request.project.repository_url,
                    request.project.last_known_path,
                    request.occurred_at
                ],
            )?;
            let fallback_name = request
                .go_nodes
                .first()
                .map(|go| go.title.trim())
                .filter(|title| !title.is_empty())
                .unwrap_or(request.goal.as_str());
            let run_name = request
                .run_name
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .unwrap_or(fallback_name);
            let run_description = request
                .run_description
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .unwrap_or(request.goal.as_str());
            let source_kind = request.source_kind.as_deref().unwrap_or("solo");
            transaction.execute(
                "INSERT INTO runs
                 (run_id, project_id, run_name, run_description, slk_version, origin_slk_version,
                  source_kind, source_project_name, goal, boundaries_json, state,
                  current_plan_revision, closure_state, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?5, ?6, ?7, ?8, ?9, 'active', 1, 'open', ?10)",
                params![
                    request.run_id,
                    request.project.project_id,
                    run_name,
                    run_description,
                    env!("CARGO_PKG_VERSION"),
                    source_kind,
                    request.source_project_name,
                    request.goal,
                    serde_json::to_string(&request.boundaries)?,
                    request.occurred_at
                ],
            )?;
            insert_role_instance(
                transaction,
                &request.run_id,
                &request.supervisor,
                &request.occurred_at,
            )?;
            insert_endpoint(
                transaction,
                &request.run_id,
                &request.supervisor.role_instance_id,
                &request.supervisor_endpoint,
                &request.occurred_at,
            )?;
            transaction.execute(
                "INSERT INTO plan_revisions (run_id, revision, author_role_instance_id, snapshot_json, reason, created_at)
                 VALUES (?1, 1, ?2, ?3, 'initial plan', ?4)",
                params![
                    request.run_id,
                    request.supervisor.role_instance_id,
                    snapshot,
                    request.occurred_at
                ],
            )?;
            for go in &request.go_nodes {
                transaction.execute(
                    "INSERT INTO go_nodes (run_id, go_id, ordinal, title, objective, state)
                     VALUES (?1, ?2, ?3, ?4, ?5, 'planned')",
                    params![
                        request.run_id,
                        go.go_id,
                        go.ordinal,
                        go.title,
                        go.objective
                    ],
                )?;
            }
            for cell in &request.cell_nodes {
                transaction.execute(
                    "INSERT INTO cell_nodes (run_id, go_id, cell_id, ordinal, title, objective, state)
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'planned')",
                    params![
                        request.run_id,
                        cell.go_id,
                        cell.cell_id,
                        cell.ordinal,
                        cell.title,
                        cell.objective
                    ],
                )?;
            }

            let issued = issue_credential(
                transaction,
                &request.run_id,
                &request.supervisor.role_instance_id,
                &request.occurred_at,
            )?;
            transaction.execute(
                "INSERT INTO token_events
                 (event_id, run_id, token_sequence, to_role_instance_id, endpoint_version, event_type, payload_type, payload_sha256, occurred_at)
                 VALUES (?1, ?2, 1, ?3, ?4, 'TOKEN_CREATED', 'RUN_INITIALIZATION', ?5, ?6)",
                params![
                    format!("token-created-{}", request.run_id),
                    request.run_id,
                    request.supervisor.role_instance_id,
                    request.supervisor_endpoint.endpoint_version,
                    payload_sha256,
                    request.occurred_at
                ],
            )?;
            transaction.execute(
                "INSERT INTO work_events
                 (event_id, run_id, plan_revision, author_role_instance_id, event_type, details_json, occurred_at)
                 VALUES (?1, ?2, 1, ?3, 'RUN_INITIALIZED', ?4, ?5)",
                params![
                    format!("run-initialized-{}", request.run_id),
                    request.run_id,
                    request.supervisor.role_instance_id,
                    serde_json::to_string(&request.boundaries)?,
                    request.occurred_at
                ],
            )?;
            transaction.execute(
                "INSERT INTO run_runtime_snapshots
                 (run_id, runtime_revision, plan_revision, token_sequence,
                  token_holder_role_instance_id, latest_event_id, latest_message_id,
                  method_version, overwatcher_binding_revision, overwatcher_status, committed_at)
                 VALUES (?1, 1, 1, 1, ?2, ?3, NULL, ?4, NULL, NULL, ?5)",
                params![
                    request.run_id,
                    request.supervisor.role_instance_id,
                    format!("run-initialized-{}", request.run_id),
                    env!("CARGO_PKG_VERSION"),
                    request.occurred_at
                ],
            )?;
            if let Some(predecessor_run_id) = request.predecessor_run_id.as_deref() {
                transaction.execute(
                    "UPDATE runs SET state='archived', closure_state='superseded',
                         closed_at=?2, archive_reason='superseded', archived_at=?2,
                         superseded_by_run_id=?3
                     WHERE run_id=?1 AND closure_state='open'",
                    params![predecessor_run_id, request.occurred_at, request.run_id],
                )?;
                transaction.execute(
                    "INSERT INTO run_lineage
                     (successor_run_id, predecessor_run_id, created_at)
                     VALUES (?1, ?2, ?3)",
                    params![request.run_id, predecessor_run_id, request.occurred_at],
                )?;
            }
            Ok(InitializedRun {
                supervisor_credential: issued.credential,
            })
        })
    }

    pub fn run_state_snapshot(&self, run_id: &str) -> Result<RunStateSnapshot, StateError> {
        let connection = open_database(&self.data_root)?;
        run_state_snapshot_from(&connection, run_id)
    }

    pub fn reconcile_run_identities(
        &self,
        credential: &Credential,
        request: ReconcileRunIdentitiesRequest,
    ) -> Result<ReconciliationResult, StateError> {
        validate_reconciliation_request(&request)?;
        let payload_json = serde_json::to_string(&request)?;
        let payload_sha256 = sha256_hex(payload_json.as_bytes());
        self.with_immediate_transaction(|transaction| {
            let actor = authorize_role(transaction, &request.canonical_run_id, credential)?;
            if actor.role != Role::Supervisor {
                return Err(StateError::RunAdministrationInvalid(
                    "reconciliation requires the canonical Run's current Supervisor".into(),
                ));
            }

            let existing: Option<String> = transaction
                .query_row(
                    "SELECT payload_sha256 FROM run_identity_reconciliation_receipts
                     WHERE receipt_id=?1",
                    [&request.receipt_id],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(existing_hash) = existing {
                if existing_hash == payload_sha256 {
                    return Ok(ReconciliationResult {
                        status: "IDEMPOTENT_REPLAY".into(),
                        receipt_id: request.receipt_id.clone(),
                        canonical_run_id: request.canonical_run_id.clone(),
                    });
                }
                return Err(StateError::RunAdministrationConflict(
                    request.receipt_id.clone(),
                ));
            }

            let actual_canonical = run_state_snapshot_from(transaction, &request.canonical_run_id)?;
            if actual_canonical != request.canonical_snapshot
                || request.canonical_snapshot.run_id != request.canonical_run_id
                || !snapshot_is_open(&actual_canonical)
            {
                return Err(StateError::RunAdministrationInvalid(
                    "canonical Run snapshot is stale, mismatched, or not open".into(),
                ));
            }

            for source in &request.source_snapshots {
                let actual = run_state_snapshot_from(transaction, &source.run_id)?;
                if actual != *source
                    || actual.project_id != actual_canonical.project_id
                    || !snapshot_is_open(&actual)
                {
                    return Err(StateError::RunAdministrationInvalid(format!(
                        "source Run snapshot is stale, cross-project, or not open: {}",
                        source.run_id
                    )));
                }
            }

            for source in &request.source_snapshots {
                let changed = transaction.execute(
                    "UPDATE runs
                     SET state='archived', closure_state='superseded', closed_at=?2,
                         archive_reason='owner-authorized-identity-reconciliation',
                         archived_at=?2, superseded_by_run_id=?3
                     WHERE run_id=?1 AND state<>'archived' AND closure_state='open'
                       AND archived_at IS NULL AND superseded_by_run_id IS NULL",
                    params![source.run_id, request.occurred_at, request.canonical_run_id],
                )?;
                if changed != 1 {
                    return Err(StateError::RunAdministrationInvalid(format!(
                        "source Run changed during reconciliation: {}",
                        source.run_id
                    )));
                }
            }

            transaction.execute(
                "INSERT INTO run_identity_reconciliation_receipts
                 (receipt_id, canonical_run_id, canonical_snapshot_json,
                  source_snapshots_json, owner_authorization_json, reason,
                  payload_sha256, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    request.receipt_id,
                    request.canonical_run_id,
                    serde_json::to_string(&request.canonical_snapshot)?,
                    serde_json::to_string(&request.source_snapshots)?,
                    serde_json::to_string(&request.owner_authorization)?,
                    request.reason,
                    payload_sha256,
                    request.occurred_at,
                ],
            )?;
            Ok(ReconciliationResult {
                status: "APPLIED".into(),
                receipt_id: request.receipt_id.clone(),
                canonical_run_id: request.canonical_run_id.clone(),
            })
        })
    }

    pub fn adopt_method_contract(
        &self,
        credential: &Credential,
        request: AdoptMethodContractRequest,
    ) -> Result<MethodAdoptionResult, StateError> {
        validate_method_adoption_request(&request)?;
        let payload_json = serde_json::to_string(&request)?;
        let payload_sha256 = sha256_hex(payload_json.as_bytes());
        self.with_immediate_transaction(|transaction| {
            let actor = authorize_role(transaction, &request.run_id, credential)?;
            if actor.role != Role::Supervisor {
                return Err(StateError::RunAdministrationInvalid(
                    "method adoption requires the Run's current Supervisor".into(),
                ));
            }

            let existing: Option<String> = transaction
                .query_row(
                    "SELECT payload_sha256 FROM run_method_adoption_receipts
                     WHERE receipt_id=?1",
                    [&request.receipt_id],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(existing_hash) = existing {
                if existing_hash == payload_sha256 {
                    return Ok(MethodAdoptionResult {
                        status: "IDEMPOTENT_REPLAY".into(),
                        receipt_id: request.receipt_id.clone(),
                        run_id: request.run_id.clone(),
                        effective_version: request.to_version.clone(),
                    });
                }
                return Err(StateError::RunAdministrationConflict(
                    request.receipt_id.clone(),
                ));
            }

            let actual = run_state_snapshot_from(transaction, &request.run_id)?;
            if actual != request.expected_snapshot
                || request.expected_snapshot.run_id != request.run_id
                || actual.slk_version != request.from_version
                || !snapshot_is_open(&actual)
            {
                return Err(StateError::RunAdministrationInvalid(
                    "method adoption snapshot is stale, mismatched, or not open".into(),
                ));
            }

            let reconciliation_count: u64 = transaction.query_row(
                "SELECT COUNT(*) FROM run_identity_reconciliation_receipts
                 WHERE canonical_run_id=?1",
                [&request.run_id],
                |row| row.get(0),
            )?;
            match (
                reconciliation_count > 0,
                request.reconciliation_receipt_id.as_deref(),
            ) {
                (true, Some(receipt_id)) => {
                    let valid: Option<i64> = transaction
                        .query_row(
                            "SELECT 1 FROM run_identity_reconciliation_receipts
                             WHERE receipt_id=?1 AND canonical_run_id=?2",
                            params![receipt_id, request.run_id],
                            |row| row.get(0),
                        )
                        .optional()?;
                    if valid.is_none() {
                        return Err(StateError::RunAdministrationInvalid(
                            "reconciliation receipt does not belong to this canonical Run".into(),
                        ));
                    }
                }
                (true, None) => {
                    return Err(StateError::RunAdministrationInvalid(
                        "a reconciled canonical Run must cite its reconciliation receipt".into(),
                    ));
                }
                (false, Some(_)) => {
                    return Err(StateError::RunAdministrationInvalid(
                        "method adoption cannot cite an unrelated reconciliation receipt".into(),
                    ));
                }
                (false, None) => {}
            }

            let active_overwatcher: Option<(u64, String)> = transaction
                .query_row(
                    "SELECT binding_revision, continuity_state FROM overwatcher_bindings
                     WHERE run_id=?1 AND lifecycle_state='active'",
                    [&request.run_id],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .optional()?;
            if uses_revisioned_runtime_contract(&request.to_version) {
                match (active_overwatcher.as_ref(), request.compatibility.overwatcher) {
                    (None, OverwatcherAssertion::Absent) => {}
                    (Some((binding_revision, continuity)), OverwatcherAssertion::PreservedActive) => {
                        if continuity != "ACTIVE" {
                            return Err(StateError::RunAdministrationInvalid(
                                "PRESERVED_ACTIVE requires an active continuity projection".into(),
                            ));
                        }
                        let cycle: Option<(String, String, String)> = transaction
                            .query_row(
                                "SELECT evidence_refs_json, native_active_session_evidence_ref,
                                        native_liveness
                                 FROM overwatch_cycles
                                 WHERE run_id=?1 AND binding_revision=?2
                                 ORDER BY cycle_sequence DESC LIMIT 1",
                                params![request.run_id, binding_revision],
                                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                            )
                            .optional()?;
                        let Some((evidence_json, native_ref, native_liveness)) = cycle else {
                            return Err(StateError::RunAdministrationInvalid(
                                "PRESERVED_ACTIVE requires one complete prior observation cycle"
                                    .into(),
                            ));
                        };
                        let evidence: Vec<EvidenceReference> =
                            serde_json::from_str(&evidence_json).map_err(|_| {
                                StateError::RunAdministrationInvalid(
                                    "prior observation evidence is not a closed revisioned-runtime-compatible set"
                                        .into(),
                                )
                            })?;
                        if native_liveness != "IN_PROGRESS"
                            || evidence.is_empty()
                            || !evidence.iter().any(|item| item.path == native_ref)
                        {
                            return Err(StateError::RunAdministrationInvalid(
                                "PRESERVED_ACTIVE requires verified native in-progress evidence"
                                    .into(),
                            ));
                        }
                        for reference in &evidence {
                            validate_evidence_reference(reference)?;
                        }
                    }
                    (
                        Some((binding_revision, _)),
                        OverwatcherAssertion::ContinuityRecoveryRequired,
                    ) => {
                        transaction.execute(
                            "UPDATE overwatcher_bindings SET continuity_state='VIOLATION'
                             WHERE run_id=?1 AND binding_revision=?2",
                            params![request.run_id, binding_revision],
                        )?;
                        let incident_id = format!(
                            "continuity-{}-{}",
                            request.run_id, binding_revision
                        );
                        transaction.execute(
                            "INSERT INTO overwatcher_incident_transitions
                             (transition_id, incident_id, run_id, binding_revision,
                              incident_code, state, evidence_path, evidence_sha256, occurred_at)
                             VALUES (?1,?2,?3,?4,'OVERWATCHER_CONTINUITY_VIOLATION','OPEN',?5,?6,?7)",
                            params![
                                format!("incident-open-{}", request.receipt_id),
                                incident_id,
                                request.run_id,
                                binding_revision,
                                format!(
                                    "owner:{}/{}",
                                    request.owner_authorization.source_thread_id,
                                    request.owner_authorization.message_id
                                ),
                                request.owner_authorization.content_sha256,
                                request.occurred_at,
                            ],
                        )?;
                    }
                    _ => {
                        return Err(StateError::RunAdministrationInvalid(
                            "revisioned runtime adoption requires an exact ABSENT, PRESERVED_ACTIVE, or CONTINUITY_RECOVERY_REQUIRED Overwatcher assertion"
                                .into(),
                        ));
                    }
                }
            } else if active_overwatcher.is_some()
                || request.compatibility.overwatcher != OverwatcherAssertion::Absent
            {
                return Err(StateError::RunAdministrationInvalid(
                    "4.2.2 method adoption requires Overwatcher=ABSENT".into(),
                ));
            }

            let changed = transaction.execute(
                "UPDATE runs SET slk_version=?2
                 WHERE run_id=?1 AND slk_version=?3 AND closure_state='open'
                   AND state<>'archived' AND archived_at IS NULL",
                params![request.run_id, request.to_version, request.from_version],
            )?;
            if changed != 1 {
                return Err(StateError::RunAdministrationInvalid(
                    "effective method version changed during adoption".into(),
                ));
            }
            transaction.execute(
                "INSERT INTO run_method_adoption_receipts
                 (receipt_id, run_id, expected_snapshot_json, from_version, to_version,
                  owner_authorization_json, reconciliation_receipt_id,
                  compatibility_json, reason, payload_sha256, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
                params![
                    request.receipt_id,
                    request.run_id,
                    serde_json::to_string(&request.expected_snapshot)?,
                    request.from_version,
                    request.to_version,
                    serde_json::to_string(&request.owner_authorization)?,
                    request.reconciliation_receipt_id,
                    serde_json::to_string(&request.compatibility)?,
                    request.reason,
                    payload_sha256,
                    request.occurred_at,
                ],
            )?;
            if uses_revisioned_runtime_contract(&request.to_version) {
                let snapshot = runtime_snapshot_from(transaction, &request.run_id)?;
                advance_runtime_snapshot(
                    transaction,
                    &request.run_id,
                    &request.receipt_id,
                    snapshot.latest_message_id.as_deref(),
                    &request.occurred_at,
                )?;
            }
            Ok(MethodAdoptionResult {
                status: "APPLIED".into(),
                receipt_id: request.receipt_id.clone(),
                run_id: request.run_id.clone(),
                effective_version: request.to_version.clone(),
            })
        })
    }

    pub fn bind_overwatcher(
        &self,
        credential: &Credential,
        request: BindOverwatcherRequest,
    ) -> Result<IssuedCredential, StateError> {
        if request.identity.role != Role::Overwatcher {
            return Err(StateError::OverwatcherBindingInvalid(
                "the bound identity must have role=overwatcher".into(),
            ));
        }
        if !valid_identifier(&request.event_id)
            || !valid_identifier(&request.identity.role_instance_id)
            || request.endpoint.endpoint_version == 0
            || request.reason.trim().is_empty()
            || request.occurred_at.trim().is_empty()
            || request.identity.agent_runtime.trim().is_empty()
            || request.identity.provider.trim().is_empty()
            || request.identity.model.trim().is_empty()
            || request.identity.reasoning.trim().is_empty()
            || request.identity.session_id.trim().is_empty()
            || request.identity.session_id != request.endpoint.session_id
            || request.endpoint.host_identity.trim().is_empty()
            || request.endpoint.transport_adapter.trim().is_empty()
            || !(180..=300).contains(&request.cadence_seconds)
            || request.foreground_turn_id.trim().is_empty()
            || request.native_active_session_evidence_ref.trim().is_empty()
        {
            return Err(StateError::OverwatcherBindingInvalid(
                "identity, exact endpoint, 180-300 second foreground active turn, native evidence, and Supervisor reason are required".into(),
            ));
        }

        self.with_immediate_transaction(|transaction| {
            let actor = authorize_role(transaction, &request.run_id, credential)?;
            if actor.role != Role::Supervisor {
                return Err(StateError::OverwatcherBindingNotAuthorized);
            }
            let run_contract: (String, String, String, Option<String>) = transaction.query_row(
                "SELECT slk_version, state, closure_state, archived_at
                 FROM runs WHERE run_id=?1",
                [&request.run_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )?;
            if !matches!(run_contract.0.as_str(), "4.2.1" | "4.2.2" | "4.2.3" | "4.2.4")
                || run_contract.1 == "archived"
                || run_contract.2 != "open"
                || run_contract.3.is_some()
            {
                return Err(StateError::OverwatcherBindingInvalid(
                    "active Overwatcher requires an open Run with a supported effective SLK contract"
                        .into(),
                ));
            }
            let binding_revision = if request.binding_revision == 0 {
                1
            } else {
                request.binding_revision
            };
            let canonical_task_id = if request.canonical_task_id.trim().is_empty() {
                request.identity.session_id.clone()
            } else {
                request.canonical_task_id.clone()
            };
            if uses_revisioned_runtime_contract(&run_contract.0)
                && (binding_revision != 1 || !valid_identifier(&canonical_task_id))
            {
                return Err(StateError::OverwatcherBindingInvalid(
                    "revisioned SLK runtime requires binding_revision=1 and one canonical task identity".into(),
                ));
            }
            let already_bound: Option<i64> = transaction
                .query_row(
                    "SELECT 1 FROM overwatcher_bindings WHERE run_id=?1",
                    [&request.run_id],
                    |row| row.get(0),
                )
                .optional()?;
            if already_bound.is_some() {
                return Err(StateError::OverwatcherAlreadyBound);
            }
            let reused_session: Option<i64> = transaction
                .query_row(
                    "SELECT 1 FROM overwatcher_bindings WHERE session_id=?1",
                    [&request.identity.session_id],
                    |row| row.get(0),
                )
                .optional()?;
            if reused_session.is_some() {
                return Err(StateError::OverwatcherSessionReused);
            }
            let identity_collision: Option<i64> = transaction
                .query_row(
                    "SELECT 1 FROM role_instances WHERE role_instance_id=?1",
                    [&request.identity.role_instance_id],
                    |row| row.get(0),
                )
                .optional()?;
            if identity_collision.is_some() {
                return Err(StateError::OverwatcherBindingInvalid(
                    "Overwatcher role_instance_id must be independent".into(),
                ));
            }

            let material = new_credential_material();
            transaction.execute(
                "INSERT INTO overwatcher_bindings
                 (run_id, role_instance_id, agent_runtime, provider, model, reasoning,
                  session_id, endpoint_version, transport_adapter, host_identity,
                  native_address_json, bound_by_role_instance_id, binding_reason,
                  credential_id, credential_sha256, credential_state,
                  lifecycle_state, bound_at, observation_mode, cadence_seconds,
                  foreground_turn_id, native_active_session_evidence_ref,
                  binding_revision, canonical_task_id, continuity_state)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12,
                         ?13, ?14, ?15, 'active', 'active', ?16, ?17, ?18, ?19, ?20,
                         ?21, ?22, 'ACTIVE')",
                params![
                    request.run_id,
                    request.identity.role_instance_id,
                    request.identity.agent_runtime,
                    request.identity.provider,
                    request.identity.model,
                    request.identity.reasoning,
                    request.identity.session_id,
                    request.endpoint.endpoint_version,
                    request.endpoint.transport_adapter,
                    request.endpoint.host_identity,
                    serde_json::to_string(&request.endpoint.native_address)?,
                    actor.role_instance_id,
                    request.reason,
                    material.credential_id,
                    material.credential_sha256,
                    request.occurred_at,
                    request.observation_mode.as_str(),
                    request.cadence_seconds,
                    request.foreground_turn_id,
                    request.native_active_session_evidence_ref,
                    binding_revision,
                    canonical_task_id,
                ],
            )?;
            transaction.execute(
                "INSERT INTO work_events
                 (event_id, run_id, plan_revision, author_role_instance_id, event_type,
                  details_json, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, 'OVERWATCHER_BOUND', ?5, ?6)",
                params![
                    request.event_id,
                    request.run_id,
                    current_plan_revision(transaction, &request.run_id)?,
                    actor.role_instance_id,
                    serde_json::to_string(&serde_json::json!({
                        "overwatcher_role_instance_id": request.identity.role_instance_id,
                        "endpoint_version": request.endpoint.endpoint_version,
                        "session_id": request.endpoint.session_id,
                        "observation_mode": request.observation_mode.as_str(),
                        "cadence_seconds": request.cadence_seconds,
                        "foreground_turn_id": request.foreground_turn_id,
                        "native_active_session_evidence_ref": request.native_active_session_evidence_ref,
                        "binding_revision": binding_revision,
                        "canonical_task_id": canonical_task_id,
                        "reason": request.reason,
                    }))?,
                    request.occurred_at,
                ],
            )?;
            if uses_revisioned_runtime_contract(&run_contract.0) {
                let runtime_revision = advance_runtime_snapshot(
                    transaction,
                    &request.run_id,
                    &request.event_id,
                    None,
                    &request.occurred_at,
                )?;
                transaction.execute(
                    "INSERT INTO overwatcher_binding_transitions
                     (transition_id, run_id, binding_revision, transition_type,
                      runtime_revision, evidence_ref, occurred_at)
                     VALUES (?1,?2,?3,'BOUND',?4,?5,?6)",
                    params![
                        format!("binding-transition-{}", request.event_id),
                        request.run_id,
                        binding_revision,
                        runtime_revision,
                        request.native_active_session_evidence_ref,
                        request.occurred_at,
                    ],
                )?;
            }
            Ok(IssuedCredential {
                credential_id: material.credential_id,
                credential: material.credential,
            })
        })
    }

    pub fn register_role(
        &self,
        credential: &Credential,
        request: RegisterRoleRequest,
    ) -> Result<IssuedCredential, StateError> {
        validate_engineering_role_binding(&request.identity, &request.endpoint)?;
        self.with_immediate_transaction(|transaction| {
            let actor = authorize_event(
                transaction,
                &request.run_id,
                credential,
                EventType::RoleRegistered,
            )?;
            let authorized = matches!(
                (actor.role, request.identity.role),
                (Role::Supervisor, Role::Checker) | (Role::Checker, Role::Worker)
            );
            if !authorized {
                return Err(StateError::RoleCreationNotAuthorized {
                    actor: actor.role,
                    target: request.identity.role,
                });
            }
            insert_role_instance(
                transaction,
                &request.run_id,
                &request.identity,
                &request.occurred_at,
            )?;
            insert_endpoint(
                transaction,
                &request.run_id,
                &request.identity.role_instance_id,
                &request.endpoint,
                &request.occurred_at,
            )?;
            let issued = issue_credential(
                transaction,
                &request.run_id,
                &request.identity.role_instance_id,
                &request.occurred_at,
            )?;
            let revision = current_plan_revision(transaction, &request.run_id)?;
            transaction.execute(
                "INSERT INTO work_events
                 (event_id, run_id, plan_revision, author_role_instance_id, event_type, details_json, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, 'ROLE_REGISTERED', ?5, ?6)",
                params![
                    request.event_id,
                    request.run_id,
                    revision,
                    actor.role_instance_id,
                    serde_json::to_string(&request.identity)?,
                    request.occurred_at
                ],
            )?;
            advance_runtime_snapshot_if_revisioned(
                transaction,
                &request.run_id,
                &request.event_id,
                &request.occurred_at,
            )?;
            Ok(issued)
        })
    }

    pub fn handoff_token(
        &self,
        credential: &Credential,
        request: TokenHandoffRequest,
    ) -> Result<CurrentToken, StateError> {
        self.with_immediate_transaction(|transaction| {
            let method_version: String = transaction
                .query_row(
                    "SELECT slk_version FROM runs WHERE run_id=?1",
                    [&request.run_id],
                    |row| row.get(0),
                )
                .optional()?
                .ok_or_else(|| StateError::RunNotFound(request.run_id.clone()))?;
            if uses_revisioned_runtime_contract(&method_version) {
                return Err(StateError::LegacyHandoffForbidden);
            }
            let actor = authorize_event(
                transaction,
                &request.run_id,
                credential,
                EventType::TokenHandedOff,
            )?;
            validate_bound_overwatcher_active(
                transaction,
                &request.run_id,
                &request.occurred_at,
            )?;
            let current = current_token_from(transaction, &request.run_id)?;
            if request.token_sequence <= current.sequence {
                return Err(StateError::TokenSequenceConflict {
                    requested: request.token_sequence,
                    current: current.sequence,
                });
            }
            if request.token_sequence != current.sequence + 1 {
                return Err(StateError::TokenSequenceGap {
                    requested: request.token_sequence,
                    expected: current.sequence + 1,
                });
            }
            if actor.role_instance_id != request.from_role_instance_id
                || current.owner_role_instance_id != request.from_role_instance_id
            {
                return Err(StateError::TokenOwnerMismatch {
                    requested_owner: request.from_role_instance_id.clone(),
                    current_owner: current.owner_role_instance_id,
                });
            }
            let endpoint_exists: Option<i64> = transaction
                .query_row(
                    "SELECT 1 FROM role_endpoints
                     WHERE run_id=?1 AND role_instance_id=?2 AND endpoint_version=?3 AND state='active'",
                    params![
                        request.run_id,
                        request.to_role_instance_id,
                        request.endpoint_version
                    ],
                    |row| row.get(0),
                )
                .optional()?;
            if endpoint_exists.is_none() {
                return Err(StateError::EndpointNotCurrent);
            }
            let target_role_text: String = transaction.query_row(
                "SELECT role FROM role_instances
                 WHERE run_id=?1 AND role_instance_id=?2 AND lifecycle='active'",
                params![request.run_id, request.to_role_instance_id],
                |row| row.get(0),
            )?;
            let target_role = Role::parse(&target_role_text)
                .ok_or_else(|| StateError::StoredRoleInvalid(target_role_text.clone()))?;
            if !valid_token_handoff_route(transaction, &request, actor.role, target_role)? {
                return Err(StateError::InvalidTokenRoute {
                    from: actor.role,
                    to: target_role,
                });
            }
            transaction.execute(
                "INSERT INTO token_events
                 (event_id, run_id, token_sequence, from_role_instance_id, to_role_instance_id,
                  go_id, cell_id, message_id, endpoint_version, event_type, payload_type,
                  payload_sha256, payload_location, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, 'TOKEN_HANDED_OFF', ?10, ?11, ?12, ?13)",
                params![
                    request.event_id,
                    request.run_id,
                    request.token_sequence,
                    request.from_role_instance_id,
                    request.to_role_instance_id,
                    request.go_id,
                    request.cell_id,
                    request.message_id,
                    request.endpoint_version,
                    request.payload_type,
                    request.payload_sha256,
                    request.payload_location,
                    request.occurred_at
                ],
            )?;
            current_token_from(transaction, &request.run_id)
        })
    }

    pub fn commit_delivery_start(
        &self,
        credential: &Credential,
        request: CommitDeliveryStartRequest,
    ) -> Result<DeliveryStartResult, StateError> {
        validate_delivery_start_request(&request)?;
        let request_json = serde_json::to_string(&request)?;
        let request_sha256 = sha256_hex(request_json.as_bytes());
        let evidence_path = Path::new(&request.start_evidence.stored_path);
        if !evidence_path.is_absolute() || !evidence_path.is_file() {
            return Err(StateError::EvidenceInvalid(
                "transport start evidence must be an existing absolute file".into(),
            ));
        }
        let evidence_bytes = fs::read(evidence_path)?;
        if sha256_hex(&evidence_bytes) != request.start_evidence.sha256 {
            return Err(StateError::EvidenceInvalid(
                "transport start evidence hash does not match stored bytes".into(),
            ));
        }

        self.with_immediate_transaction(|transaction| {
            let existing: Option<String> = transaction
                .query_row(
                    "SELECT request_sha256 FROM transport_start_receipts
                     WHERE transport_receipt_id=?1",
                    [&request.transport_receipt_id],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(existing_sha256) = existing {
                if existing_sha256 != request_sha256 {
                    return Err(StateError::TransportStartConflict(
                        request.transport_receipt_id.clone(),
                    ));
                }
                return delivery_start_result_from(
                    transaction,
                    &request.run_id,
                    &request.event_id,
                    &request.message_id,
                    "IDEMPOTENT_REPLAY",
                );
            }

            let method_version: String = transaction
                .query_row(
                    "SELECT slk_version FROM runs WHERE run_id=?1",
                    [&request.run_id],
                    |row| row.get(0),
                )
                .optional()?
                .ok_or_else(|| StateError::RunNotFound(request.run_id.clone()))?;
            if !uses_revisioned_runtime_contract(&method_version) {
                return Err(StateError::RunAdministrationInvalid(
                    "commit-delivery-start requires a revisioned SLK runtime contract".into(),
                ));
            }
            let actor = authorize_event(
                transaction,
                &request.run_id,
                credential,
                EventType::TransportStarted,
            )?;
            validate_bound_overwatcher_active(transaction, &request.run_id, &request.occurred_at)?;
            if actor.role_instance_id != request.from_role_instance_id {
                return Err(StateError::RoleInstanceMismatch);
            }
            let plan_revision = current_plan_revision(transaction, &request.run_id)?;
            if request.plan_revision != plan_revision {
                return Err(StateError::PlanRevisionMismatch {
                    requested: request.plan_revision,
                    current: plan_revision,
                });
            }
            let runtime_revision = current_runtime_revision(transaction, &request.run_id)?;
            if request.expected_runtime_revision != runtime_revision {
                return Err(StateError::RuntimeRevisionMismatch {
                    requested: request.expected_runtime_revision,
                    current: runtime_revision,
                });
            }
            let current = current_token_from(transaction, &request.run_id)?;
            if current.owner_role_instance_id != request.from_role_instance_id {
                return Err(StateError::TokenOwnerMismatch {
                    requested_owner: request.from_role_instance_id.clone(),
                    current_owner: current.owner_role_instance_id,
                });
            }
            if request.token_sequence <= current.sequence {
                return Err(StateError::TokenSequenceConflict {
                    requested: request.token_sequence,
                    current: current.sequence,
                });
            }
            if request.token_sequence != current.sequence + 1 {
                return Err(StateError::TokenSequenceGap {
                    requested: request.token_sequence,
                    expected: current.sequence + 1,
                });
            }
            let endpoint_exists: Option<i64> = transaction
                .query_row(
                    "SELECT 1 FROM role_endpoints
                     WHERE run_id=?1 AND role_instance_id=?2 AND endpoint_version=?3
                       AND state='active'",
                    params![
                        request.run_id,
                        request.to_role_instance_id,
                        request.endpoint_version
                    ],
                    |row| row.get(0),
                )
                .optional()?;
            if endpoint_exists.is_none() {
                return Err(StateError::EndpointNotCurrent);
            }
            let target_role_text: String = transaction.query_row(
                "SELECT role FROM role_instances
                 WHERE run_id=?1 AND role_instance_id=?2 AND lifecycle='active'",
                params![request.run_id, request.to_role_instance_id],
                |row| row.get(0),
            )?;
            let target_role = Role::parse(&target_role_text)
                .ok_or_else(|| StateError::StoredRoleInvalid(target_role_text.clone()))?;
            let route = TokenHandoffRequest {
                event_id: request.event_id.clone(),
                message_id: request.message_id.clone(),
                run_id: request.run_id.clone(),
                go_id: request.go_id.clone(),
                cell_id: request.cell_id.clone(),
                token_sequence: request.token_sequence,
                from_role_instance_id: request.from_role_instance_id.clone(),
                to_role_instance_id: request.to_role_instance_id.clone(),
                endpoint_version: request.endpoint_version,
                payload_type: request.payload_type.clone(),
                payload_sha256: request.payload_sha256.clone(),
                payload_location: Some(request.start_evidence.stored_path.clone()),
                occurred_at: request.occurred_at.clone(),
            };
            if !valid_token_handoff_route(transaction, &route, actor.role, target_role)? {
                return Err(StateError::InvalidTokenRoute {
                    from: actor.role,
                    to: target_role,
                });
            }

            let next_runtime_revision = runtime_revision + 1;
            transaction.execute(
                "INSERT INTO transport_start_receipts
                 (transport_receipt_id, run_id, event_id, message_id, go_id, cell_id,
                  attempt, plan_revision, runtime_revision, token_sequence,
                  from_role_instance_id, to_role_instance_id, endpoint_version,
                  payload_type, payload_sha256, evidence_id, evidence_path,
                  evidence_sha256, endpoint_sha256, envelope_sha256, native_status,
                  request_sha256, occurred_at)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,
                         ?16,?17,?18,?19,?20,'STARTED',?21,?22)",
                params![
                    request.transport_receipt_id,
                    request.run_id,
                    request.event_id,
                    request.message_id,
                    request.go_id,
                    request.cell_id,
                    request.attempt,
                    request.plan_revision,
                    next_runtime_revision,
                    request.token_sequence,
                    request.from_role_instance_id,
                    request.to_role_instance_id,
                    request.endpoint_version,
                    request.payload_type,
                    request.payload_sha256,
                    request.start_evidence.evidence_id,
                    request.start_evidence.stored_path,
                    request.start_evidence.sha256,
                    request.start_evidence.endpoint_sha256,
                    request.start_evidence.envelope_sha256,
                    request_sha256,
                    request.occurred_at,
                ],
            )?;
            transaction.execute(
                "INSERT INTO token_events
                 (event_id, run_id, token_sequence, from_role_instance_id,
                  to_role_instance_id, go_id, cell_id, message_id, endpoint_version,
                  event_type, payload_type, payload_sha256, payload_location, occurred_at)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,'TOKEN_HANDED_OFF',?10,?11,?12,?13)",
                params![
                    format!("token-start-{}", request.transport_receipt_id),
                    request.run_id,
                    request.token_sequence,
                    request.from_role_instance_id,
                    request.to_role_instance_id,
                    request.go_id,
                    request.cell_id,
                    request.message_id,
                    request.endpoint_version,
                    request.payload_type,
                    request.payload_sha256,
                    request.start_evidence.stored_path,
                    request.occurred_at,
                ],
            )?;
            transaction.execute(
                "INSERT INTO work_events
                 (event_id, run_id, go_id, cell_id, attempt, plan_revision,
                  author_role_instance_id, event_type, details_json, occurred_at)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,'TRANSPORT_STARTED',?8,?9)",
                params![
                    request.event_id,
                    request.run_id,
                    request.go_id,
                    request.cell_id,
                    request.attempt,
                    request.plan_revision,
                    request.from_role_instance_id,
                    serde_json::to_string(&serde_json::json!({
                        "transport_receipt_id": request.transport_receipt_id,
                        "message_id": request.message_id,
                        "start_evidence_id": request.start_evidence.evidence_id,
                        "start_evidence_sha256": request.start_evidence.sha256,
                        "endpoint_sha256": request.start_evidence.endpoint_sha256,
                        "envelope_sha256": request.start_evidence.envelope_sha256,
                    }))?,
                    request.occurred_at,
                ],
            )?;
            transaction.execute(
                "UPDATE runs SET current_runtime_revision=?2 WHERE run_id=?1",
                params![request.run_id, next_runtime_revision],
            )?;
            insert_runtime_snapshot(
                transaction,
                &request.run_id,
                next_runtime_revision,
                &request.event_id,
                Some(&request.message_id),
                &request.occurred_at,
            )?;
            delivery_start_result_from(
                transaction,
                &request.run_id,
                &request.event_id,
                &request.message_id,
                "COMMITTED",
            )
        })
    }

    pub fn revise_plan(
        &self,
        credential: &Credential,
        request: RevisePlanRequest,
    ) -> Result<u32, StateError> {
        self.with_immediate_transaction(|transaction| {
            let actor = authorize_event(
                transaction,
                &request.run_id,
                credential,
                EventType::PlanRevised,
            )?;
            let previous = current_plan_revision(transaction, &request.run_id)?;
            let revision = previous + 1;
            transaction.execute(
                "INSERT INTO plan_revisions
                 (run_id, revision, author_role_instance_id, snapshot_json, reason, previous_revision, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    request.run_id,
                    revision,
                    actor.role_instance_id,
                    serde_json::to_string(&request.snapshot)?,
                    request.reason,
                    previous,
                    request.occurred_at
                ],
            )?;
            transaction.execute(
                "UPDATE runs SET current_plan_revision=?2 WHERE run_id=?1",
                params![request.run_id, revision],
            )?;
            transaction.execute(
                "INSERT INTO work_events
                 (event_id, run_id, plan_revision, author_role_instance_id, event_type, details_json, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, 'PLAN_REVISED', ?5, ?6)",
                params![
                    request.event_id,
                    request.run_id,
                    revision,
                    actor.role_instance_id,
                    serde_json::to_string(&serde_json::json!({
                        "reason": request.reason,
                        "previous_revision": previous
                    }))?,
                    request.occurred_at
                ],
            )?;
            advance_runtime_snapshot_if_revisioned(
                transaction,
                &request.run_id,
                &request.event_id,
                &request.occurred_at,
            )?;
            Ok(revision)
        })
    }

    pub fn replace_role(
        &self,
        credential: &Credential,
        request: ReplaceRoleRequest,
    ) -> Result<IssuedCredential, StateError> {
        validate_engineering_role_binding(&request.replacement, &request.endpoint)?;
        self.with_immediate_transaction(|transaction| {
            let actor = authorize_event(
                transaction,
                &request.run_id,
                credential,
                EventType::RoleReplaced,
            )?;
            let old_role_text: String = transaction
                .query_row(
                    "SELECT role FROM role_instances
                     WHERE run_id=?1 AND role_instance_id=?2 AND lifecycle='active'",
                    params![request.run_id, request.old_role_instance_id],
                    |row| row.get(0),
                )
                .optional()?
                .ok_or_else(|| {
                    StateError::RoleInstanceNotCurrent(request.old_role_instance_id.clone())
                })?;
            let old_role = Role::parse(&old_role_text)
                .ok_or_else(|| StateError::StoredRoleInvalid(old_role_text.clone()))?;
            let authorized = matches!(
                (actor.role, old_role),
                (Role::Supervisor, Role::Checker) | (Role::Checker, Role::Worker)
            );
            if !authorized || request.replacement.role != old_role {
                return Err(StateError::RoleCreationNotAuthorized {
                    actor: actor.role,
                    target: request.replacement.role,
                });
            }

            let credential_id: String = transaction.query_row(
                "SELECT credential_id FROM role_credentials
                 WHERE role_instance_id=?1 AND state='active'",
                [&request.old_role_instance_id],
                |row| row.get(0),
            )?;
            revoke_credential(transaction, &credential_id, &request.occurred_at)?;
            transaction.execute(
                "UPDATE role_endpoints SET state='retired', retired_at=?2
                 WHERE role_instance_id=?1 AND state='active'",
                params![request.old_role_instance_id, request.occurred_at],
            )?;
            transaction.execute(
                "UPDATE role_instances SET lifecycle='replaced', exited_at=?2
                 WHERE role_instance_id=?1",
                params![request.old_role_instance_id, request.occurred_at],
            )?;
            insert_role_instance(
                transaction,
                &request.run_id,
                &request.replacement,
                &request.occurred_at,
            )?;
            transaction.execute(
                "UPDATE role_instances SET predecessor_role_instance_id=?2, takeover_at=?3
                 WHERE role_instance_id=?1",
                params![
                    request.replacement.role_instance_id,
                    request.old_role_instance_id,
                    request.occurred_at
                ],
            )?;
            transaction.execute(
                "UPDATE role_instances SET successor_role_instance_id=?2
                 WHERE role_instance_id=?1",
                params![
                    request.old_role_instance_id,
                    request.replacement.role_instance_id
                ],
            )?;
            insert_endpoint(
                transaction,
                &request.run_id,
                &request.replacement.role_instance_id,
                &request.endpoint,
                &request.occurred_at,
            )?;
            let issued = issue_credential(
                transaction,
                &request.run_id,
                &request.replacement.role_instance_id,
                &request.occurred_at,
            )?;
            let revision = current_plan_revision(transaction, &request.run_id)?;
            transaction.execute(
                "INSERT INTO work_events
                 (event_id, run_id, plan_revision, author_role_instance_id, event_type, details_json, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, 'ROLE_REPLACED', ?5, ?6)",
                params![
                    request.event_id,
                    request.run_id,
                    revision,
                    actor.role_instance_id,
                    serde_json::to_string(&serde_json::json!({
                        "old_role_instance_id": request.old_role_instance_id,
                        "new_role_instance_id": request.replacement.role_instance_id,
                        "reason": request.reason
                    }))?,
                    request.occurred_at
                ],
            )?;
            advance_runtime_snapshot_if_revisioned(
                transaction,
                &request.run_id,
                &request.event_id,
                &request.occurred_at,
            )?;
            Ok(issued)
        })
    }

    pub fn rebind_session(
        &self,
        credential: &Credential,
        request: RebindSessionRequest,
    ) -> Result<(), StateError> {
        self.with_immediate_transaction(|transaction| {
            let actor = authorize_event(
                transaction,
                &request.run_id,
                credential,
                EventType::TokenHandedOff,
            )?;
            let target_role_text: String = transaction
                .query_row(
                    "SELECT role FROM role_instances
                     WHERE run_id=?1 AND role_instance_id=?2 AND lifecycle='active'",
                    params![request.run_id, request.role_instance_id],
                    |row| row.get(0),
                )
                .optional()?
                .ok_or_else(|| {
                    StateError::RoleInstanceNotCurrent(request.role_instance_id.clone())
                })?;
            let target_role = Role::parse(&target_role_text)
                .ok_or_else(|| StateError::StoredRoleInvalid(target_role_text.clone()))?;
            let authorized = matches!(
                (actor.role, target_role),
                (Role::Supervisor, Role::Checker) | (Role::Checker, Role::Worker)
            ) || (actor.role == Role::Supervisor
                && target_role == Role::Supervisor
                && actor.role_instance_id == request.role_instance_id);
            if !authorized {
                return Err(StateError::SessionReboundNotAuthorized {
                    actor: actor.role,
                    target: target_role,
                });
            }
            validate_engineering_endpoint_binding(target_role, &request.endpoint)?;

            let current_version: u32 = transaction.query_row(
                "SELECT endpoint_version FROM role_endpoints
                 WHERE run_id=?1 AND role_instance_id=?2 AND state='active'",
                params![request.run_id, request.role_instance_id],
                |row| row.get(0),
            )?;
            if request.endpoint.endpoint_version != current_version + 1 {
                return Err(StateError::EndpointNotCurrent);
            }
            transaction.execute(
                "UPDATE role_endpoints SET state='retired', retired_at=?3
                 WHERE run_id=?1 AND role_instance_id=?2 AND state='active'",
                params![
                    request.run_id,
                    request.role_instance_id,
                    request.occurred_at
                ],
            )?;
            insert_endpoint(
                transaction,
                &request.run_id,
                &request.role_instance_id,
                &request.endpoint,
                &request.occurred_at,
            )?;
            transaction.execute(
                "UPDATE role_instances SET session_id=?3
                 WHERE run_id=?1 AND role_instance_id=?2 AND lifecycle='active'",
                params![
                    request.run_id,
                    request.role_instance_id,
                    request.endpoint.session_id
                ],
            )?;
            let revision = current_plan_revision(transaction, &request.run_id)?;
            transaction.execute(
                "INSERT INTO work_events
                 (event_id, run_id, plan_revision, author_role_instance_id, event_type,
                  details_json, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, 'SESSION_REBOUND', ?5, ?6)",
                params![
                    request.event_id,
                    request.run_id,
                    revision,
                    actor.role_instance_id,
                    serde_json::to_string(&serde_json::json!({
                        "role_instance_id": request.role_instance_id,
                        "endpoint_version": request.endpoint.endpoint_version,
                        "session_id": request.endpoint.session_id,
                        "reason": request.reason
                    }))?,
                    request.occurred_at
                ],
            )?;
            advance_runtime_snapshot_if_revisioned(
                transaction,
                &request.run_id,
                &request.event_id,
                &request.occurred_at,
            )?;
            Ok(())
        })
    }

    pub fn write_event(
        &self,
        credential: &Credential,
        request: WriteRequest,
    ) -> Result<(), StateError> {
        self.with_immediate_transaction(|transaction| {
            let actor =
                authorize_event(transaction, &request.run_id, credential, request.event_type)?;
            let method_version: String = transaction.query_row(
                "SELECT slk_version FROM runs WHERE run_id=?1",
                [&request.run_id],
                |row| row.get(0),
            )?;
            if method_version == "4.2.4" {
                type ExistingWorkEvent = (
                    String,
                    Option<String>,
                    Option<String>,
                    Option<u32>,
                    u32,
                    String,
                    String,
                    String,
                    Option<String>,
                    String,
                );
                let existing: Option<ExistingWorkEvent> = transaction
                    .query_row(
                        "SELECT run_id, go_id, cell_id, attempt, plan_revision,
                                author_role_instance_id, event_type, details_json,
                                corrects_event_id, occurred_at
                         FROM work_events WHERE event_id=?1",
                        [&request.event_id],
                        |row| {
                            Ok((
                                row.get(0)?,
                                row.get(1)?,
                                row.get(2)?,
                                row.get(3)?,
                                row.get(4)?,
                                row.get(5)?,
                                row.get(6)?,
                                row.get(7)?,
                                row.get(8)?,
                                row.get(9)?,
                            ))
                        },
                    )
                    .optional()?;
                if let Some(existing) = existing {
                    let requested_details = serde_json::to_string(&request.details)?;
                    return if existing
                        == (
                            request.run_id.clone(),
                            request.go_id.clone(),
                            request.cell_id.clone(),
                            request.attempt,
                            request.plan_revision,
                            actor.role_instance_id.clone(),
                            request.event_type.as_str().to_string(),
                            requested_details,
                            request.corrects_event_id.clone(),
                            request.occurred_at.clone(),
                        ) {
                        Ok(())
                    } else {
                        Err(StateError::WorkEventConflict(request.event_id.clone()))
                    };
                }
            }
            if matches!(
                request.event_type,
                EventType::CellDispatched | EventType::ReworkRequested
            ) {
                validate_bound_overwatcher_active(
                    transaction,
                    &request.run_id,
                    &request.occurred_at,
                )?;
            }
            if actor.role_instance_id != request.role_instance_id {
                return Err(StateError::RoleInstanceMismatch);
            }
            let token = current_token_from(transaction, &request.run_id)?;
            if token.owner_role_instance_id != actor.role_instance_id {
                return Err(StateError::TokenOwnerMismatch {
                    requested_owner: actor.role_instance_id,
                    current_owner: token.owner_role_instance_id,
                });
            }
            let current_revision = current_plan_revision(transaction, &request.run_id)?;
            if request.plan_revision != current_revision {
                return Err(StateError::PlanRevisionMismatch {
                    requested: request.plan_revision,
                    current: current_revision,
                });
            }
            if let Some(cell_id) = request.cell_id.as_deref() {
                let cell_exists: Option<i64> = transaction
                    .query_row(
                        "SELECT 1 FROM cell_nodes WHERE run_id=?1 AND cell_id=?2",
                        params![request.run_id, cell_id],
                        |row| row.get(0),
                    )
                    .optional()?;
                if cell_exists.is_none() {
                    return Err(StateError::CellNotFound(cell_id.to_string()));
                }
            }
            if let Some(corrects_event_id) = request.corrects_event_id.as_deref() {
                let target_author: Option<String> = transaction
                    .query_row(
                        "SELECT author_role_instance_id FROM work_events
                         WHERE run_id=?1 AND event_id=?2",
                        params![request.run_id, corrects_event_id],
                        |row| row.get(0),
                    )
                    .optional()?;
                if target_author.as_deref() != Some(actor.role_instance_id.as_str()) {
                    return Err(StateError::CorrectionTargetInvalid(
                        corrects_event_id.to_string(),
                    ));
                }
            }
            transaction.execute(
                "INSERT INTO work_events
                 (event_id, run_id, go_id, cell_id, attempt, plan_revision,
                  author_role_instance_id, event_type, details_json, corrects_event_id, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
                params![
                    request.event_id,
                    request.run_id,
                    request.go_id,
                    request.cell_id,
                    request.attempt,
                    request.plan_revision,
                    actor.role_instance_id,
                    request.event_type.as_str(),
                    serde_json::to_string(&request.details)?,
                    request.corrects_event_id,
                    request.occurred_at
                ],
            )?;
            if let (Some(cell_id), Some(state)) = (
                request.cell_id.as_deref(),
                projected_cell_state(request.event_type),
            ) {
                transaction.execute(
                    "UPDATE cell_nodes SET state=?3 WHERE run_id=?1 AND cell_id=?2",
                    params![request.run_id, cell_id, state],
                )?;
            }
            if request.event_type == EventType::RunSuperseded {
                let successor = request
                    .details
                    .get("superseded_by_run_id")
                    .and_then(serde_json::Value::as_str)
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| {
                        StateError::InvalidPlan(
                            "RUN_SUPERSEDED requires superseded_by_run_id".into(),
                        )
                    })?;
                transaction.execute(
                    "UPDATE runs
                     SET state='archived', closure_state='superseded', closed_at=?2,
                         archive_reason='superseded', archived_at=?2, superseded_by_run_id=?3
                     WHERE run_id=?1",
                    params![request.run_id, request.occurred_at, successor],
                )?;
            }
            if request.event_type == EventType::RunAbandoned {
                transaction.execute(
                    "UPDATE runs
                     SET state='archived', closure_state='abandoned', closed_at=?2,
                         archive_reason='abandoned', archived_at=?2
                     WHERE run_id=?1",
                    params![request.run_id, request.occurred_at],
                )?;
            }
            if request.event_type == EventType::RunClosed {
                transaction.execute(
                    "UPDATE runs
                     SET state='closed', closure_state='closed', closed_at=?2,
                         archive_reason='completed', archived_at=?2
                     WHERE run_id=?1",
                    params![request.run_id, request.occurred_at],
                )?;
            }
            if uses_revisioned_runtime_contract(&method_version) {
                let snapshot = runtime_snapshot_from(transaction, &request.run_id)?;
                advance_runtime_snapshot(
                    transaction,
                    &request.run_id,
                    &request.event_id,
                    snapshot.latest_message_id.as_deref(),
                    &request.occurred_at,
                )?;
            }
            Ok(())
        })
    }

    pub fn record_observation(
        &self,
        credential: &Credential,
        request: OperationalObservationRequest,
    ) -> Result<(), StateError> {
        if !valid_identifier(&request.observation_id)
            || request.plan_revision == 0
            || request.attempt == Some(0)
            || request.evidence_refs.is_empty()
            || request
                .evidence_refs
                .iter()
                .any(|item| item.trim().is_empty())
            || request
                .message_id
                .as_deref()
                .is_some_and(|value| value.trim().is_empty())
            || request
                .related_event_id
                .as_deref()
                .is_some_and(|value| value.trim().is_empty())
            || (request.cell_id.is_some() && request.go_id.is_none())
            || (request.cell_id.is_none() && request.attempt.is_some())
        {
            return Err(StateError::OverwatcherObservationInvalid(
                "closed identity, scope, and evidence are required".into(),
            ));
        }
        let payload_json = serde_json::to_string(&request)?;
        let payload_sha256 = sha256_hex(payload_json.as_bytes());
        self.with_immediate_transaction(|transaction| {
            let overwatcher_role_instance_id =
                authorize_overwatcher(transaction, &request.run_id, credential)?;
            if overwatcher_role_instance_id != request.role_instance_id {
                return Err(StateError::OverwatcherObservationInvalid(
                    "only the bound Overwatcher may author observations".into(),
                ));
            }
            let active_binding: Option<i64> = transaction
                .query_row(
                    "SELECT 1 FROM overwatcher_bindings
                     WHERE run_id=?1 AND role_instance_id=?2 AND lifecycle_state='active'",
                    params![request.run_id, overwatcher_role_instance_id],
                    |row| row.get(0),
                )
                .optional()?;
            if active_binding.is_none() {
                return Err(StateError::OverwatcherObservationInvalid(
                    "the Overwatcher binding is not active".into(),
                ));
            }
            let revision = current_plan_revision(transaction, &request.run_id)?;
            if request.plan_revision != revision {
                return Err(StateError::PlanRevisionMismatch {
                    requested: request.plan_revision,
                    current: revision,
                });
            }
            if let (Some(go_id), Some(cell_id)) =
                (request.go_id.as_deref(), request.cell_id.as_deref())
            {
                let cell_exists: Option<i64> = transaction
                    .query_row(
                        "SELECT 1 FROM cell_nodes
                         WHERE run_id=?1 AND go_id=?2 AND cell_id=?3",
                        params![request.run_id, go_id, cell_id],
                        |row| row.get(0),
                    )
                    .optional()?;
                if cell_exists.is_none() {
                    return Err(StateError::OverwatcherObservationInvalid(
                        "observation CELL scope is not in the current plan".into(),
                    ));
                }
            }
            let existing: Option<String> = transaction
                .query_row(
                    "SELECT payload_sha256 FROM operational_observations
                     WHERE observation_id=?1",
                    [&request.observation_id],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(existing) = existing {
                return if existing == payload_sha256 {
                    Ok(())
                } else {
                    Err(StateError::OverwatcherObservationConflict)
                };
            }
            transaction.execute(
                "INSERT INTO operational_observations
                 (observation_id, run_id, overwatcher_role_instance_id, go_id, cell_id,
                  attempt, plan_revision, kind, related_event_id, message_id,
                  evidence_refs_json, details_json, payload_sha256, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
                params![
                    request.observation_id,
                    request.run_id,
                    overwatcher_role_instance_id,
                    request.go_id,
                    request.cell_id,
                    request.attempt,
                    request.plan_revision,
                    request.kind.as_str(),
                    request.related_event_id,
                    request.message_id,
                    serde_json::to_string(&request.evidence_refs)?,
                    serde_json::to_string(&request.details)?,
                    payload_sha256,
                    request.occurred_at,
                ],
            )?;
            Ok(())
        })
    }

    pub fn record_overwatch_cycle(
        &self,
        credential: &Credential,
        request: OverwatchCycleRequest,
    ) -> Result<(), StateError> {
        validate_overwatch_cycle_shape(&request)?;
        let payload_json = serde_json::to_string(&request)?;
        let payload_sha256 = sha256_hex(payload_json.as_bytes());
        self.with_immediate_transaction(|transaction| {
            let overwatcher_role_instance_id =
                authorize_overwatcher(transaction, &request.run_id, credential)?;
            if overwatcher_role_instance_id != request.role_instance_id {
                return Err(StateError::OverwatcherCycleInvalid(
                    "only the bound Overwatcher may author cycles".into(),
                ));
            }
            let binding: Option<OverwatchCycleBindingRow> = transaction
                .query_row(
                    "SELECT session_id, observation_mode, cadence_seconds,
                            foreground_turn_id, lifecycle_state, binding_revision,
                            continuity_state, bound_at
                     FROM overwatcher_bindings
                     WHERE run_id=?1 AND role_instance_id=?2",
                    params![request.run_id, overwatcher_role_instance_id],
                    |row| {
                        Ok((
                            row.get(0)?,
                            row.get(1)?,
                            row.get(2)?,
                            row.get(3)?,
                            row.get(4)?,
                            row.get(5)?,
                            row.get(6)?,
                            row.get(7)?,
                        ))
                    },
                )
                .optional()?;
            let Some((session_id, mode, cadence, foreground_turn_id, lifecycle, binding_revision, continuity_state, bound_at)) = binding else {
                return Err(StateError::OverwatcherCycleInvalid(
                    "the Overwatcher binding does not exist".into(),
                ));
            };
            if lifecycle != "active"
                || mode != "FOREGROUND_ACTIVE_TURN"
                || session_id != request.session_id
                || foreground_turn_id != request.foreground_turn_id
                || cadence != i64::from(request.cadence_seconds)
                || continuity_state != "ACTIVE"
            {
                return Err(StateError::OverwatcherCycleInvalid(
                    "cycle identity must match the active foreground binding".into(),
                ));
            }
            let method_version: String = transaction.query_row(
                "SELECT slk_version FROM runs WHERE run_id=?1",
                [&request.run_id],
                |row| row.get(0),
            )?;
            let runtime_snapshot = runtime_snapshot_from(transaction, &request.run_id)?;
            if uses_revisioned_runtime_contract(&method_version) {
                if request.binding_revision != binding_revision
                    || request.runtime_revision != runtime_snapshot.runtime_revision
                    || request.native_liveness != NativeLiveness::InProgress
                {
                    return Err(StateError::OverwatcherCycleInvalid(
                        "cycle must bind the current runtime/binding revision and a live foreground turn"
                            .into(),
                    ));
                }
                for evidence in &request.evidence_refs {
                    validate_evidence_reference(evidence)?;
                }
                if !request
                    .evidence_refs
                    .iter()
                    .any(|item| item.path == request.native_active_session_evidence_ref)
                {
                    return Err(StateError::OverwatcherCycleInvalid(
                        "native activity reference must name one verified cycle evidence file".into(),
                    ));
                }
                if method_version == "4.2.4" {
                    validate_worker_completion_cycle(
                        transaction,
                        &request,
                        &runtime_snapshot,
                    )?;
                }
            }
            let revision = current_plan_revision(transaction, &request.run_id)?;
            if request.plan_revision != revision {
                return Err(StateError::PlanRevisionMismatch {
                    requested: request.plan_revision,
                    current: revision,
                });
            }
            if let (Some(go_id), Some(cell_id)) =
                (request.go_id.as_deref(), request.cell_id.as_deref())
            {
                let exists: Option<i64> = transaction
                    .query_row(
                        "SELECT 1 FROM cell_nodes WHERE run_id=?1 AND go_id=?2 AND cell_id=?3",
                        params![request.run_id, go_id, cell_id],
                        |row| row.get(0),
                    )
                    .optional()?;
                if exists.is_none() {
                    return Err(StateError::OverwatcherCycleInvalid(
                        "cycle CELL scope is not in the current plan".into(),
                    ));
                }
            }
            let token = current_token_from(transaction, &request.run_id)?;
            if token.sequence != request.token_sequence
                || token.owner_role_instance_id != request.token_holder_role_instance_id
            {
                return Err(StateError::OverwatcherCycleInvalid(
                    "cycle TOKEN snapshot is stale or mismatched".into(),
                ));
            }
            let current_message_id: Option<String> = transaction.query_row(
                "SELECT message_id FROM token_events
                 WHERE run_id=?1 ORDER BY token_sequence DESC LIMIT 1",
                [&request.run_id],
                |row| row.get(0),
            )?;
            let expected_message = if uses_revisioned_runtime_contract(&method_version) {
                runtime_snapshot.latest_message_id.clone()
            } else {
                current_message_id
            };
            if expected_message != request.latest_message_id {
                return Err(StateError::OverwatcherCycleInvalid(
                    "cycle latest message reference is stale".into(),
                ));
            }
            let latest_event_id: String = transaction.query_row(
                "SELECT event_id FROM work_events WHERE run_id=?1 ORDER BY rowid DESC LIMIT 1",
                [&request.run_id],
                |row| row.get(0),
            )?;
            let expected_event = if uses_revisioned_runtime_contract(&method_version) {
                runtime_snapshot.latest_event_id.clone()
            } else {
                latest_event_id
            };
            if expected_event != request.latest_event_id {
                return Err(StateError::OverwatcherCycleInvalid(
                    "cycle latest event reference is stale".into(),
                ));
            }
            let existing: Option<String> = transaction
                .query_row(
                    "SELECT payload_sha256 FROM overwatch_cycles WHERE cycle_id=?1",
                    [&request.cycle_id],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(existing) = existing {
                return if existing == payload_sha256 {
                    Ok(())
                } else {
                    Err(StateError::OverwatcherObservationConflict)
                };
            }
            let current_sequence: u64 = transaction.query_row(
                "SELECT COALESCE(MAX(cycle_sequence), 0) FROM overwatch_cycles WHERE run_id=?1",
                [&request.run_id],
                |row| row.get(0),
            )?;
            if request.cycle_sequence != current_sequence + 1 {
                return Err(StateError::OverwatcherCycleSequence {
                    requested: request.cycle_sequence,
                    expected: current_sequence + 1,
                });
            }
            let previous_completed_at: Option<String> = transaction
                .query_row(
                    "SELECT completed_at FROM overwatch_cycles
                     WHERE run_id=?1 ORDER BY cycle_sequence DESC LIMIT 1",
                    [&request.run_id],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(previous_completed_at) = previous_completed_at.as_deref() {
                if parse_rfc3339(&request.started_at)? < parse_rfc3339(previous_completed_at)? {
                    return Err(StateError::OverwatcherCycleInvalid(
                        "observation cycles must not overlap".into(),
                    ));
                }
            }
            let cadence_anchor = previous_completed_at.as_deref().unwrap_or(bound_at.as_str());
            let cadence_health = if parse_rfc3339(&request.started_at)?
                > parse_rfc3339(cadence_anchor)? + cadence
            {
                "LATE"
            } else {
                "ON_TIME"
            };
            transaction.execute(
                "INSERT INTO overwatch_cycles
                 (cycle_id, run_id, overwatcher_role_instance_id, session_id,
                  foreground_turn_id, cycle_sequence, cadence_seconds, plan_revision,
                  go_id, cell_id, attempt, token_sequence, token_holder_role_instance_id,
                  latest_event_id, latest_message_id, checklist_json, anomaly_codes_json,
                  evidence_refs_json, native_active_session_evidence_ref, payload_sha256,
                  started_at, completed_at, next_cycle_at, binding_revision,
                  runtime_revision, native_liveness, cadence_health, cost_metrics_json)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12,
                         ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23,
                         ?24, ?25, ?26, ?27, ?28)",
                params![
                    request.cycle_id,
                    request.run_id,
                    overwatcher_role_instance_id,
                    request.session_id,
                    request.foreground_turn_id,
                    request.cycle_sequence,
                    request.cadence_seconds,
                    request.plan_revision,
                    request.go_id,
                    request.cell_id,
                    request.attempt,
                    request.token_sequence,
                    request.token_holder_role_instance_id,
                    request.latest_event_id,
                    request.latest_message_id,
                    serde_json::to_string(&request.checklist)?,
                    serde_json::to_string(&request.anomaly_codes)?,
                    serde_json::to_string(&request.evidence_refs)?,
                    request.native_active_session_evidence_ref,
                    payload_sha256,
                    request.started_at,
                    request.completed_at,
                    request.next_cycle_at,
                    binding_revision,
                    runtime_snapshot.runtime_revision,
                    request.native_liveness.as_str(),
                    cadence_health,
                    request
                        .cost_metrics
                        .as_ref()
                        .map(serde_json::to_string)
                        .transpose()?,
                ],
            )?;
            Ok(())
        })
    }

    pub fn close_overwatcher(
        &self,
        credential: &Credential,
        request: CloseOverwatcherRequest,
    ) -> Result<(), StateError> {
        if !valid_identifier(&request.event_id) || request.archive_evidence_ref.trim().is_empty() {
            return Err(StateError::OverwatcherObservationInvalid(
                "closure event and archive evidence are required".into(),
            ));
        }
        self.with_immediate_transaction(|transaction| {
            let overwatcher_role_instance_id =
                authorize_overwatcher(transaction, &request.run_id, credential)?;
            let (method_version, closure_state): (String, String) = transaction.query_row(
                "SELECT slk_version, closure_state FROM runs WHERE run_id=?1",
                [&request.run_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )?;
            if uses_revisioned_runtime_contract(&method_version) {
                if closure_state == "open" {
                    return Err(StateError::OverwatcherObservationInvalid(
                        "a whole-Run Overwatcher cannot close at a CELL or GO boundary".into(),
                    ));
                }
                let requested_revision = request.runtime_revision.ok_or_else(|| {
                    StateError::OverwatcherObservationInvalid(
                        "terminal close requires the exact runtime revision".into(),
                    )
                })?;
                let snapshot = runtime_snapshot_from(transaction, &request.run_id)?;
                if requested_revision != snapshot.runtime_revision {
                    return Err(StateError::OverwatcherObservationInvalid(
                        "terminal close runtime revision is stale".into(),
                    ));
                }
                let final_cycle_id = request.final_cycle_id.as_deref().ok_or_else(|| {
                    StateError::OverwatcherObservationInvalid(
                        "terminal close requires the final observation cycle".into(),
                    )
                })?;
                let final_cycle: Option<(String, u64)> = transaction
                    .query_row(
                        "SELECT cycle_id, runtime_revision FROM overwatch_cycles
                         WHERE run_id=?1 ORDER BY cycle_sequence DESC LIMIT 1",
                        [&request.run_id],
                        |row| Ok((row.get(0)?, row.get(1)?)),
                    )
                    .optional()?;
                if final_cycle.as_ref().map(|item| item.0.as_str()) != Some(final_cycle_id)
                    || final_cycle.as_ref().map(|item| item.1) != Some(requested_revision)
                {
                    return Err(StateError::OverwatcherObservationInvalid(
                        "terminal close must cite the latest cycle at the same runtime revision"
                            .into(),
                    ));
                }
            }
            let revision = current_plan_revision(transaction, &request.run_id)?;
            let details = serde_json::json!({
                "archive_evidence_ref": request.archive_evidence_ref.clone(),
                "final_cycle_id": request.final_cycle_id.clone(),
                "runtime_revision": request.runtime_revision,
            });
            let details_json = serde_json::to_string(&details)?;
            let payload_sha256 = sha256_hex(details_json.as_bytes());
            transaction.execute(
                "INSERT INTO operational_observations
                 (observation_id, run_id, overwatcher_role_instance_id, plan_revision,
                  kind, evidence_refs_json, details_json, payload_sha256, occurred_at)
                 VALUES (?1, ?2, ?3, ?4, 'OVERWATCHER_CLOSED', ?5, ?6, ?7, ?8)",
                params![
                    request.event_id,
                    request.run_id,
                    overwatcher_role_instance_id,
                    revision,
                    serde_json::to_string(&vec![request.archive_evidence_ref.clone()])?,
                    details_json,
                    payload_sha256,
                    request.occurred_at,
                ],
            )?;
            transaction.execute(
                "UPDATE overwatcher_bindings
                 SET lifecycle_state='archived', continuity_state='ARCHIVED',
                     closed_at=?2, archive_evidence_ref=?3
                 WHERE run_id=?1 AND role_instance_id=?4",
                params![
                    request.run_id,
                    request.occurred_at,
                    request.archive_evidence_ref,
                    overwatcher_role_instance_id,
                ],
            )?;
            transaction.execute(
                "UPDATE overwatcher_bindings SET credential_state='revoked'
                 WHERE run_id=?1 AND role_instance_id=?2",
                params![request.run_id, overwatcher_role_instance_id],
            )?;
            if uses_revisioned_runtime_contract(&method_version) {
                let snapshot = runtime_snapshot_from(transaction, &request.run_id)?;
                let runtime_revision = advance_runtime_snapshot(
                    transaction,
                    &request.run_id,
                    &request.event_id,
                    snapshot.latest_message_id.as_deref(),
                    &request.occurred_at,
                )?;
                transaction.execute(
                    "INSERT INTO overwatcher_binding_transitions
                     (transition_id, run_id, binding_revision, transition_type, cycle_id,
                      runtime_revision, evidence_ref, occurred_at)
                     SELECT ?1, run_id, binding_revision, 'TERMINAL_CLOSE', ?2, ?3, ?4, ?5
                     FROM overwatcher_bindings WHERE run_id=?6",
                    params![
                        request.event_id,
                        request.final_cycle_id,
                        runtime_revision,
                        request.archive_evidence_ref,
                        request.occurred_at,
                        request.run_id,
                    ],
                )?;
            }
            Ok(())
        })
    }

    pub fn replace_overwatcher(
        &self,
        credential: &Credential,
        request: ReplaceOverwatcherRequest,
    ) -> Result<IssuedCredential, StateError> {
        if !valid_identifier(&request.event_id)
            || request.expected_binding_revision == 0
            || request.expected_runtime_revision == 0
            || request.replacement.role != Role::Overwatcher
            || !valid_identifier(&request.replacement.role_instance_id)
            || request.replacement.session_id != request.endpoint.session_id
            || request.replacement.agent_runtime.trim().is_empty()
            || request.replacement.provider.trim().is_empty()
            || request.replacement.model.trim().is_empty()
            || request.replacement.reasoning.trim().is_empty()
            || request.endpoint.endpoint_version == 0
            || request.endpoint.transport_adapter.trim().is_empty()
            || request.endpoint.host_identity.trim().is_empty()
            || !(180..=300).contains(&request.cadence_seconds)
            || request.foreground_turn_id.trim().is_empty()
            || request.reason.trim().is_empty()
        {
            return Err(StateError::OverwatcherBindingInvalid(
                "replacement requires one complete closed identity and 180-300 second cadence"
                    .into(),
            ));
        }
        validate_admin_timestamp(&request.occurred_at)?;
        validate_evidence_reference(&request.native_active_session_evidence)?;
        match request.mode {
            OverwatcherReplacementMode::Planned => {
                if request.final_cycle_id.as_deref().is_none_or(str::is_empty)
                    || request.authorization_evidence.is_some()
                {
                    return Err(StateError::OverwatcherBindingInvalid(
                        "planned replacement requires a final cycle and no recovery authorization"
                            .into(),
                    ));
                }
            }
            OverwatcherReplacementMode::ContinuityRecovery => {
                if request.final_cycle_id.is_some() || request.authorization_evidence.is_none() {
                    return Err(StateError::OverwatcherBindingInvalid(
                        "continuity recovery requires authorization and preserves the missing final cycle"
                            .into(),
                    ));
                }
                validate_evidence_reference(
                    request.authorization_evidence.as_ref().expect("checked"),
                )?;
            }
        }

        self.with_immediate_transaction(|transaction| {
            let actor = authorize_role(transaction, &request.run_id, credential)?;
            if actor.role != Role::Supervisor {
                return Err(StateError::OverwatcherBindingNotAuthorized);
            }
            let method_version: String = transaction.query_row(
                "SELECT slk_version FROM runs WHERE run_id=?1 AND closure_state='open'",
                [&request.run_id],
                |row| row.get(0),
            )?;
            if !uses_revisioned_runtime_contract(&method_version) {
                return Err(StateError::OverwatcherBindingInvalid(
                    "revisioned replacement requires an effective revisioned runtime contract".into(),
                ));
            }
            let snapshot = runtime_snapshot_from(transaction, &request.run_id)?;
            if snapshot.runtime_revision != request.expected_runtime_revision {
                return Err(StateError::OverwatcherBindingInvalid(
                    "replacement runtime revision is stale".into(),
                ));
            }
            let binding: (u64, String, String, String) = transaction.query_row(
                "SELECT binding_revision, role_instance_id, session_id, continuity_state
                 FROM overwatcher_bindings
                 WHERE run_id=?1 AND lifecycle_state='active'",
                [&request.run_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )?;
            if binding.0 != request.expected_binding_revision
                || binding.1 == request.replacement.role_instance_id
                || binding.2 == request.replacement.session_id
            {
                return Err(StateError::OverwatcherBindingInvalid(
                    "replacement must bind the exact current revision to a new role/session identity"
                        .into(),
                ));
            }
            let identity_collision: Option<i64> = transaction
                .query_row(
                    "SELECT 1 FROM role_instances WHERE role_instance_id=?1",
                    [&request.replacement.role_instance_id],
                    |row| row.get(0),
                )
                .optional()?;
            let session_collision: Option<i64> = transaction
                .query_row(
                    "SELECT 1 FROM overwatcher_bindings
                     WHERE session_id=?1 AND run_id<>?2",
                    params![request.replacement.session_id, request.run_id],
                    |row| row.get(0),
                )
                .optional()?;
            if identity_collision.is_some() || session_collision.is_some() {
                return Err(StateError::OverwatcherSessionReused);
            }
            match request.mode {
                OverwatcherReplacementMode::Planned => {
                    if binding.3 != "ACTIVE" {
                        return Err(StateError::OverwatcherBindingInvalid(
                            "planned replacement requires uninterrupted active continuity".into(),
                        ));
                    }
                    let last_cycle: Option<(String, u64, u64)> = transaction
                        .query_row(
                            "SELECT cycle_id, binding_revision, runtime_revision
                             FROM overwatch_cycles WHERE run_id=?1
                             ORDER BY cycle_sequence DESC LIMIT 1",
                            [&request.run_id],
                            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                        )
                        .optional()?;
                    let expected_cycle = request.final_cycle_id.as_deref().expect("checked");
                    if last_cycle.as_ref().map(|item| item.0.as_str()) != Some(expected_cycle)
                        || last_cycle.as_ref().map(|item| item.1) != Some(binding.0)
                        || last_cycle.as_ref().map(|item| item.2)
                            != Some(snapshot.runtime_revision)
                    {
                        return Err(StateError::OverwatcherBindingInvalid(
                            "planned replacement requires the exact final cycle at the current revision"
                                .into(),
                        ));
                    }
                }
                OverwatcherReplacementMode::ContinuityRecovery => {
                    if binding.3 != "VIOLATION" {
                        return Err(StateError::OverwatcherBindingInvalid(
                            "recovery replacement requires a recorded continuity violation".into(),
                        ));
                    }
                }
            }

            let next_binding_revision = binding.0 + 1;
            let material = new_credential_material();
            let native_address_json = serde_json::to_string(&request.endpoint.native_address)?;
            if request.mode == OverwatcherReplacementMode::ContinuityRecovery {
                let authorization = request.authorization_evidence.as_ref().expect("checked");
                let incident_id = format!("continuity-{}-{}", request.run_id, binding.0);
                transaction.execute(
                    "INSERT INTO overwatcher_incident_transitions
                     (transition_id, incident_id, run_id, binding_revision, incident_code,
                      state, evidence_path, evidence_sha256, occurred_at)
                     VALUES (?1,?2,?3,?4,'OVERWATCHER_CONTINUITY_VIOLATION','ACKNOWLEDGED',?5,?6,?7)",
                    params![
                        format!("incident-ack-{}", request.event_id),
                        incident_id,
                        request.run_id,
                        binding.0,
                        authorization.path,
                        authorization.sha256,
                        request.occurred_at,
                    ],
                )?;
                transaction.execute(
                    "INSERT INTO overwatcher_binding_transitions
                     (transition_id, run_id, binding_revision, transition_type, cycle_id,
                      runtime_revision, evidence_ref, occurred_at)
                     VALUES (?1,?2,?3,'INCOMPLETE_SHUTDOWN',NULL,?4,?5,?6)",
                    params![
                        format!("incomplete-{}", request.event_id),
                        request.run_id,
                        binding.0,
                        snapshot.runtime_revision,
                        authorization.path,
                        request.occurred_at,
                    ],
                )?;
            }
            transaction.execute(
                "UPDATE overwatcher_bindings SET
                    role_instance_id=?2, agent_runtime=?3, provider=?4, model=?5,
                    reasoning=?6, session_id=?7, endpoint_version=?8,
                    transport_adapter=?9, host_identity=?10, native_address_json=?11,
                    bound_by_role_instance_id=?12, binding_reason=?13,
                    credential_id=?14, credential_sha256=?15, credential_state='active',
                    lifecycle_state='active', bound_at=?16, closed_at=NULL,
                    archive_evidence_ref=NULL, cadence_seconds=?17,
                    foreground_turn_id=?18, native_active_session_evidence_ref=?19,
                    binding_revision=?20, canonical_task_id=?21, continuity_state='ACTIVE'
                 WHERE run_id=?1 AND binding_revision=?22",
                params![
                    request.run_id,
                    request.replacement.role_instance_id,
                    request.replacement.agent_runtime,
                    request.replacement.provider,
                    request.replacement.model,
                    request.replacement.reasoning,
                    request.replacement.session_id,
                    request.endpoint.endpoint_version,
                    request.endpoint.transport_adapter,
                    request.endpoint.host_identity,
                    native_address_json,
                    actor.role_instance_id,
                    request.reason,
                    material.credential_id,
                    material.credential_sha256,
                    request.occurred_at,
                    request.cadence_seconds,
                    request.foreground_turn_id,
                    request.native_active_session_evidence.path,
                    next_binding_revision,
                    request.replacement.session_id,
                    binding.0,
                ],
            )?;
            let runtime_revision = advance_runtime_snapshot(
                transaction,
                &request.run_id,
                &request.event_id,
                snapshot.latest_message_id.as_deref(),
                &request.occurred_at,
            )?;
            let transition_type = match request.mode {
                OverwatcherReplacementMode::Planned => "PLANNED_REPLACEMENT",
                OverwatcherReplacementMode::ContinuityRecovery => "RECOVERY_REPLACEMENT",
            };
            transaction.execute(
                "INSERT INTO overwatcher_binding_transitions
                 (transition_id, run_id, binding_revision, transition_type, cycle_id,
                  runtime_revision, evidence_ref, occurred_at)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",
                params![
                    request.event_id,
                    request.run_id,
                    next_binding_revision,
                    transition_type,
                    request.final_cycle_id,
                    runtime_revision,
                    request.native_active_session_evidence.path,
                    request.occurred_at,
                ],
            )?;
            if request.mode == OverwatcherReplacementMode::ContinuityRecovery {
                let authorization = request.authorization_evidence.as_ref().expect("checked");
                transaction.execute(
                    "INSERT INTO overwatcher_incident_transitions
                     (transition_id, incident_id, run_id, binding_revision, incident_code,
                      state, evidence_path, evidence_sha256, occurred_at)
                     VALUES (?1,?2,?3,?4,'OVERWATCHER_CONTINUITY_VIOLATION','RESOLVED',?5,?6,?7)",
                    params![
                        format!("incident-resolved-{}", request.event_id),
                        format!("continuity-{}-{}", request.run_id, binding.0),
                        request.run_id,
                        binding.0,
                        authorization.path,
                        authorization.sha256,
                        request.occurred_at,
                    ],
                )?;
            }
            Ok(IssuedCredential {
                credential_id: material.credential_id,
                credential: material.credential,
            })
        })
    }

    pub fn record_overwatcher_status(
        &self,
        credential: &Credential,
        request: RecordOverwatcherStatusRequest,
    ) -> Result<(), StateError> {
        if !valid_identifier(&request.status_id)
            || request.binding_revision == 0
            || !valid_identifier(&request.role_instance_id)
            || request.session_id.trim().is_empty()
            || request.foreground_turn_id.trim().is_empty()
        {
            return Err(StateError::OverwatcherCycleInvalid(
                "native status identity is incomplete".into(),
            ));
        }
        validate_evidence_reference(&request.evidence)?;
        validate_admin_timestamp(&request.observed_at)?;
        let payload_sha256 = sha256_hex(serde_json::to_string(&request)?.as_bytes());
        self.with_immediate_transaction(|transaction| {
            let role_instance_id =
                authorize_overwatcher(transaction, &request.run_id, credential)?;
            let binding: (u64, String, String, String, String, String) = transaction.query_row(
                "SELECT binding_revision, role_instance_id, session_id, foreground_turn_id,
                        lifecycle_state, continuity_state
                 FROM overwatcher_bindings WHERE run_id=?1",
                [&request.run_id],
                |row| {
                    Ok((
                        row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?,
                        row.get(5)?,
                    ))
                },
            )?;
            if binding.0 != request.binding_revision
                || binding.1 != role_instance_id
                || binding.1 != request.role_instance_id
                || binding.2 != request.session_id
                || binding.3 != request.foreground_turn_id
                || binding.4 != "active"
            {
                return Err(StateError::OverwatcherCycleInvalid(
                    "native status does not bind the current Overwatcher turn".into(),
                ));
            }
            if binding.5 == "VIOLATION" && request.native_liveness == NativeLiveness::InProgress {
                return Err(StateError::OverwatcherCycleInvalid(
                    "a continuity violation cannot be silently upgraded to active".into(),
                ));
            }
            let existing: Option<String> = transaction
                .query_row(
                    "SELECT payload_sha256 FROM overwatcher_native_status_receipts WHERE status_id=?1",
                    [&request.status_id],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(existing) = existing {
                return if existing == payload_sha256 {
                    Ok(())
                } else {
                    Err(StateError::OverwatcherObservationConflict)
                };
            }
            transaction.execute(
                "INSERT INTO overwatcher_native_status_receipts
                 (status_id, run_id, binding_revision, role_instance_id, session_id,
                  foreground_turn_id, native_liveness, evidence_path, evidence_sha256,
                  observed_at, payload_sha256)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
                params![
                    request.status_id,
                    request.run_id,
                    request.binding_revision,
                    request.role_instance_id,
                    request.session_id,
                    request.foreground_turn_id,
                    request.native_liveness.as_str(),
                    request.evidence.path,
                    request.evidence.sha256,
                    request.observed_at,
                    payload_sha256,
                ],
            )?;
            if request.native_liveness != NativeLiveness::InProgress {
                transaction.execute(
                    "UPDATE overwatcher_bindings SET continuity_state='VIOLATION'
                     WHERE run_id=?1 AND binding_revision=?2",
                    params![request.run_id, request.binding_revision],
                )?;
                let incident_id = format!(
                    "continuity-{}-{}",
                    request.run_id, request.binding_revision
                );
                transaction.execute(
                    "INSERT INTO overwatcher_incident_transitions
                     (transition_id, incident_id, run_id, binding_revision, incident_code,
                      state, evidence_path, evidence_sha256, occurred_at)
                     VALUES (?1,?2,?3,?4,'OVERWATCHER_CONTINUITY_VIOLATION','OPEN',?5,?6,?7)",
                    params![
                        format!("incident-open-{}", request.status_id),
                        incident_id,
                        request.run_id,
                        request.binding_revision,
                        request.evidence.path,
                        request.evidence.sha256,
                        request.observed_at,
                    ],
                )?;
            }
            let current_snapshot = runtime_snapshot_from(transaction, &request.run_id)?;
            advance_runtime_snapshot(
                transaction,
                &request.run_id,
                &request.status_id,
                current_snapshot.latest_message_id.as_deref(),
                &request.observed_at,
            )?;
            Ok(())
        })
    }

    pub fn current_token(&self, run_id: &str) -> Result<CurrentToken, StateError> {
        let connection = open_database(&self.data_root)?;
        current_token_from(&connection, run_id)
    }

    pub fn authenticate_active_role(
        &self,
        run_id: &str,
        credential: &Credential,
    ) -> Result<AuthorizedActor, StateError> {
        let connection = open_database(&self.data_root)?;
        authorize_event(&connection, run_id, credential, EventType::TokenHandedOff)
    }

    pub fn current_cell_state(&self, run_id: &str, cell_id: &str) -> Result<String, StateError> {
        let connection = open_database(&self.data_root)?;
        connection
            .query_row(
                "SELECT state FROM cell_nodes WHERE run_id=?1 AND cell_id=?2",
                params![run_id, cell_id],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| StateError::CellNotFound(cell_id.to_string()))
    }

    pub fn d1_rework_count(&self, run_id: &str, cell_id: &str) -> Result<u64, StateError> {
        let connection = open_database(&self.data_root)?;
        let count: i64 = connection.query_row(
            "SELECT COUNT(*) FROM work_events
             WHERE run_id=?1 AND cell_id=?2 AND event_type IN ('D1_FAILED', 'REWORK_REQUESTED')",
            params![run_id, cell_id],
            |row| row.get(0),
        )?;
        Ok(count as u64)
    }

    pub fn run_count(&self) -> Result<u64, StateError> {
        let connection = open_database(&self.data_root)?;
        let count: i64 = connection.query_row("SELECT COUNT(*) FROM runs", [], |row| row.get(0))?;
        Ok(count as u64)
    }

    pub(crate) fn with_immediate_transaction<T, F>(&self, mut operation: F) -> Result<T, StateError>
    where
        F: FnMut(&Transaction<'_>) -> Result<T, StateError>,
    {
        let mut last_busy = None;
        for attempt in 0..TRANSACTION_ATTEMPTS {
            let mut connection = match open_database(&self.data_root) {
                Ok(connection) => connection,
                Err(SchemaError::Sqlite(error)) if is_busy(&error) => {
                    last_busy = Some(error);
                    thread::sleep(Duration::from_millis(25 * (attempt as u64 + 1)));
                    continue;
                }
                Err(error) => return Err(error.into()),
            };
            let transaction =
                match connection.transaction_with_behavior(TransactionBehavior::Immediate) {
                    Ok(transaction) => transaction,
                    Err(error) if is_busy(&error) => {
                        last_busy = Some(error);
                        thread::sleep(Duration::from_millis(25 * (attempt as u64 + 1)));
                        continue;
                    }
                    Err(error) => return Err(error.into()),
                };
            let value = operation(&transaction)?;
            match transaction.commit() {
                Ok(()) => return Ok(value),
                Err(error) if is_busy(&error) => {
                    last_busy = Some(error);
                    thread::sleep(Duration::from_millis(25 * (attempt as u64 + 1)));
                }
                Err(error) => return Err(error.into()),
            }
        }
        Err(last_busy.expect("busy retry records one error").into())
    }
}

fn validate_overwatch_cycle_shape(request: &OverwatchCycleRequest) -> Result<(), StateError> {
    let checks = [
        request.checklist.run_position,
        request.checklist.role_bindings,
        request.checklist.direct_handoffs,
        request.checklist.cell_lifecycle,
        request.checklist.stall_and_duplicates,
        request.checklist.bi_projection,
        request.checklist.active_session,
        request.checklist.terminal_closure,
    ];
    let has_anomaly = checks.contains(&OverwatchCheckResult::Anomaly);
    if !valid_identifier(&request.cycle_id)
        || request.plan_revision == 0
        || request.cycle_sequence == 0
        || !(180..=300).contains(&request.cadence_seconds)
        || request.role_instance_id.trim().is_empty()
        || request.session_id.trim().is_empty()
        || request.foreground_turn_id.trim().is_empty()
        || request.token_sequence == 0
        || request.token_holder_role_instance_id.trim().is_empty()
        || request.latest_event_id.trim().is_empty()
        || request.native_active_session_evidence_ref.trim().is_empty()
        || request.evidence_refs.is_empty()
        || request
            .evidence_refs
            .iter()
            .any(|item| item.path.trim().is_empty() || !is_lower_sha256(&item.sha256))
        || has_anomaly == request.anomaly_codes.is_empty()
        || request.checklist.active_session == OverwatchCheckResult::NotApplicable
        || (request.cell_id.is_some() && request.go_id.is_none())
        || (request.cell_id.is_none() && request.attempt.is_some())
    {
        return Err(StateError::OverwatcherCycleInvalid(
            "closed identity, complete checklist, active-session result, and evidence are required"
                .into(),
        ));
    }
    let started = parse_rfc3339(&request.started_at)?;
    let completed = parse_rfc3339(&request.completed_at)?;
    let next = parse_rfc3339(&request.next_cycle_at)?;
    if completed < started || next - completed != i64::from(request.cadence_seconds) {
        return Err(StateError::OverwatcherCycleInvalid(
            "cycle timestamps must be ordered and next_cycle_at must equal the bound cadence"
                .into(),
        ));
    }
    Ok(())
}

fn validate_evidence_reference(reference: &EvidenceReference) -> Result<(), StateError> {
    if !is_lower_sha256(&reference.sha256) {
        return Err(StateError::EvidenceInvalid(
            "evidence reference must contain a lowercase SHA-256".into(),
        ));
    }
    let path = Path::new(&reference.path);
    if !path.is_absolute() || !path.is_file() {
        return Err(StateError::EvidenceInvalid(
            "evidence reference must name an existing absolute file".into(),
        ));
    }
    let bytes = fs::read(path)?;
    if sha256_hex(&bytes) != reference.sha256 {
        return Err(StateError::EvidenceInvalid(
            "evidence reference hash does not match stored bytes".into(),
        ));
    }
    Ok(())
}

fn validate_worker_completion_cycle(
    connection: &Connection,
    request: &OverwatchCycleRequest,
    runtime_snapshot: &RuntimeSnapshot,
) -> Result<(), StateError> {
    let token_role: Option<String> = connection
        .query_row(
            "SELECT role FROM role_instances WHERE run_id=?1 AND role_instance_id=?2",
            params![request.run_id, request.token_holder_role_instance_id],
            |row| row.get(0),
        )
        .optional()?;
    if token_role.as_deref() != Some("worker") {
        return Ok(());
    }
    let mut inspections = Vec::new();
    for reference in &request.evidence_refs {
        let bytes = fs::read(&reference.path)?;
        let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes) else {
            continue;
        };
        if value
            .get("schema_version")
            .and_then(serde_json::Value::as_str)
            == Some("slk.worker-completion-inspection/v1")
        {
            inspections.push(value);
        }
    }
    if inspections.len() != 1 {
        return Err(StateError::OverwatcherCycleInvalid(
            "4.2.4 Worker-held TOKEN requires exactly one completion inspection per cycle".into(),
        ));
    }
    let inspection = &inspections[0];
    let status = inspection
        .get("status")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| {
            StateError::OverwatcherCycleInvalid(
                "Worker completion inspection status is missing".into(),
            )
        })?;
    if inspection.get("run_id").and_then(serde_json::Value::as_str) != Some(request.run_id.as_str())
        || inspection.get("go_id").and_then(serde_json::Value::as_str) != request.go_id.as_deref()
        || inspection
            .get("cell_id")
            .and_then(serde_json::Value::as_str)
            != request.cell_id.as_deref()
        || inspection
            .get("worker_role_instance_id")
            .and_then(serde_json::Value::as_str)
            != Some(request.token_holder_role_instance_id.as_str())
        || inspection
            .get("source_message_id")
            .and_then(serde_json::Value::as_str)
            != runtime_snapshot.latest_message_id.as_deref()
        || runtime_snapshot.token_sequence != request.token_sequence
    {
        return Err(StateError::OverwatcherCycleInvalid(
            "Worker completion inspection scope or TOKEN identity is stale".into(),
        ));
    }
    let missing = status == "WORKER_COMPLETION_HANDOFF_MISSING";
    let inspection_codes = inspection
        .get("anomaly_codes")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| {
            StateError::OverwatcherCycleInvalid(
                "Worker completion inspection anomaly codes are missing".into(),
            )
        })?;
    let inspection_has_exact_missing_codes = inspection_codes.len() == 2
        && inspection_codes
            .iter()
            .any(|value| value.as_str() == Some("WORKER_COMPLETION_HANDOFF_MISSING"))
        && inspection_codes
            .iter()
            .any(|value| value.as_str() == Some("COMMUNICATION_RECOVERY_REQUIRED"));
    if inspection
        .get("notification_already_sent")
        .and_then(serde_json::Value::as_bool)
        .is_none()
        || (missing && !inspection_has_exact_missing_codes)
        || (!missing && !inspection_codes.is_empty())
    {
        return Err(StateError::OverwatcherCycleInvalid(
            "Worker completion inspection anomaly state is invalid".into(),
        ));
    }
    let has_missing_code = request
        .anomaly_codes
        .contains(&crate::model::OverwatchAnomalyCode::WorkerCompletionHandoffMissing);
    let has_recovery_code = request
        .anomaly_codes
        .contains(&crate::model::OverwatchAnomalyCode::CommunicationRecoveryRequired);
    if missing
        != (request.checklist.stall_and_duplicates == OverwatchCheckResult::Anomaly
            && has_missing_code
            && has_recovery_code)
    {
        return Err(StateError::OverwatcherCycleInvalid(
            "Worker completion handoff anomaly cannot be cleared or fabricated".into(),
        ));
    }
    Ok(())
}

fn validate_bound_overwatcher_active(
    connection: &Connection,
    run_id: &str,
    action_at: &str,
) -> Result<(), StateError> {
    let binding: Option<ActiveOverwatcherGateRow> = connection
        .query_row(
            "SELECT o.cadence_seconds, o.foreground_turn_id, o.lifecycle_state,
                    o.binding_revision, o.continuity_state, r.slk_version
             FROM overwatcher_bindings o JOIN runs r ON r.run_id=o.run_id
             WHERE o.run_id=?1",
            [run_id],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                ))
            },
        )
        .optional()?;
    let Some((
        cadence,
        foreground_turn_id,
        lifecycle,
        binding_revision,
        continuity_state,
        method_version,
    )) = binding
    else {
        return Ok(());
    };
    let Some(cadence) = cadence else {
        return Err(StateError::OverwatcherInactive(
            "legacy 4.2.0 binding has no active-cycle contract".into(),
        ));
    };
    if lifecycle != "active" || foreground_turn_id.as_deref().is_none_or(str::is_empty) {
        return Err(StateError::OverwatcherInactive(
            "foreground active turn is not bound".into(),
        ));
    }
    if uses_revisioned_runtime_contract(&method_version) {
        if continuity_state != "ACTIVE" {
            return Err(StateError::OverwatcherInactive(
                "foreground turn continuity violation blocks new dispatch".into(),
            ));
        }
        let live_cycle: Option<i64> = connection
            .query_row(
                "SELECT 1 FROM overwatch_cycles
                 WHERE run_id=?1 AND binding_revision=?2 AND native_liveness='IN_PROGRESS'
                 ORDER BY cycle_sequence DESC LIMIT 1",
                params![run_id, binding_revision],
                |row| row.get(0),
            )
            .optional()?;
        if live_cycle.is_none() {
            return Err(StateError::OverwatcherInactive(
                "no complete live cycle exists for the current binding revision".into(),
            ));
        }
        return Ok(());
    }
    let completed_at: Option<String> = connection
        .query_row(
            "SELECT completed_at FROM overwatch_cycles
             WHERE run_id=?1 ORDER BY cycle_sequence DESC LIMIT 1",
            [run_id],
            |row| row.get(0),
        )
        .optional()?;
    let Some(completed_at) = completed_at else {
        return Err(StateError::OverwatcherInactive(
            "no complete active observation cycle exists".into(),
        ));
    };
    let elapsed = parse_rfc3339(action_at)? - parse_rfc3339(&completed_at)?;
    if elapsed < 0 || elapsed > cadence * 2 {
        return Err(StateError::OverwatcherInactive(
            "two foreground observation intervals elapsed without a complete cycle".into(),
        ));
    }
    Ok(())
}

fn parse_rfc3339(value: &str) -> Result<i64, StateError> {
    OffsetDateTime::parse(value, &Rfc3339)
        .map(|timestamp| timestamp.unix_timestamp())
        .map_err(|_| StateError::OverwatcherCycleInvalid("timestamps must be RFC3339".into()))
}

fn validate_linear_plan(request: &InitRunRequest) -> Result<(), StateError> {
    if !valid_identifier(&request.project.project_id)
        || !valid_identifier(&request.run_id)
        || !valid_identifier(&request.supervisor.role_instance_id)
    {
        return Err(StateError::InvalidPlan(
            "project, Run, and role identities must be safe path segments".into(),
        ));
    }
    if request.predecessor_run_id.as_deref() == Some(request.run_id.as_str())
        || request
            .predecessor_run_id
            .as_deref()
            .is_some_and(|value| !valid_identifier(value))
    {
        return Err(StateError::InvalidPlan(
            "predecessor_run_id must identify a different Run".into(),
        ));
    }
    if request.go_nodes.is_empty() || request.cell_nodes.is_empty() {
        return Err(StateError::InvalidPlan(
            "at least one GO and one CELL are required".into(),
        ));
    }
    let source_kind = request.source_kind.as_deref().unwrap_or("solo");
    if !matches!(source_kind, "solo" | "clk" | "glk") {
        return Err(StateError::InvalidPlan(
            "source_kind must be solo, clk, or glk".into(),
        ));
    }
    if source_kind != "solo"
        && request
            .source_project_name
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .is_none()
    {
        return Err(StateError::InvalidPlan(
            "CLK/GLK source context requires source_project_name".into(),
        ));
    }
    let mut go_ids = BTreeSet::new();
    for (index, go) in request.go_nodes.iter().enumerate() {
        if !valid_identifier(&go.go_id)
            || go.ordinal as usize != index + 1
            || !go_ids.insert(go.go_id.as_str())
        {
            return Err(StateError::InvalidPlan(
                "GO identities and ordinals must be unique and contiguous".into(),
            ));
        }
    }
    let mut next_cell_ordinal = BTreeMap::<&str, u32>::new();
    let mut cell_ids = BTreeSet::new();
    for cell in &request.cell_nodes {
        if !valid_identifier(&cell.cell_id)
            || !go_ids.contains(cell.go_id.as_str())
            || !cell_ids.insert(cell.cell_id.as_str())
        {
            return Err(StateError::InvalidPlan(
                "every CELL must have a unique identity and reference one GO".into(),
            ));
        }
        let next = next_cell_ordinal.entry(cell.go_id.as_str()).or_insert(1);
        if cell.ordinal != *next {
            return Err(StateError::InvalidPlan(
                "CELL ordinals must be contiguous inside each GO".into(),
            ));
        }
        *next += 1;
    }
    Ok(())
}

fn validate_engineering_role_binding(
    identity: &crate::model::RoleIdentity,
    endpoint: &crate::model::EndpointIdentity,
) -> Result<(), StateError> {
    let expected = match identity.role {
        Role::Supervisor => (
            "codex",
            "openai",
            "gpt-5.6-sol",
            "xhigh",
            "codex-app-server",
        ),
        Role::Checker => (
            "ocrv",
            "dashscope-tokenplan",
            "qwen3.8-max",
            "provider-default",
            "ocrv-checker",
        ),
        Role::Worker => (
            "dsh",
            "deepseek",
            "deepseek-v4-flash",
            "provider-default",
            "dsh-worker",
        ),
        Role::Overwatcher => return Ok(()),
    };
    let actual = (
        identity.agent_runtime.as_str(),
        identity.provider.as_str(),
        identity.model.as_str(),
        identity.reasoning.as_str(),
        endpoint.transport_adapter.as_str(),
    );
    if actual != expected || identity.session_id != endpoint.session_id {
        return Err(StateError::RoleBindingInvalid {
            role: identity.role,
            reason: "runtime, provider, model, reasoning, adapter, and session must match the fixed role contract"
                .into(),
        });
    }
    Ok(())
}

fn validate_engineering_endpoint_binding(
    role: Role,
    endpoint: &crate::model::EndpointIdentity,
) -> Result<(), StateError> {
    let expected = match role {
        Role::Supervisor => "codex-app-server",
        Role::Checker => "ocrv-checker",
        Role::Worker => "dsh-worker",
        Role::Overwatcher => return Ok(()),
    };
    if endpoint.transport_adapter != expected {
        return Err(StateError::RoleBindingInvalid {
            role,
            reason: "session rebound must retain the fixed role adapter".into(),
        });
    }
    Ok(())
}

fn insert_role_instance(
    connection: &Connection,
    run_id: &str,
    identity: &crate::model::RoleIdentity,
    occurred_at: &str,
) -> Result<(), StateError> {
    connection.execute(
        "INSERT INTO role_instances
         (role_instance_id, run_id, role, agent_runtime, provider, model, reasoning, session_id, lifecycle, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'active', ?9)",
        params![
            identity.role_instance_id,
            run_id,
            identity.role.as_str(),
            identity.agent_runtime,
            identity.provider,
            identity.model,
            identity.reasoning,
            identity.session_id,
            occurred_at
        ],
    )?;
    Ok(())
}

fn insert_endpoint(
    connection: &Connection,
    run_id: &str,
    role_instance_id: &str,
    endpoint: &crate::model::EndpointIdentity,
    occurred_at: &str,
) -> Result<(), StateError> {
    connection.execute(
        "INSERT INTO role_endpoints
         (run_id, role_instance_id, endpoint_version, transport_adapter, host_identity,
          session_id, native_address_json, state, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 'active', ?8)",
        params![
            run_id,
            role_instance_id,
            endpoint.endpoint_version,
            endpoint.transport_adapter,
            endpoint.host_identity,
            endpoint.session_id,
            serde_json::to_string(&endpoint.native_address)?,
            occurred_at
        ],
    )?;
    Ok(())
}

fn current_plan_revision(connection: &Connection, run_id: &str) -> Result<u32, StateError> {
    connection
        .query_row(
            "SELECT current_plan_revision FROM runs WHERE run_id=?1",
            [run_id],
            |row| row.get::<_, u32>(0),
        )
        .optional()?
        .ok_or_else(|| StateError::RunNotFound(run_id.to_string()))
}

fn current_runtime_revision(connection: &Connection, run_id: &str) -> Result<u64, StateError> {
    connection
        .query_row(
            "SELECT current_runtime_revision FROM runs WHERE run_id=?1",
            [run_id],
            |row| row.get::<_, u64>(0),
        )
        .optional()?
        .ok_or_else(|| StateError::RunNotFound(run_id.to_string()))
}

fn insert_runtime_snapshot(
    transaction: &Transaction<'_>,
    run_id: &str,
    runtime_revision: u64,
    latest_event_id: &str,
    latest_message_id: Option<&str>,
    committed_at: &str,
) -> Result<(), StateError> {
    let plan_revision = current_plan_revision(transaction, run_id)?;
    let token = current_token_from(transaction, run_id)?;
    let method_version: String = transaction.query_row(
        "SELECT slk_version FROM runs WHERE run_id=?1",
        [run_id],
        |row| row.get(0),
    )?;
    let overwatcher: Option<(u64, String)> = transaction
        .query_row(
            "SELECT binding_revision, continuity_state
             FROM overwatcher_bindings WHERE run_id=?1",
            [run_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    let (overwatcher_binding_revision, overwatcher_status) = match overwatcher {
        Some((revision, status)) => (Some(revision), Some(status)),
        None => (None, None),
    };
    transaction.execute(
        "INSERT INTO run_runtime_snapshots
         (run_id, runtime_revision, plan_revision, token_sequence,
          token_holder_role_instance_id, latest_event_id, latest_message_id,
          method_version, overwatcher_binding_revision, overwatcher_status, committed_at)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
        params![
            run_id,
            runtime_revision,
            plan_revision,
            token.sequence,
            token.owner_role_instance_id,
            latest_event_id,
            latest_message_id,
            method_version,
            overwatcher_binding_revision,
            overwatcher_status,
            committed_at,
        ],
    )?;
    Ok(())
}

fn advance_runtime_snapshot(
    transaction: &Transaction<'_>,
    run_id: &str,
    latest_event_id: &str,
    latest_message_id: Option<&str>,
    committed_at: &str,
) -> Result<u64, StateError> {
    let revision = current_runtime_revision(transaction, run_id)? + 1;
    transaction.execute(
        "UPDATE runs SET current_runtime_revision=?2 WHERE run_id=?1",
        params![run_id, revision],
    )?;
    insert_runtime_snapshot(
        transaction,
        run_id,
        revision,
        latest_event_id,
        latest_message_id,
        committed_at,
    )?;
    Ok(revision)
}

pub(crate) fn advance_runtime_snapshot_if_revisioned(
    transaction: &Transaction<'_>,
    run_id: &str,
    latest_event_id: &str,
    committed_at: &str,
) -> Result<Option<u64>, StateError> {
    let method_version: String = transaction.query_row(
        "SELECT slk_version FROM runs WHERE run_id=?1",
        [run_id],
        |row| row.get(0),
    )?;
    if !uses_revisioned_runtime_contract(&method_version) {
        return Ok(None);
    }
    let snapshot = runtime_snapshot_from(transaction, run_id)?;
    advance_runtime_snapshot(
        transaction,
        run_id,
        latest_event_id,
        snapshot.latest_message_id.as_deref(),
        committed_at,
    )
    .map(Some)
}

pub(crate) fn runtime_snapshot_from(
    connection: &Connection,
    run_id: &str,
) -> Result<RuntimeSnapshot, StateError> {
    connection
        .query_row(
            "SELECT run_id, runtime_revision, plan_revision, token_sequence,
                    token_holder_role_instance_id, latest_event_id, latest_message_id,
                    method_version, overwatcher_binding_revision, overwatcher_status, committed_at
             FROM run_runtime_snapshots WHERE run_id=?1
             ORDER BY runtime_revision DESC LIMIT 1",
            [run_id],
            |row| {
                Ok(RuntimeSnapshot {
                    run_id: row.get(0)?,
                    runtime_revision: row.get(1)?,
                    plan_revision: row.get(2)?,
                    token_sequence: row.get(3)?,
                    token_holder_role_instance_id: row.get(4)?,
                    latest_event_id: row.get(5)?,
                    latest_message_id: row.get(6)?,
                    method_version: row.get(7)?,
                    overwatcher_binding_revision: row.get(8)?,
                    overwatcher_status: row.get(9)?,
                    committed_at: row.get(10)?,
                })
            },
        )
        .optional()?
        .ok_or_else(|| StateError::RunNotFound(run_id.to_string()))
}

fn delivery_start_result_from(
    connection: &Connection,
    run_id: &str,
    event_id: &str,
    message_id: &str,
    status: &str,
) -> Result<DeliveryStartResult, StateError> {
    let snapshot = runtime_snapshot_from(connection, run_id)?;
    Ok(DeliveryStartResult {
        status: status.to_string(),
        runtime_revision: snapshot.runtime_revision,
        token: current_token_from(connection, run_id)?,
        event_id: event_id.to_string(),
        message_id: message_id.to_string(),
    })
}

pub(crate) fn current_token_from(
    connection: &Connection,
    run_id: &str,
) -> Result<CurrentToken, StateError> {
    connection
        .query_row(
            "SELECT token_sequence, to_role_instance_id, go_id, cell_id
             FROM token_events WHERE run_id=?1 ORDER BY token_sequence DESC LIMIT 1",
            [run_id],
            |row| {
                Ok(CurrentToken {
                    sequence: row.get(0)?,
                    owner_role_instance_id: row.get(1)?,
                    go_id: row.get(2)?,
                    cell_id: row.get(3)?,
                })
            },
        )
        .optional()?
        .ok_or_else(|| StateError::RunNotFound(run_id.to_string()))
}

fn projected_cell_state(event: EventType) -> Option<&'static str> {
    match event {
        EventType::CellDispatched => Some("dispatched"),
        EventType::WorkStarted | EventType::WorkProgress => Some("working"),
        EventType::D0Completed => Some("d0_complete"),
        EventType::CandidateSubmitted => Some("candidate_ready"),
        EventType::D1Failed | EventType::ReworkRequested => Some("rework_required"),
        EventType::D1Incomplete => Some("d1_incomplete"),
        EventType::D1Passed => Some("d1_passed"),
        _ => None,
    }
}

fn valid_token_route(from: Role, to: Role) -> bool {
    matches!(
        (from, to),
        (Role::Supervisor, Role::Checker)
            | (Role::Checker, Role::Worker)
            | (Role::Worker, Role::Checker)
            | (Role::Checker, Role::Supervisor)
    )
}

fn valid_token_handoff_route(
    connection: &Connection,
    request: &TokenHandoffRequest,
    from: Role,
    to: Role,
) -> Result<bool, StateError> {
    let latest_d1 = latest_d1_state(connection, request)?;
    if from == Role::Checker && latest_d1.as_deref() == Some("D1_INCOMPLETE") {
        return Ok(false);
    }
    if from == Role::Checker && latest_d1.as_deref() == Some("D1_FAILED") {
        return Ok(to == Role::Supervisor && request.payload_type == "D1_FAILURE_ESCALATION");
    }
    match request.payload_type.as_str() {
        "D1_FAILURE_ESCALATION" => Ok(false),
        "D1_REWORK_DIRECTIVE" => valid_supervisor_rework_route(connection, request, from, to),
        _ => Ok(valid_token_route(from, to)),
    }
}

fn valid_supervisor_rework_route(
    connection: &Connection,
    request: &TokenHandoffRequest,
    from: Role,
    to: Role,
) -> Result<bool, StateError> {
    if (from, to) != (Role::Supervisor, Role::Worker)
        || request.payload_type != "D1_REWORK_DIRECTIVE"
    {
        return Ok(false);
    }

    let prior_handoff: Option<(String, String, String, String)> = connection
        .query_row(
            "SELECT from_role_instance_id, payload_type, go_id, cell_id
             FROM token_events WHERE run_id=?1 ORDER BY token_sequence DESC LIMIT 1",
            [&request.run_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )
        .optional()?;
    let Some((prior_sender, prior_payload, prior_go, prior_cell)) = prior_handoff else {
        return Ok(false);
    };
    let prior_sender_role: Option<String> = connection
        .query_row(
            "SELECT role FROM role_instances
             WHERE run_id=?1 AND role_instance_id=?2 AND lifecycle='active'",
            params![request.run_id, prior_sender],
            |row| row.get(0),
        )
        .optional()?;
    if prior_sender_role.as_deref() != Some("checker")
        || prior_payload != "D1_FAILURE_ESCALATION"
        || prior_go != request.go_id
        || prior_cell != request.cell_id
    {
        return Ok(false);
    }

    Ok(latest_d1_state(connection, request)?.as_deref() == Some("D1_FAILED"))
}

fn latest_d1_state(
    connection: &Connection,
    request: &TokenHandoffRequest,
) -> Result<Option<String>, StateError> {
    connection
        .query_row(
            "SELECT event_type FROM work_events
             WHERE run_id=?1 AND go_id=?2 AND cell_id=?3
               AND event_type IN ('D1_FAILED', 'D1_PASSED', 'D1_INCOMPLETE')
             ORDER BY rowid DESC LIMIT 1",
            params![request.run_id, request.go_id, request.cell_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(StateError::from)
}

fn validate_reconciliation_request(
    request: &ReconcileRunIdentitiesRequest,
) -> Result<(), StateError> {
    if !valid_identifier(&request.receipt_id)
        || !valid_identifier(&request.canonical_run_id)
        || request.canonical_snapshot.run_id != request.canonical_run_id
        || request.reason.trim().is_empty()
        || request.source_snapshots.is_empty()
    {
        return Err(StateError::RunAdministrationInvalid(
            "receipt, canonical Run, explicit sources, and reason are required".into(),
        ));
    }
    validate_owner_authorization(
        &request.owner_authorization,
        &[
            OwnerDecision::ApproveRunIdentityReconciliation,
            OwnerDecision::ApproveReconciliationAndAdoption,
        ],
    )?;
    validate_admin_timestamp(&request.occurred_at)?;
    let mut sources = BTreeSet::new();
    for snapshot in &request.source_snapshots {
        if !valid_identifier(&snapshot.run_id)
            || snapshot.run_id == request.canonical_run_id
            || !sources.insert(snapshot.run_id.as_str())
        {
            return Err(StateError::RunAdministrationInvalid(
                "source Run IDs must be explicit, unique, and different from canonical".into(),
            ));
        }
    }
    Ok(())
}

fn uses_revisioned_runtime_contract(version: &str) -> bool {
    matches!(version, "4.2.3" | "4.2.4")
}

fn validate_method_adoption_request(
    request: &AdoptMethodContractRequest,
) -> Result<(), StateError> {
    let supported_transition =
        (matches!(request.from_version.as_str(), "4.1.1" | "4.2.0" | "4.2.1")
            && request.to_version == "4.2.2")
            || (request.from_version == "4.2.2" && request.to_version == "4.2.3")
            || (request.from_version == "4.2.3" && request.to_version == "4.2.4");
    if !valid_identifier(&request.receipt_id)
        || !valid_identifier(&request.run_id)
        || request.expected_snapshot.run_id != request.run_id
        || request.reason.trim().is_empty()
        || !supported_transition
        || request.from_version == request.to_version
        || request
            .reconciliation_receipt_id
            .as_deref()
            .is_some_and(|value| !valid_identifier(value))
    {
        return Err(StateError::RunAdministrationInvalid(
            "method adoption requires a declared compatible version transition and closed identities"
                .into(),
        ));
    }
    validate_owner_authorization(
        &request.owner_authorization,
        &[
            OwnerDecision::ApproveMethodContractAdoption,
            OwnerDecision::ApproveReconciliationAndAdoption,
        ],
    )?;
    validate_admin_timestamp(&request.occurred_at)
}

fn validate_delivery_start_request(request: &CommitDeliveryStartRequest) -> Result<(), StateError> {
    let identifiers = [
        request.event_id.as_str(),
        request.transport_receipt_id.as_str(),
        request.run_id.as_str(),
        request.go_id.as_str(),
        request.cell_id.as_str(),
        request.message_id.as_str(),
        request.from_role_instance_id.as_str(),
        request.to_role_instance_id.as_str(),
        request.start_evidence.evidence_id.as_str(),
    ];
    if identifiers.iter().any(|value| !valid_identifier(value))
        || request.attempt == 0
        || request.plan_revision == 0
        || request.expected_runtime_revision == 0
        || request.token_sequence == 0
        || request.endpoint_version == 0
        || request.payload_type.trim().is_empty()
        || request.start_evidence.message_id != request.message_id
        || !is_lower_sha256(&request.payload_sha256)
        || !is_lower_sha256(&request.start_evidence.sha256)
        || !is_lower_sha256(&request.start_evidence.endpoint_sha256)
        || !is_lower_sha256(&request.start_evidence.envelope_sha256)
    {
        return Err(StateError::EvidenceInvalid(
            "delivery-start identity, binding, or digest is invalid".into(),
        ));
    }
    validate_admin_timestamp(&request.occurred_at)
}

fn validate_owner_authorization(
    evidence: &OwnerAuthorizationEvidence,
    allowed: &[OwnerDecision],
) -> Result<(), StateError> {
    if !valid_identifier(&evidence.source_thread_id)
        || !valid_identifier(&evidence.message_id)
        || !is_lower_sha256(&evidence.content_sha256)
        || !allowed.contains(&evidence.decision)
    {
        return Err(StateError::RunAdministrationInvalid(
            "closed Owner authorization evidence is missing or invalid".into(),
        ));
    }
    validate_admin_timestamp(&evidence.occurred_at)
}

fn validate_admin_timestamp(value: &str) -> Result<(), StateError> {
    OffsetDateTime::parse(value, &Rfc3339)
        .map(|_| ())
        .map_err(|_| StateError::RunAdministrationInvalid("timestamps must be RFC3339".into()))
}

fn is_lower_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn snapshot_is_open(snapshot: &RunStateSnapshot) -> bool {
    snapshot.state != "archived"
        && snapshot.closure_state == "open"
        && snapshot.archived_at.is_none()
        && snapshot.superseded_by_run_id.is_none()
}

struct RunSnapshotRow {
    project_id: String,
    slk_version: String,
    state: String,
    closure_state: String,
    archived_at: Option<String>,
    superseded_by_run_id: Option<String>,
    predecessor_run_id: Option<String>,
}

pub(crate) fn run_state_snapshot_from(
    connection: &Connection,
    run_id: &str,
) -> Result<RunStateSnapshot, StateError> {
    let run: Option<RunSnapshotRow> = connection
        .query_row(
            "SELECT r.project_id, r.slk_version, r.state, r.closure_state,
                    r.archived_at, r.superseded_by_run_id, l.predecessor_run_id
             FROM runs r LEFT JOIN run_lineage l ON l.successor_run_id=r.run_id
             WHERE r.run_id=?1",
            [run_id],
            |row| {
                Ok(RunSnapshotRow {
                    project_id: row.get(0)?,
                    slk_version: row.get(1)?,
                    state: row.get(2)?,
                    closure_state: row.get(3)?,
                    archived_at: row.get(4)?,
                    superseded_by_run_id: row.get(5)?,
                    predecessor_run_id: row.get(6)?,
                })
            },
        )
        .optional()?;
    let Some(run) = run else {
        return Err(StateError::RunNotFound(run_id.to_string()));
    };
    let (event_count, latest_event_id): (u64, String) = connection.query_row(
        "SELECT COUNT(*), COALESCE((SELECT event_id FROM work_events
                                   WHERE run_id=?1 ORDER BY rowid DESC LIMIT 1), '')
         FROM work_events WHERE run_id=?1",
        [run_id],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    let token = current_token_from(connection, run_id)?;
    let role_count: u64 = connection.query_row(
        "SELECT COUNT(*) FROM role_instances WHERE run_id=?1",
        [run_id],
        |row| row.get(0),
    )?;
    let evidence_count: u64 = connection.query_row(
        "SELECT COUNT(*) FROM evidence WHERE run_id=?1",
        [run_id],
        |row| row.get(0),
    )?;
    Ok(RunStateSnapshot {
        run_id: run_id.to_string(),
        project_id: run.project_id,
        slk_version: run.slk_version,
        state: run.state,
        closure_state: run.closure_state,
        archived_at: run.archived_at,
        superseded_by_run_id: run.superseded_by_run_id,
        predecessor_run_id: run.predecessor_run_id,
        event_count,
        latest_event_id,
        token_sequence: token.sequence,
        token_holder_role_instance_id: token.owner_role_instance_id,
        role_count,
        evidence_count,
    })
}

pub(crate) fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn is_busy(error: &rusqlite::Error) -> bool {
    matches!(
        error.sqlite_error_code(),
        Some(ErrorCode::DatabaseBusy | ErrorCode::DatabaseLocked)
    )
}
