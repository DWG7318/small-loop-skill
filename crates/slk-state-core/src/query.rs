//! Stable read-only projections for Agents, the query CLI, and future BI.

use rusqlite::{params, Connection, OptionalExtension};
use serde::Serialize;
use serde_json::{json, Value};

use crate::auth::StateError;
use crate::schema::{open_database_read_only, SCHEMA_VERSION};
use crate::write::StateStore;

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
    pub goal: String,
    pub state: String,
    pub current_plan_revision: u32,
    pub closure_state: String,
    pub created_at: String,
    pub closed_at: Option<String>,
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
pub struct RunProjection {
    pub schema_version: u32,
    pub summary: RunSummary,
    pub boundaries_json: String,
    pub go_nodes: Vec<GoProjection>,
    pub roles: Vec<RoleProjection>,
    pub plan_revisions: Vec<PlanRevisionProjection>,
    pub events: Vec<EventProjection>,
    pub token_history: Vec<TokenProjection>,
    pub evidence: Vec<EvidenceProjection>,
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
        let (sql, value) = if let Some(project_id) = project_id {
            (
                "SELECT run_id, project_id, goal, state, current_plan_revision, closure_state,
                        created_at, closed_at FROM runs WHERE project_id=?1
                 ORDER BY created_at DESC, run_id",
                Some(project_id),
            )
        } else {
            (
                "SELECT run_id, project_id, goal, state, current_plan_revision, closure_state,
                        created_at, closed_at FROM runs
                 ORDER BY created_at DESC, run_id",
                None,
            )
        };
        let mut statement = connection.prepare(sql)?;
        let mapper = |row: &rusqlite::Row<'_>| {
            Ok(RunSummary {
                run_id: row.get(0)?,
                project_id: row.get(1)?,
                goal: row.get(2)?,
                state: row.get(3)?,
                current_plan_revision: row.get(4)?,
                closure_state: row.get(5)?,
                created_at: row.get(6)?,
                closed_at: row.get(7)?,
            })
        };
        let rows = match value {
            Some(project_id) => statement.query_map([project_id], mapper)?,
            None => statement.query_map([], mapper)?,
        };
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn query_run(&self, run_id: &str) -> Result<RunProjection, StateError> {
        if run_id.is_empty() {
            return Err(StateError::RunIdRequired);
        }
        let connection = open_database_read_only(&self.data_root)?;
        let row: Option<(RunSummary, String)> = connection
            .query_row(
                "SELECT run_id, project_id, goal, state, current_plan_revision, closure_state,
                        created_at, closed_at, boundaries_json FROM runs WHERE run_id=?1",
                [run_id],
                |row| {
                    Ok((
                        RunSummary {
                            run_id: row.get(0)?,
                            project_id: row.get(1)?,
                            goal: row.get(2)?,
                            state: row.get(3)?,
                            current_plan_revision: row.get(4)?,
                            closure_state: row.get(5)?,
                            created_at: row.get(6)?,
                            closed_at: row.get(7)?,
                        },
                        row.get(8)?,
                    ))
                },
            )
            .optional()?;
        let (summary, boundaries_json) =
            row.ok_or_else(|| StateError::RunNotFound(run_id.to_string()))?;
        Ok(RunProjection {
            schema_version: SCHEMA_VERSION as u32,
            summary,
            boundaries_json,
            go_nodes: load_go_nodes(&connection, run_id)?,
            roles: load_roles(&connection, run_id)?,
            plan_revisions: load_plan_revisions(&connection, run_id)?,
            events: load_events(&connection, run_id)?,
            token_history: load_tokens(&connection, run_id)?,
            evidence: load_evidence(&connection, run_id)?,
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
         ORDER BY CASE role WHEN 'supervisor' THEN 1 WHEN 'checker' THEN 2 ELSE 3 END,
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
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
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
