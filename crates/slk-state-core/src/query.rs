//! Stable read-only projections for Agents, the query CLI, and future BI.

use std::collections::{HashMap, HashSet};
use std::thread;
use std::time::{Duration, Instant};

use rusqlite::{params, Connection, OptionalExtension};
use serde::Serialize;
use serde_json::{json, Value};

use crate::auth::StateError;
use crate::model::RuntimeSnapshot;
use crate::model::{OwnerAuthorizationEvidence, RunStateSnapshot};
use crate::schema::open_database_read_only;
use crate::write::{run_state_snapshot_from, runtime_snapshot_from, StateStore};

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ProjectSummary {
    pub project_id: String,
    pub name: String,
    pub repository_url: Option<String>,
    pub last_known_path: String,
    pub run_count: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RunSummary {
    pub run_id: String,
    pub project_id: String,
    pub run_name: String,
    pub run_description: String,
    pub slk_version: String,
    pub origin_slk_version: String,
    pub source_kind: String,
    pub source_project_name: Option<String>,
    pub goal: String,
    pub state: String,
    pub current_plan_revision: u32,
    pub closure_state: String,
    pub created_at: String,
    pub closed_at: Option<String>,
    pub archive_reason: Option<String>,
    pub archived_at: Option<String>,
    pub superseded_by_run_id: Option<String>,
    pub predecessor_run_id: Option<String>,
    pub lineage_root_run_id: String,
    pub identity_state: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CellProjection {
    pub cell_id: String,
    pub ordinal: u32,
    pub title: String,
    pub objective: String,
    pub state: String,
    pub attempt: u32,
    pub outcome: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GoProjection {
    pub go_id: String,
    pub ordinal: u32,
    pub title: String,
    pub objective: String,
    pub state: String,
    pub outcome: Option<String>,
    pub cell_nodes: Vec<CellProjection>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RoleProjection {
    pub role: String,
    pub role_instance_id: String,
    pub agent_runtime: String,
    pub provider: String,
    pub model: String,
    pub reasoning: String,
    pub session_id: String,
    pub lifecycle: String,
    pub predecessor_role_instance_id: Option<String>,
    pub successor_role_instance_id: Option<String>,
    pub current_go_id: Option<String>,
    pub current_cell_id: Option<String>,
    pub created_at: String,
    pub takeover_at: Option<String>,
    pub exited_at: Option<String>,
    pub endpoints: Vec<EndpointProjection>,
    pub display_state: String,
    pub binding_mode: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct EndpointProjection {
    pub endpoint_version: u32,
    pub transport_adapter: String,
    pub host_identity: String,
    pub session_id: String,
    pub state: String,
    pub created_at: String,
    pub retired_at: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PlanRevisionProjection {
    pub revision: u32,
    pub author_role_instance_id: String,
    pub reason: String,
    pub previous_revision: Option<u32>,
    pub created_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct EventProjection {
    pub event_id: String,
    pub event_type: String,
    pub author_role_instance_id: String,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
    pub attempt: Option<u32>,
    pub details_json: String,
    pub corrects_event_id: Option<String>,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TokenProjection {
    pub token_sequence: u64,
    pub from_role_instance_id: Option<String>,
    pub to_role_instance_id: String,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
    pub message_id: Option<String>,
    pub event_type: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct EvidenceProjection {
    pub evidence_id: String,
    pub evidence_type: String,
    pub stored_path: String,
    pub sha256: String,
    pub byte_length: u64,
    pub producing_role_instance_id: String,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
    pub created_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OperationalObservationProjection {
    pub observation_id: String,
    pub overwatcher_role_instance_id: String,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
    pub attempt: Option<u32>,
    pub plan_revision: u32,
    pub kind: String,
    pub related_event_id: Option<String>,
    pub message_id: Option<String>,
    pub evidence_refs_json: String,
    pub details_json: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OverwatchCycleProjection {
    pub cycle_id: String,
    pub overwatcher_role_instance_id: String,
    pub session_id: String,
    pub foreground_turn_id: String,
    pub cycle_sequence: u64,
    pub cadence_seconds: u32,
    pub plan_revision: u32,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
    pub attempt: Option<u32>,
    pub token_sequence: u64,
    pub token_holder_role_instance_id: String,
    pub latest_event_id: String,
    pub latest_message_id: Option<String>,
    pub checklist_json: String,
    pub anomaly_codes_json: String,
    pub evidence_refs_json: String,
    pub native_active_session_evidence_ref: String,
    pub started_at: String,
    pub completed_at: String,
    pub next_cycle_at: String,
    pub binding_revision: u64,
    pub runtime_revision: u64,
    pub native_liveness: String,
    pub cadence_health: String,
    pub cost_metrics_json: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OverwatcherNativeStatusProjection {
    pub status_id: String,
    pub binding_revision: u64,
    pub role_instance_id: String,
    pub session_id: String,
    pub foreground_turn_id: String,
    pub native_liveness: String,
    pub evidence_path: String,
    pub evidence_sha256: String,
    pub observed_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OverwatcherIncidentTransitionProjection {
    pub transition_id: String,
    pub incident_id: String,
    pub binding_revision: u64,
    pub incident_code: String,
    pub state: String,
    pub evidence_path: String,
    pub evidence_sha256: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OverwatcherBindingTransitionProjection {
    pub transition_id: String,
    pub binding_revision: u64,
    pub transition_type: String,
    pub cycle_id: Option<String>,
    pub runtime_revision: u64,
    pub evidence_ref: String,
    pub occurred_at: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum WaitForChangeStatus {
    Changed,
    Timeout,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct WaitForChangeResult {
    pub status: WaitForChangeStatus,
    pub run_id: String,
    pub after_revision: u64,
    pub current_revision: u64,
}

struct OverwatcherBindingRow {
    role_instance_id: String,
    agent_runtime: String,
    provider: String,
    model: String,
    reasoning: String,
    session_id: String,
    endpoint_version: u32,
    transport_adapter: String,
    host_identity: String,
    lifecycle_state: String,
    bound_at: String,
    closed_at: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RunProjection {
    pub schema_version: u32,
    pub summary: RunSummary,
    pub administrative_snapshot: RunStateSnapshot,
    pub runtime_snapshot: Option<RuntimeSnapshot>,
    pub boundaries_json: String,
    pub go_nodes: Vec<GoProjection>,
    pub roles: Vec<RoleProjection>,
    pub plan_revisions: Vec<PlanRevisionProjection>,
    pub events: Vec<EventProjection>,
    pub native_invocations: Vec<NativeInvocationProjection>,
    pub token_history: Vec<TokenProjection>,
    pub evidence: Vec<EvidenceProjection>,
    pub overwatch_cycles: Vec<OverwatchCycleProjection>,
    pub overwatcher_native_status_receipts: Vec<OverwatcherNativeStatusProjection>,
    pub overwatcher_incident_transitions: Vec<OverwatcherIncidentTransitionProjection>,
    pub overwatcher_binding_transitions: Vec<OverwatcherBindingTransitionProjection>,
    pub operational_observations: Vec<OperationalObservationProjection>,
    pub reconciliation_receipts: Vec<RunIdentityReconciliationReceiptProjection>,
    pub method_adoption_receipts: Vec<MethodAdoptionReceiptProjection>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct NativeInvocationProjection {
    pub message_id: String,
    pub role_instance_id: String,
    pub start_evidence_path: String,
    pub start_evidence_sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RunIdentityReconciliationReceiptProjection {
    pub receipt_id: String,
    pub canonical_run_id: String,
    pub source_run_ids: Vec<String>,
    pub owner_source_thread_id: String,
    pub owner_message_id: String,
    pub owner_decision: String,
    pub reason: String,
    pub occurred_at: String,
    pub payload_sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MethodAdoptionReceiptProjection {
    pub receipt_id: String,
    pub run_id: String,
    pub from_version: String,
    pub to_version: String,
    pub reconciliation_receipt_id: Option<String>,
    pub owner_source_thread_id: String,
    pub owner_message_id: String,
    pub owner_decision: String,
    pub reason: String,
    pub occurred_at: String,
    pub payload_sha256: String,
}

impl RunProjection {
    pub fn role(&self, role: &str) -> Option<&RoleProjection> {
        self.roles
            .iter()
            .find(|item| item.role == role && item.lifecycle == "active")
    }
}

impl StateStore {
    pub fn list_projects(&self) -> Result<Vec<ProjectSummary>, StateError> {
        let connection = open_database_read_only(&self.data_root)?;
        let mut statement = connection.prepare(
            "SELECT p.project_id, p.name, p.repository_url, p.last_known_path, COUNT(r.run_id)
             FROM projects p LEFT JOIN runs r ON r.project_id=p.project_id
             GROUP BY p.project_id, p.name, p.repository_url, p.last_known_path
             ORDER BY p.name, p.project_id",
        )?;
        let rows = statement.query_map([], |row| {
            Ok(ProjectSummary {
                project_id: row.get(0)?,
                name: row.get(1)?,
                repository_url: row.get(2)?,
                last_known_path: row.get(3)?,
                run_count: row.get(4)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn list_runs(&self, project_id: Option<&str>) -> Result<Vec<RunSummary>, StateError> {
        let connection = open_database_read_only(&self.data_root)?;
        load_run_summaries(&connection, project_id)
    }

    pub fn query_run(&self, run_id: &str) -> Result<RunProjection, StateError> {
        if run_id.is_empty() {
            return Err(StateError::RunIdRequired);
        }
        let connection = open_database_read_only(&self.data_root)?;
        let row: Option<(String, String)> = connection
            .query_row(
                "SELECT project_id, boundaries_json FROM runs WHERE run_id=?1",
                [run_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        let (project_id, boundaries_json) =
            row.ok_or_else(|| StateError::RunNotFound(run_id.to_string()))?;
        let summary = load_run_summaries(&connection, Some(&project_id))?
            .into_iter()
            .find(|summary| summary.run_id == run_id)
            .ok_or_else(|| StateError::RunNotFound(run_id.to_string()))?;
        Ok(RunProjection {
            schema_version: connection
                .pragma_query_value(None, "user_version", |row| row.get(0))?,
            summary,
            administrative_snapshot: run_state_snapshot_from(&connection, run_id)?,
            runtime_snapshot: Some(runtime_snapshot_from(&connection, run_id)?),
            boundaries_json,
            go_nodes: load_go_nodes(&connection, run_id)?,
            roles: load_roles(&connection, run_id)?,
            plan_revisions: load_plan_revisions(&connection, run_id)?,
            events: load_events(&connection, run_id)?,
            native_invocations: {
                let mut statement = connection.prepare("SELECT message_id, to_role_instance_id, evidence_path, evidence_sha256
                    FROM transport_start_receipts WHERE run_id=?1 ORDER BY rowid")?;
                let rows = statement.query_map([run_id], |row| Ok(NativeInvocationProjection {
                    message_id: row.get(0)?, role_instance_id: row.get(1)?,
                    start_evidence_path: row.get(2)?, start_evidence_sha256: row.get(3)?,
                }))?.collect::<Result<Vec<_>, _>>()?;
                rows
            },
            token_history: load_tokens(&connection, run_id)?,
            evidence: load_evidence(&connection, run_id)?,
            overwatch_cycles: load_overwatch_cycles(&connection, run_id)?,
            overwatcher_native_status_receipts: load_overwatcher_native_statuses(
                &connection,
                run_id,
            )?,
            overwatcher_incident_transitions: load_overwatcher_incident_transitions(
                &connection,
                run_id,
            )?,
            overwatcher_binding_transitions: load_overwatcher_binding_transitions(
                &connection,
                run_id,
            )?,
            operational_observations: load_operational_observations(&connection, run_id)?,
            reconciliation_receipts: load_reconciliation_receipts(&connection, run_id)?,
            method_adoption_receipts: load_method_adoption_receipts(&connection, run_id)?,
        })
    }

    pub fn projects_view(&self) -> Result<Value, StateError> {
        Ok(json!({
            "schema_version": "slk.bi.projects/v1",
            "projects": self.list_projects()?
        }))
    }

    pub fn runs_view(&self, project_id: Option<&str>) -> Result<Value, StateError> {
        Ok(json!({
            "schema_version": "slk.bi.runs/v1",
            "runs": self.list_runs(project_id)?
        }))
    }

    pub fn run_view(&self, run_id: &str) -> Result<Value, StateError> {
        let projection = self.query_run(run_id)?;
        let mut value = serde_json::to_value(projection)?;
        let object = value
            .as_object_mut()
            .expect("RunProjection serializes as an object");
        object.insert("schema_version".into(), json!("slk.bi.run/v1"));
        object.insert("run_id".into(), json!(run_id));
        Ok(value)
    }

    pub fn graph_view(&self, run_id: &str) -> Result<Value, StateError> {
        let projection = self.query_run(run_id)?;
        Ok(
            json!({"schema_version":"slk.bi.graph/v1","run_id":run_id,"go_nodes":projection.go_nodes}),
        )
    }

    pub fn roles_view(&self, run_id: &str) -> Result<Value, StateError> {
        let projection = self.query_run(run_id)?;
        Ok(json!({"schema_version":"slk.bi.roles/v1","run_id":run_id,"roles":projection.roles}))
    }

    pub fn plans_view(&self, run_id: &str) -> Result<Value, StateError> {
        let projection = self.query_run(run_id)?;
        Ok(
            json!({"schema_version":"slk.bi.plans/v1","run_id":run_id,"plan_revisions":projection.plan_revisions}),
        )
    }

    pub fn events_view(&self, run_id: &str) -> Result<Value, StateError> {
        let projection = self.query_run(run_id)?;
        Ok(json!({"schema_version":"slk.bi.events/v1","run_id":run_id,"events":projection.events}))
    }

    pub fn evidence_view(&self, run_id: &str) -> Result<Value, StateError> {
        let projection = self.query_run(run_id)?;
        Ok(
            json!({"schema_version":"slk.bi.evidence/v1","run_id":run_id,"evidence":projection.evidence}),
        )
    }

    pub fn wait_for_change(
        &self,
        run_id: &str,
        after_revision: u64,
        timeout_seconds: u64,
    ) -> Result<WaitForChangeResult, StateError> {
        let started = Instant::now();
        self.wait_for_change_with(
            run_id,
            after_revision,
            timeout_seconds,
            move || started.elapsed().as_millis() as u64,
            |millis| thread::sleep(Duration::from_millis(millis)),
        )
    }

    pub fn wait_for_change_with<N, S>(
        &self,
        run_id: &str,
        after_revision: u64,
        timeout_seconds: u64,
        mut monotonic_millis: N,
        mut sleep_millis: S,
    ) -> Result<WaitForChangeResult, StateError>
    where
        N: FnMut() -> u64,
        S: FnMut(u64),
    {
        if run_id.is_empty() || !(1..=300).contains(&timeout_seconds) {
            return Err(StateError::RunAdministrationInvalid(
                "wait-for-change requires a Run and 1-300 second bound".into(),
            ));
        }
        let deadline = monotonic_millis().saturating_add(timeout_seconds.saturating_mul(1_000));
        loop {
            let connection = open_database_read_only(&self.data_root)?;
            let current: u64 = connection
                .query_row(
                    "SELECT current_runtime_revision FROM runs WHERE run_id=?1",
                    [run_id],
                    |row| row.get(0),
                )
                .optional()?
                .ok_or_else(|| StateError::RunNotFound(run_id.to_string()))?;
            if after_revision > current {
                return Err(StateError::RunAdministrationInvalid(
                    "after_revision is ahead of authoritative runtime state".into(),
                ));
            }
            if current > after_revision {
                return Ok(WaitForChangeResult {
                    status: WaitForChangeStatus::Changed,
                    run_id: run_id.to_string(),
                    after_revision,
                    current_revision: current,
                });
            }
            let now = monotonic_millis();
            if now >= deadline {
                return Ok(WaitForChangeResult {
                    status: WaitForChangeStatus::Timeout,
                    run_id: run_id.to_string(),
                    after_revision,
                    current_revision: current,
                });
            }
            sleep_millis((deadline - now).min(100));
        }
    }
}

fn load_run_summaries(
    connection: &Connection,
    project_id: Option<&str>,
) -> Result<Vec<RunSummary>, StateError> {
    let (sql, value) = if let Some(project_id) = project_id {
        (
            "SELECT r.run_id, r.project_id, r.run_name, r.run_description, r.slk_version,
                        r.origin_slk_version,
                        r.source_kind, r.source_project_name, r.goal, r.state,
                        r.current_plan_revision, r.closure_state, r.created_at, r.closed_at,
                        r.archive_reason, r.archived_at, r.superseded_by_run_id,
                        l.predecessor_run_id
                 FROM runs r LEFT JOIN run_lineage l ON l.successor_run_id=r.run_id
                 WHERE r.project_id=?1 ORDER BY r.created_at DESC, r.run_id",
            Some(project_id),
        )
    } else {
        (
            "SELECT r.run_id, r.project_id, r.run_name, r.run_description, r.slk_version,
                        r.origin_slk_version,
                        r.source_kind, r.source_project_name, r.goal, r.state,
                        r.current_plan_revision, r.closure_state, r.created_at, r.closed_at,
                        r.archive_reason, r.archived_at, r.superseded_by_run_id,
                        l.predecessor_run_id
                 FROM runs r LEFT JOIN run_lineage l ON l.successor_run_id=r.run_id
                 ORDER BY r.created_at DESC, r.run_id",
            None,
        )
    };
    let mut statement = connection.prepare(sql)?;
    let mapper = |row: &rusqlite::Row<'_>| {
        Ok(RunSummary {
            run_id: row.get(0)?,
            project_id: row.get(1)?,
            run_name: row.get(2)?,
            run_description: row.get(3)?,
            slk_version: row.get(4)?,
            origin_slk_version: row.get(5)?,
            source_kind: row.get(6)?,
            source_project_name: row.get(7)?,
            goal: row.get(8)?,
            state: row.get(9)?,
            current_plan_revision: row.get(10)?,
            closure_state: row.get(11)?,
            created_at: row.get(12)?,
            closed_at: row.get(13)?,
            archive_reason: row.get(14)?,
            archived_at: row.get(15)?,
            superseded_by_run_id: row.get(16)?,
            predecessor_run_id: row.get(17)?,
            lineage_root_run_id: row.get(0)?,
            identity_state: String::new(),
        })
    };
    let rows = match value {
        Some(project_id) => statement.query_map([project_id], mapper)?,
        None => statement.query_map([], mapper)?,
    };
    let runs = rows.collect::<Result<Vec<_>, _>>()?;
    let reconciled_pairs = load_valid_reconciliation_pairs(connection)?;
    Ok(annotate_run_identities(runs, &reconciled_pairs))
}

fn annotate_run_identities(
    mut runs: Vec<RunSummary>,
    reconciled_pairs: &HashSet<(String, String)>,
) -> Vec<RunSummary> {
    let predecessors = runs
        .iter()
        .map(|run| (run.run_id.clone(), run.predecessor_run_id.clone()))
        .collect::<HashMap<_, _>>();
    let advertised_successors = runs
        .iter()
        .filter_map(|run| {
            run.superseded_by_run_id
                .as_ref()
                .filter(|successor| {
                    !reconciled_pairs.contains(&(run.run_id.clone(), (*successor).clone()))
                })
                .map(|successor| (successor.clone(), run.run_id.clone()))
        })
        .collect::<HashMap<_, _>>();
    let successors = runs
        .iter()
        .filter_map(|run| {
            run.predecessor_run_id
                .as_ref()
                .map(|predecessor| (predecessor.clone(), run.run_id.clone()))
        })
        .collect::<HashMap<_, _>>();
    let mut orphaned = HashSet::new();

    for run in &mut runs {
        let mut current = run.run_id.clone();
        let mut seen = HashSet::new();
        while let Some(Some(predecessor)) = predecessors.get(&current) {
            if !seen.insert(current.clone()) || !predecessors.contains_key(predecessor) {
                orphaned.extend(seen.iter().cloned());
                orphaned.insert(run.run_id.clone());
                break;
            }
            let linked = successors.get(predecessor) == Some(&current)
                && advertised_successors.get(&current) == Some(predecessor);
            if !linked {
                orphaned.insert(predecessor.clone());
                orphaned.insert(current.clone());
            }
            current = predecessor.clone();
        }
        run.lineage_root_run_id = current;
    }

    for run in &runs {
        if let Some(successor) = &run.superseded_by_run_id {
            if !reconciled_pairs.contains(&(run.run_id.clone(), successor.clone()))
                && successors.get(&run.run_id) != Some(successor)
            {
                orphaned.insert(run.run_id.clone());
                orphaned.insert(successor.clone());
            }
        }
        if run.predecessor_run_id.is_none() && advertised_successors.contains_key(&run.run_id) {
            orphaned.insert(run.run_id.clone());
            if let Some(predecessor) = advertised_successors.get(&run.run_id) {
                orphaned.insert(predecessor.clone());
            }
        }
    }

    let mut open_by_root: HashMap<String, usize> = HashMap::new();
    for run in &runs {
        if run.closure_state == "open" && run.state != "archived" && run.archived_at.is_none() {
            *open_by_root
                .entry(run.lineage_root_run_id.clone())
                .or_default() += 1;
        }
    }
    for run in &mut runs {
        run.identity_state = if orphaned.contains(&run.run_id) {
            "ORPHANED_IDENTITY"
        } else if open_by_root
            .get(&run.lineage_root_run_id)
            .copied()
            .unwrap_or(0)
            > 1
        {
            "DUPLICATE_ACTIVE_RUN"
        } else if run.closure_state == "open"
            && run.state != "archived"
            && run.archived_at.is_none()
        {
            "CURRENT"
        } else {
            "HISTORY"
        }
        .into();
    }
    runs
}

fn load_valid_reconciliation_pairs(
    connection: &Connection,
) -> Result<HashSet<(String, String)>, StateError> {
    let mut statement = connection.prepare(
        "SELECT canonical_run_id, canonical_snapshot_json, source_snapshots_json, occurred_at
         FROM run_identity_reconciliation_receipts ORDER BY occurred_at, receipt_id",
    )?;
    let rows = statement.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
        ))
    })?;
    let mut pairs = HashSet::new();
    for row in rows {
        let (canonical, canonical_snapshot_json, snapshots_json, occurred_at) = row?;
        let canonical_snapshot: RunStateSnapshot = serde_json::from_str(&canonical_snapshot_json)?;
        let canonical_exists: Option<i64> = connection
            .query_row(
                "SELECT 1 FROM runs WHERE run_id=?1 AND project_id=?2",
                params![canonical, canonical_snapshot.project_id],
                |row| row.get(0),
            )
            .optional()?;
        if canonical_exists.is_none() {
            continue;
        }
        let snapshots: Vec<RunStateSnapshot> = serde_json::from_str(&snapshots_json)?;
        for snapshot in snapshots {
            let current = run_state_snapshot_from(connection, &snapshot.run_id)?;
            let valid: Option<i64> = connection
                .query_row(
                    "SELECT 1 FROM runs
                     WHERE run_id=?1 AND state='archived' AND closure_state='superseded'
                       AND closed_at=?2
                       AND archive_reason='owner-authorized-identity-reconciliation'
                       AND archived_at=?2 AND superseded_by_run_id=?3",
                    params![snapshot.run_id, occurred_at, canonical],
                    |row| row.get(0),
                )
                .optional()?;
            let immutable_matches = current.project_id == snapshot.project_id
                && current.slk_version == snapshot.slk_version
                && current.predecessor_run_id == snapshot.predecessor_run_id
                && current.event_count == snapshot.event_count
                && current.latest_event_id == snapshot.latest_event_id
                && current.token_sequence == snapshot.token_sequence
                && current.token_holder_role_instance_id == snapshot.token_holder_role_instance_id
                && current.role_count == snapshot.role_count
                && current.evidence_count == snapshot.evidence_count;
            if valid.is_some() && immutable_matches {
                pairs.insert((snapshot.run_id, canonical.clone()));
            }
        }
    }
    Ok(pairs)
}

fn load_reconciliation_receipts(
    connection: &Connection,
    run_id: &str,
) -> Result<Vec<RunIdentityReconciliationReceiptProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT receipt_id, canonical_run_id, source_snapshots_json,
                owner_authorization_json, reason, occurred_at, payload_sha256
         FROM run_identity_reconciliation_receipts ORDER BY occurred_at, receipt_id",
    )?;
    let rows = statement.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, String>(6)?,
        ))
    })?;
    let mut output = Vec::new();
    for row in rows {
        let (receipt_id, canonical, snapshots_json, owner_json, reason, occurred_at, hash) = row?;
        let snapshots: Vec<RunStateSnapshot> = serde_json::from_str(&snapshots_json)?;
        let source_run_ids = snapshots
            .into_iter()
            .map(|snapshot| snapshot.run_id)
            .collect::<Vec<_>>();
        if canonical != run_id && !source_run_ids.iter().any(|source| source == run_id) {
            continue;
        }
        let owner: OwnerAuthorizationEvidence = serde_json::from_str(&owner_json)?;
        output.push(RunIdentityReconciliationReceiptProjection {
            receipt_id,
            canonical_run_id: canonical,
            source_run_ids,
            owner_source_thread_id: owner.source_thread_id,
            owner_message_id: owner.message_id,
            owner_decision: owner.decision.as_str().into(),
            reason,
            occurred_at,
            payload_sha256: hash,
        });
    }
    Ok(output)
}

fn load_method_adoption_receipts(
    connection: &Connection,
    run_id: &str,
) -> Result<Vec<MethodAdoptionReceiptProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT receipt_id, run_id, from_version, to_version,
                reconciliation_receipt_id, owner_authorization_json, reason,
                occurred_at, payload_sha256
         FROM run_method_adoption_receipts WHERE run_id=?1
         ORDER BY occurred_at, receipt_id",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, Option<String>>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, String>(6)?,
            row.get::<_, String>(7)?,
            row.get::<_, String>(8)?,
        ))
    })?;
    let mut output = Vec::new();
    for row in rows {
        let (
            receipt_id,
            run_id,
            from_version,
            to_version,
            reconciliation_receipt_id,
            owner_json,
            reason,
            occurred_at,
            payload_sha256,
        ) = row?;
        let owner: OwnerAuthorizationEvidence = serde_json::from_str(&owner_json)?;
        output.push(MethodAdoptionReceiptProjection {
            receipt_id,
            run_id,
            from_version,
            to_version,
            reconciliation_receipt_id,
            owner_source_thread_id: owner.source_thread_id,
            owner_message_id: owner.message_id,
            owner_decision: owner.decision.as_str().into(),
            reason,
            occurred_at,
            payload_sha256,
        });
    }
    Ok(output)
}

fn load_go_nodes(connection: &Connection, run_id: &str) -> Result<Vec<GoProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT go_id, ordinal, title, objective, state, outcome
         FROM go_nodes WHERE run_id=?1 ORDER BY ordinal",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, u32>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, Option<String>>(5)?,
        ))
    })?;
    let mut output = Vec::new();
    for row in rows {
        let (go_id, ordinal, title, objective, state, outcome) = row?;
        output.push(GoProjection {
            cell_nodes: load_cell_nodes(connection, run_id, &go_id)?,
            go_id,
            ordinal,
            title,
            objective,
            state,
            outcome,
        });
    }
    Ok(output)
}

fn load_cell_nodes(
    connection: &Connection,
    run_id: &str,
    go_id: &str,
) -> Result<Vec<CellProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT cell_id, ordinal, title, objective, state, attempt, outcome
         FROM cell_nodes WHERE run_id=?1 AND go_id=?2 ORDER BY ordinal",
    )?;
    let rows = statement.query_map(params![run_id, go_id], |row| {
        Ok(CellProjection {
            cell_id: row.get(0)?,
            ordinal: row.get(1)?,
            title: row.get(2)?,
            objective: row.get(3)?,
            state: row.get(4)?,
            attempt: row.get(5)?,
            outcome: row.get(6)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn load_roles(connection: &Connection, run_id: &str) -> Result<Vec<RoleProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT role, role_instance_id, agent_runtime, provider, model, reasoning, session_id,
                lifecycle, predecessor_role_instance_id, successor_role_instance_id,
                current_go_id, current_cell_id, created_at, takeover_at, exited_at
         FROM role_instances WHERE run_id=?1
         ORDER BY CASE role WHEN 'supervisor' THEN 1 WHEN 'checker' THEN 3 ELSE 4 END,
                  created_at, role_instance_id",
    )?;
    let rows = statement.query_map([run_id], |row| {
        let role_instance_id: String = row.get(1)?;
        let endpoints = load_endpoints(connection, &role_instance_id)?;
        Ok(RoleProjection {
            role: row.get(0)?,
            display_state: role_display_state(connection, &role_instance_id)?,
            role_instance_id,
            agent_runtime: row.get(2)?,
            provider: row.get(3)?,
            model: row.get(4)?,
            reasoning: row.get(5)?,
            session_id: row.get(6)?,
            lifecycle: row.get(7)?,
            predecessor_role_instance_id: row.get(8)?,
            successor_role_instance_id: row.get(9)?,
            current_go_id: row.get(10)?,
            current_cell_id: row.get(11)?,
            created_at: row.get(12)?,
            takeover_at: row.get(13)?,
            exited_at: row.get(14)?,
            endpoints,
            binding_mode: None,
        })
    })?;
    let mut output = rows.collect::<Result<Vec<_>, _>>()?;
    let overwatcher: Option<OverwatcherBindingRow> = connection
        .query_row(
            "SELECT role_instance_id, agent_runtime, provider, model, reasoning, session_id,
                    endpoint_version, transport_adapter, host_identity, lifecycle_state,
                    bound_at, closed_at
             FROM overwatcher_bindings WHERE run_id=?1",
            [run_id],
            |row| {
                Ok(OverwatcherBindingRow {
                    role_instance_id: row.get(0)?,
                    agent_runtime: row.get(1)?,
                    provider: row.get(2)?,
                    model: row.get(3)?,
                    reasoning: row.get(4)?,
                    session_id: row.get(5)?,
                    endpoint_version: row.get(6)?,
                    transport_adapter: row.get(7)?,
                    host_identity: row.get(8)?,
                    lifecycle_state: row.get(9)?,
                    bound_at: row.get(10)?,
                    closed_at: row.get(11)?,
                })
            },
        )
        .optional()?;
    if let Some(overwatcher) = overwatcher {
        let active = overwatcher.lifecycle_state == "active";
        output.push(RoleProjection {
            role: "overwatcher".into(),
            role_instance_id: overwatcher.role_instance_id,
            agent_runtime: overwatcher.agent_runtime,
            provider: overwatcher.provider,
            model: overwatcher.model,
            reasoning: overwatcher.reasoning,
            session_id: overwatcher.session_id.clone(),
            lifecycle: if active {
                "active".into()
            } else {
                "exited".into()
            },
            predecessor_role_instance_id: None,
            successor_role_instance_id: None,
            current_go_id: None,
            current_cell_id: None,
            created_at: overwatcher.bound_at.clone(),
            takeover_at: None,
            exited_at: overwatcher.closed_at.clone(),
            endpoints: vec![EndpointProjection {
                endpoint_version: overwatcher.endpoint_version,
                transport_adapter: overwatcher.transport_adapter,
                host_identity: overwatcher.host_identity,
                session_id: overwatcher.session_id,
                state: if active {
                    "active".into()
                } else {
                    "retired".into()
                },
                created_at: overwatcher.bound_at,
                retired_at: overwatcher.closed_at,
            }],
            display_state: if active {
                "observing".into()
            } else {
                overwatcher.lifecycle_state
            },
            binding_mode: Some("supervisor_selected".into()),
        });
    }
    output.sort_by_key(|item| match item.role.as_str() {
        "supervisor" => 1,
        "overwatcher" => 2,
        "checker" => 3,
        "worker" => 4,
        _ => 5,
    });
    Ok(output)
}

fn load_endpoints(
    connection: &Connection,
    role_instance_id: &str,
) -> rusqlite::Result<Vec<EndpointProjection>> {
    let mut statement = connection.prepare(
        "SELECT endpoint_version, transport_adapter, host_identity, session_id, state,
                created_at, retired_at
         FROM role_endpoints WHERE role_instance_id=?1 ORDER BY endpoint_version",
    )?;
    let rows = statement.query_map([role_instance_id], |row| {
        Ok(EndpointProjection {
            endpoint_version: row.get(0)?,
            transport_adapter: row.get(1)?,
            host_identity: row.get(2)?,
            session_id: row.get(3)?,
            state: row.get(4)?,
            created_at: row.get(5)?,
            retired_at: row.get(6)?,
        })
    })?;
    rows.collect()
}

fn role_display_state(connection: &Connection, role_instance_id: &str) -> rusqlite::Result<String> {
    let lifecycle: String = connection.query_row(
        "SELECT lifecycle FROM role_instances WHERE role_instance_id=?1",
        [role_instance_id],
        |row| row.get(0),
    )?;
    if lifecycle == "exited" {
        return Ok("archived".into());
    }
    let event: Option<String> = connection
        .query_row(
            "SELECT event_type FROM work_events WHERE author_role_instance_id=?1
             ORDER BY rowid DESC LIMIT 1",
            [role_instance_id],
            |row| row.get(0),
        )
        .optional()?;
    Ok(match event.as_deref() {
        Some(
            "WORK_STARTED" | "WORK_PROGRESS" | "RESOURCE_RECOVERED" | "D1_STARTED" | "D2_STARTED",
        ) => "working",
        Some("RESOURCE_CONTENDED") => "resource_blocked",
        Some("BLOCKER_REPORTED" | "TRANSPORT_FAILED") => "blocked",
        Some(
            "D0_COMPLETED"
            | "CANDIDATE_SUBMITTED"
            | "D1_PASSED"
            | "D1_FAILED"
            | "D2_PASSED"
            | "D2_FAILED"
            | "RUN_SUPERSEDED"
            | "RUN_ABANDONED"
            | "RUN_CLOSED",
        ) => "completed",
        _ => "ready",
    }
    .to_string())
}

fn load_plan_revisions(
    connection: &Connection,
    run_id: &str,
) -> Result<Vec<PlanRevisionProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT revision, author_role_instance_id, reason, previous_revision, created_at
         FROM plan_revisions WHERE run_id=?1 ORDER BY revision",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(PlanRevisionProjection {
            revision: row.get(0)?,
            author_role_instance_id: row.get(1)?,
            reason: row.get(2)?,
            previous_revision: row.get(3)?,
            created_at: row.get(4)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn load_events(connection: &Connection, run_id: &str) -> Result<Vec<EventProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT event_id, event_type, author_role_instance_id, go_id, cell_id, attempt,
                details_json, corrects_event_id, occurred_at
         FROM work_events WHERE run_id=?1 ORDER BY rowid",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(EventProjection {
            event_id: row.get(0)?,
            event_type: row.get(1)?,
            author_role_instance_id: row.get(2)?,
            go_id: row.get(3)?,
            cell_id: row.get(4)?,
            attempt: row.get(5)?,
            details_json: row.get(6)?,
            corrects_event_id: row.get(7)?,
            occurred_at: row.get(8)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn load_tokens(connection: &Connection, run_id: &str) -> Result<Vec<TokenProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT token_sequence, from_role_instance_id, to_role_instance_id, go_id, cell_id,
                message_id, event_type, occurred_at
         FROM token_events WHERE run_id=?1 ORDER BY token_sequence",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(TokenProjection {
            token_sequence: row.get(0)?,
            from_role_instance_id: row.get(1)?,
            to_role_instance_id: row.get(2)?,
            go_id: row.get(3)?,
            cell_id: row.get(4)?,
            message_id: row.get(5)?,
            event_type: row.get(6)?,
            occurred_at: row.get(7)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn load_evidence(
    connection: &Connection,
    run_id: &str,
) -> Result<Vec<EvidenceProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT evidence_id, evidence_type, stored_path, sha256, byte_length,
                producing_role_instance_id, go_id, cell_id, created_at
         FROM evidence WHERE run_id=?1 ORDER BY created_at, evidence_id",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(EvidenceProjection {
            evidence_id: row.get(0)?,
            evidence_type: row.get(1)?,
            stored_path: row.get(2)?,
            sha256: row.get(3)?,
            byte_length: row.get(4)?,
            producing_role_instance_id: row.get(5)?,
            go_id: row.get(6)?,
            cell_id: row.get(7)?,
            created_at: row.get(8)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn load_operational_observations(
    connection: &Connection,
    run_id: &str,
) -> Result<Vec<OperationalObservationProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT observation_id, overwatcher_role_instance_id, go_id, cell_id, attempt,
                plan_revision, kind, related_event_id, message_id, evidence_refs_json,
                details_json, occurred_at
         FROM operational_observations
         WHERE run_id=?1 ORDER BY occurred_at, observation_id",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(OperationalObservationProjection {
            observation_id: row.get(0)?,
            overwatcher_role_instance_id: row.get(1)?,
            go_id: row.get(2)?,
            cell_id: row.get(3)?,
            attempt: row.get(4)?,
            plan_revision: row.get(5)?,
            kind: row.get(6)?,
            related_event_id: row.get(7)?,
            message_id: row.get(8)?,
            evidence_refs_json: row.get(9)?,
            details_json: row.get(10)?,
            occurred_at: row.get(11)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn load_overwatch_cycles(
    connection: &Connection,
    run_id: &str,
) -> Result<Vec<OverwatchCycleProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT cycle_id, overwatcher_role_instance_id, session_id, foreground_turn_id,
                cycle_sequence, cadence_seconds, plan_revision, go_id, cell_id, attempt,
                token_sequence, token_holder_role_instance_id, latest_event_id,
                latest_message_id, checklist_json, anomaly_codes_json, evidence_refs_json,
                native_active_session_evidence_ref, started_at, completed_at, next_cycle_at,
                binding_revision, runtime_revision, native_liveness, cadence_health,
                cost_metrics_json
         FROM overwatch_cycles WHERE run_id=?1 ORDER BY cycle_sequence",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(OverwatchCycleProjection {
            cycle_id: row.get(0)?,
            overwatcher_role_instance_id: row.get(1)?,
            session_id: row.get(2)?,
            foreground_turn_id: row.get(3)?,
            cycle_sequence: row.get(4)?,
            cadence_seconds: row.get(5)?,
            plan_revision: row.get(6)?,
            go_id: row.get(7)?,
            cell_id: row.get(8)?,
            attempt: row.get(9)?,
            token_sequence: row.get(10)?,
            token_holder_role_instance_id: row.get(11)?,
            latest_event_id: row.get(12)?,
            latest_message_id: row.get(13)?,
            checklist_json: row.get(14)?,
            anomaly_codes_json: row.get(15)?,
            evidence_refs_json: row.get(16)?,
            native_active_session_evidence_ref: row.get(17)?,
            started_at: row.get(18)?,
            completed_at: row.get(19)?,
            next_cycle_at: row.get(20)?,
            binding_revision: row.get(21)?,
            runtime_revision: row.get(22)?,
            native_liveness: row.get(23)?,
            cadence_health: row.get(24)?,
            cost_metrics_json: row.get(25)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn load_overwatcher_native_statuses(
    connection: &Connection,
    run_id: &str,
) -> Result<Vec<OverwatcherNativeStatusProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT status_id, binding_revision, role_instance_id, session_id,
                foreground_turn_id, native_liveness, evidence_path, evidence_sha256,
                observed_at
         FROM overwatcher_native_status_receipts
         WHERE run_id=?1 ORDER BY rowid",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(OverwatcherNativeStatusProjection {
            status_id: row.get(0)?,
            binding_revision: row.get(1)?,
            role_instance_id: row.get(2)?,
            session_id: row.get(3)?,
            foreground_turn_id: row.get(4)?,
            native_liveness: row.get(5)?,
            evidence_path: row.get(6)?,
            evidence_sha256: row.get(7)?,
            observed_at: row.get(8)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn load_overwatcher_incident_transitions(
    connection: &Connection,
    run_id: &str,
) -> Result<Vec<OverwatcherIncidentTransitionProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT transition_id, incident_id, binding_revision, incident_code, state,
                evidence_path, evidence_sha256, occurred_at
         FROM overwatcher_incident_transitions
         WHERE run_id=?1 ORDER BY rowid",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(OverwatcherIncidentTransitionProjection {
            transition_id: row.get(0)?,
            incident_id: row.get(1)?,
            binding_revision: row.get(2)?,
            incident_code: row.get(3)?,
            state: row.get(4)?,
            evidence_path: row.get(5)?,
            evidence_sha256: row.get(6)?,
            occurred_at: row.get(7)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn load_overwatcher_binding_transitions(
    connection: &Connection,
    run_id: &str,
) -> Result<Vec<OverwatcherBindingTransitionProjection>, StateError> {
    let mut statement = connection.prepare(
        "SELECT transition_id, binding_revision, transition_type, cycle_id,
                runtime_revision, evidence_ref, occurred_at
         FROM overwatcher_binding_transitions
         WHERE run_id=?1 ORDER BY rowid",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(OverwatcherBindingTransitionProjection {
            transition_id: row.get(0)?,
            binding_revision: row.get(1)?,
            transition_type: row.get(2)?,
            cycle_id: row.get(3)?,
            runtime_revision: row.get(4)?,
            evidence_ref: row.get(5)?,
            occurred_at: row.get(6)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}
