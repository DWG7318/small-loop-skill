//! Atomic Run, role, work-event, and SLK TOKEN transactions.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use rusqlite::{
    params, Connection, ErrorCode, OptionalExtension, Transaction, TransactionBehavior,
};
use sha2::{Digest, Sha256};

use crate::auth::{
    authorize_event, issue_credential, revoke_credential, AuthorizedActor, Credential,
    IssuedCredential, StateError,
};
use crate::model::{
    EventType, InitRunRequest, RebindSessionRequest, RegisterRoleRequest, ReplaceRoleRequest,
    RevisePlanRequest, Role, TokenHandoffRequest, WriteRequest,
};
use crate::schema::{open_database, SchemaError};

const TRANSACTION_ATTEMPTS: usize = 3;

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

impl StateStore {
    pub fn new(data_root: impl AsRef<Path>) -> Self {
        Self {
            data_root: data_root.as_ref().to_path_buf(),
        }
    }

    pub fn init_run(&self, request: InitRunRequest) -> Result<InitializedRun, StateError> {
        validate_linear_plan(&request)?;
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
                 (run_id, project_id, run_name, run_description, slk_version,
                  source_kind, source_project_name, goal, boundaries_json, state,
                  current_plan_revision, closure_state, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, 'active', 1, 'open', ?10)",
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
            Ok(InitializedRun {
                supervisor_credential: issued.credential,
            })
        })
    }

    pub fn register_role(
        &self,
        credential: &Credential,
        request: RegisterRoleRequest,
    ) -> Result<IssuedCredential, StateError> {
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
            Ok(issued)
        })
    }

    pub fn handoff_token(
        &self,
        credential: &Credential,
        request: TokenHandoffRequest,
    ) -> Result<CurrentToken, StateError> {
        self.with_immediate_transaction(|transaction| {
            let actor = authorize_event(
                transaction,
                &request.run_id,
                credential,
                EventType::TokenHandedOff,
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
            if !valid_token_route(actor.role, target_role) {
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
            Ok(revision)
        })
    }

    pub fn replace_role(
        &self,
        credential: &Credential,
        request: ReplaceRoleRequest,
    ) -> Result<IssuedCredential, StateError> {
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

fn validate_linear_plan(request: &InitRunRequest) -> Result<(), StateError> {
    if !valid_identifier(&request.project.project_id)
        || !valid_identifier(&request.run_id)
        || !valid_identifier(&request.supervisor.role_instance_id)
    {
        return Err(StateError::InvalidPlan(
            "project, Run, and role identities must be safe path segments".into(),
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
