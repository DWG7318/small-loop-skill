//! Deterministic human-readable exports of authoritative SQLite state.

use std::fmt::Write as _;
use std::fs::{self, OpenOptions};
use std::io::Write as _;
use std::path::PathBuf;

use rusqlite::{params, OptionalExtension};

use crate::auth::StateError;
use crate::config::replace_file;
use crate::schema::open_database;
use crate::write::StateStore;

#[derive(Debug)]
struct WorkRow {
    event_id: String,
    event_type: String,
    details: String,
    occurred_at: String,
    role: String,
    role_instance_id: String,
    go_id: Option<String>,
    cell_id: Option<String>,
    corrects_event_id: Option<String>,
}

#[derive(Debug)]
struct RunExportHeader {
    project_id: String,
    goal: String,
    boundaries: String,
    state: String,
    revision: i64,
    closure: String,
    created_at: String,
    closed_at: Option<String>,
}

struct OverwatcherExportRow {
    role_instance_id: String,
    agent_runtime: String,
    provider: String,
    model: String,
    reasoning: String,
    session_id: String,
    lifecycle_state: String,
    binding_reason: String,
    bound_at: String,
}

impl StateStore {
    pub fn export_run(&self, run_id: &str) -> Result<PathBuf, StateError> {
        let connection = open_database(&self.data_root)?;
        let run: Option<RunExportHeader> = connection
            .query_row(
                "SELECT project_id, goal, boundaries_json, state, current_plan_revision,
                            closure_state, created_at, closed_at
                     FROM runs WHERE run_id=?1",
                [run_id],
                |row| {
                    Ok(RunExportHeader {
                        project_id: row.get(0)?,
                        goal: row.get(1)?,
                        boundaries: row.get(2)?,
                        state: row.get(3)?,
                        revision: row.get(4)?,
                        closure: row.get(5)?,
                        created_at: row.get(6)?,
                        closed_at: row.get(7)?,
                    })
                },
            )
            .optional()?;
        let run = run.ok_or_else(|| StateError::RunNotFound(run_id.to_string()))?;

        let mut markdown = String::new();
        writeln!(markdown, "# SLK Run {run_id}").unwrap();
        writeln!(markdown).unwrap();
        writeln!(markdown, "- Project: `{}`", run.project_id).unwrap();
        writeln!(markdown, "- State: `{}`", run.state).unwrap();
        writeln!(markdown, "- Closure: `{}`", run.closure).unwrap();
        writeln!(markdown, "- Current plan revision: `{}`", run.revision).unwrap();
        writeln!(markdown, "- Created: `{}`", run.created_at).unwrap();
        writeln!(
            markdown,
            "- Closed: `{}`",
            run.closed_at.as_deref().unwrap_or("not closed")
        )
        .unwrap();
        writeln!(markdown).unwrap();
        writeln!(markdown, "## Goal and boundaries").unwrap();
        writeln!(markdown).unwrap();
        writeln!(markdown, "{}", single_line(&run.goal)).unwrap();
        writeln!(markdown).unwrap();
        writeln!(markdown, "```json").unwrap();
        writeln!(markdown, "{}", run.boundaries).unwrap();
        writeln!(markdown, "```").unwrap();

        render_plan_revisions(&connection, run_id, &mut markdown)?;
        render_nodes(&connection, run_id, &mut markdown)?;
        render_roles(&connection, run_id, &mut markdown)?;
        let events = load_work_events(&connection, run_id)?;
        render_role_events(&events, "worker", "D0 / Worker", &mut markdown);
        render_role_events(&events, "checker", "D1 / Checker", &mut markdown);
        render_role_events(&events, "supervisor", "D2 / Supervisor", &mut markdown);
        render_corrections(&events, &mut markdown);
        render_tokens(&connection, run_id, &mut markdown)?;
        render_overwatch_cycles(&connection, run_id, &mut markdown)?;
        render_operational_observations(&connection, run_id, &mut markdown)?;
        render_evidence(&connection, run_id, &mut markdown)?;

        let export_directory = self
            .data_root
            .join("exports")
            .join(&run.project_id)
            .join(run_id);
        fs::create_dir_all(&export_directory)?;
        let destination = export_directory.join(format!("SLK-RUN-{run_id}.md"));
        let temporary = export_directory.join(format!(".SLK-RUN-{run_id}.md.tmp"));
        if temporary.exists() {
            fs::remove_file(&temporary)?;
        }
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)?;
        file.write_all(markdown.as_bytes())?;
        file.sync_all()?;
        drop(file);
        replace_file(&temporary, &destination)?;
        Ok(destination)
    }
}

fn render_plan_revisions(
    connection: &rusqlite::Connection,
    run_id: &str,
    output: &mut String,
) -> Result<(), StateError> {
    writeln!(output).unwrap();
    writeln!(output, "## Plan revisions").unwrap();
    writeln!(output).unwrap();
    let mut statement = connection.prepare(
        "SELECT revision, reason, author_role_instance_id, created_at
         FROM plan_revisions WHERE run_id=?1 ORDER BY revision",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok((
            row.get::<_, i64>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
        ))
    })?;
    for row in rows {
        let (revision, reason, author, occurred_at) = row?;
        writeln!(
            output,
            "- v{revision} — {} — `{author}` — `{occurred_at}`",
            single_line(&reason)
        )
        .unwrap();
    }
    Ok(())
}

fn render_nodes(
    connection: &rusqlite::Connection,
    run_id: &str,
    output: &mut String,
) -> Result<(), StateError> {
    writeln!(output).unwrap();
    writeln!(output, "## GO and CELL plan").unwrap();
    let mut go_statement = connection.prepare(
        "SELECT go_id, title, objective, state, outcome
         FROM go_nodes WHERE run_id=?1 ORDER BY ordinal",
    )?;
    let go_rows = go_statement.query_map([run_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, Option<String>>(4)?,
        ))
    })?;
    for go_row in go_rows {
        let (go_id, title, objective, state, outcome) = go_row?;
        writeln!(output).unwrap();
        writeln!(output, "### {go_id} — {}", single_line(&title)).unwrap();
        writeln!(output, "- State: `{state}`").unwrap();
        writeln!(output, "- Objective: {}", single_line(&objective)).unwrap();
        if let Some(outcome) = outcome {
            writeln!(output, "- Outcome: {}", single_line(&outcome)).unwrap();
        }
        let mut cell_statement = connection.prepare(
            "SELECT cell_id, title, objective, state, attempt, outcome
             FROM cell_nodes WHERE run_id=?1 AND go_id=?2 ORDER BY ordinal",
        )?;
        let cell_rows = cell_statement.query_map(params![run_id, go_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, Option<String>>(5)?,
            ))
        })?;
        for cell_row in cell_rows {
            let (cell_id, title, objective, state, attempt, outcome) = cell_row?;
            writeln!(
                output,
                "  - {cell_id} — {} — `{state}` — attempt {attempt}",
                single_line(&title)
            )
            .unwrap();
            writeln!(output, "    - Objective: {}", single_line(&objective)).unwrap();
            if let Some(outcome) = outcome {
                writeln!(output, "    - Outcome: {}", single_line(&outcome)).unwrap();
            }
        }
    }
    Ok(())
}

fn render_roles(
    connection: &rusqlite::Connection,
    run_id: &str,
    output: &mut String,
) -> Result<(), StateError> {
    writeln!(output).unwrap();
    writeln!(output, "## Role roster and replacement history").unwrap();
    writeln!(output).unwrap();
    let mut statement = connection.prepare(
        "SELECT role, role_instance_id, agent_runtime, provider, model, reasoning, session_id,
                lifecycle, predecessor_role_instance_id, successor_role_instance_id
         FROM role_instances WHERE run_id=?1 ORDER BY created_at, role_instance_id",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, String>(6)?,
            row.get::<_, String>(7)?,
            row.get::<_, Option<String>>(8)?,
            row.get::<_, Option<String>>(9)?,
        ))
    })?;
    for row in rows {
        let (
            role,
            id,
            runtime,
            provider,
            model,
            reasoning,
            session,
            lifecycle,
            predecessor,
            successor,
        ) = row?;
        writeln!(output, "- `{role}` `{id}` — `{runtime}` / `{provider}` / `{model}` / `{reasoning}` — session `{session}` — `{lifecycle}` — predecessor `{}` — successor `{}`",
            predecessor.as_deref().unwrap_or("none"), successor.as_deref().unwrap_or("none")).unwrap();
    }
    let overwatcher: Option<OverwatcherExportRow> = connection
        .query_row(
            "SELECT role_instance_id, agent_runtime, provider, model, reasoning, session_id,
                        lifecycle_state, binding_reason, bound_at
                 FROM overwatcher_bindings WHERE run_id=?1",
            [run_id],
            |row| {
                Ok(OverwatcherExportRow {
                    role_instance_id: row.get(0)?,
                    agent_runtime: row.get(1)?,
                    provider: row.get(2)?,
                    model: row.get(3)?,
                    reasoning: row.get(4)?,
                    session_id: row.get(5)?,
                    lifecycle_state: row.get(6)?,
                    binding_reason: row.get(7)?,
                    bound_at: row.get(8)?,
                })
            },
        )
        .optional()?;
    if let Some(overwatcher) = overwatcher {
        writeln!(output, "- Overwatcher binding `{}` — `{}` / `{}` / `{}` / `{}` — session `{}` — `{}` — selected at `{}` — {}",
            overwatcher.role_instance_id, overwatcher.agent_runtime, overwatcher.provider,
            overwatcher.model, overwatcher.reasoning, overwatcher.session_id,
            overwatcher.lifecycle_state, overwatcher.bound_at,
            single_line(&overwatcher.binding_reason)).unwrap();
    }
    Ok(())
}

fn load_work_events(
    connection: &rusqlite::Connection,
    run_id: &str,
) -> Result<Vec<WorkRow>, StateError> {
    let mut statement = connection.prepare(
        "SELECT w.event_id, w.event_type, w.details_json, w.occurred_at, r.role,
                w.author_role_instance_id, w.go_id, w.cell_id, w.corrects_event_id
         FROM work_events w
         JOIN role_instances r ON r.role_instance_id=w.author_role_instance_id
         WHERE w.run_id=?1 ORDER BY w.rowid",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok(WorkRow {
            event_id: row.get(0)?,
            event_type: row.get(1)?,
            details: row.get(2)?,
            occurred_at: row.get(3)?,
            role: row.get(4)?,
            role_instance_id: row.get(5)?,
            go_id: row.get(6)?,
            cell_id: row.get(7)?,
            corrects_event_id: row.get(8)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
}

fn render_role_events(events: &[WorkRow], role: &str, title: &str, output: &mut String) {
    writeln!(output).unwrap();
    writeln!(output, "## {title}").unwrap();
    writeln!(output).unwrap();
    let selected = events.iter().filter(|event| event.role == role);
    let mut count = 0;
    for event in selected {
        count += 1;
        writeln!(
            output,
            "- `{}` `{}` by `{}` at `{}` — GO `{}` / CELL `{}` — {}",
            event.event_type,
            event.event_id,
            event.role_instance_id,
            event.occurred_at,
            event.go_id.as_deref().unwrap_or("none"),
            event.cell_id.as_deref().unwrap_or("none"),
            single_line(&event.details)
        )
        .unwrap();
    }
    if count == 0 {
        writeln!(output, "- None recorded.").unwrap();
    }
}

fn render_corrections(events: &[WorkRow], output: &mut String) {
    writeln!(output).unwrap();
    writeln!(output, "## Corrections and exemptions").unwrap();
    writeln!(output).unwrap();
    let mut count = 0;
    for event in events.iter().filter(|event| {
        event.corrects_event_id.is_some()
            || event.event_type.contains("EXEMPT")
            || event.event_type.contains("REWORK")
            || event.event_type.contains("FAILED")
    }) {
        count += 1;
        writeln!(
            output,
            "- `{}` `{}` corrects `{}` — {}",
            event.event_type,
            event.event_id,
            event.corrects_event_id.as_deref().unwrap_or("none"),
            single_line(&event.details)
        )
        .unwrap();
    }
    if count == 0 {
        writeln!(output, "- None recorded.").unwrap();
    }
}

fn render_tokens(
    connection: &rusqlite::Connection,
    run_id: &str,
    output: &mut String,
) -> Result<(), StateError> {
    writeln!(output).unwrap();
    writeln!(output, "## SLK TOKEN history").unwrap();
    writeln!(output).unwrap();
    let mut statement = connection.prepare(
        "SELECT token_sequence, event_type, from_role_instance_id, to_role_instance_id,
                go_id, cell_id, message_id, occurred_at
         FROM token_events WHERE run_id=?1 ORDER BY token_sequence",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok((
            row.get::<_, i64>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, Option<String>>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, Option<String>>(4)?,
            row.get::<_, Option<String>>(5)?,
            row.get::<_, Option<String>>(6)?,
            row.get::<_, String>(7)?,
        ))
    })?;
    for row in rows {
        let (sequence, event_type, from, to, go, cell, message, occurred_at) = row?;
        writeln!(output, "- #{sequence} `{event_type}`: `{}` -> `{to}` — GO `{}` / CELL `{}` — message `{}` — `{occurred_at}`",
            from.as_deref().unwrap_or("created"), go.as_deref().unwrap_or("none"),
            cell.as_deref().unwrap_or("none"), message.as_deref().unwrap_or("none")).unwrap();
    }
    Ok(())
}

fn render_evidence(
    connection: &rusqlite::Connection,
    run_id: &str,
    output: &mut String,
) -> Result<(), StateError> {
    writeln!(output).unwrap();
    writeln!(output, "## Evidence").unwrap();
    writeln!(output).unwrap();
    let mut statement = connection.prepare(
        "SELECT evidence_id, evidence_type, stored_path, sha256, byte_length,
                producing_role_instance_id, go_id, cell_id, created_at
         FROM evidence WHERE run_id=?1 ORDER BY created_at, evidence_id",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, i64>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, Option<String>>(6)?,
            row.get::<_, Option<String>>(7)?,
            row.get::<_, String>(8)?,
        ))
    })?;
    let mut count = 0;
    for row in rows {
        count += 1;
        let (id, kind, path, hash, bytes, role, go, cell, occurred_at) = row?;
        writeln!(output, "- `{id}` `{kind}` — `{path}` — SHA-256 `{hash}` — {bytes} bytes — by `{role}` — GO `{}` / CELL `{}` — `{occurred_at}`",
            go.as_deref().unwrap_or("none"), cell.as_deref().unwrap_or("none")).unwrap();
    }
    if count == 0 {
        writeln!(output, "- None recorded.").unwrap();
    }
    Ok(())
}

fn render_operational_observations(
    connection: &rusqlite::Connection,
    run_id: &str,
    output: &mut String,
) -> Result<(), StateError> {
    writeln!(output).unwrap();
    writeln!(output, "## Operational observations / Overwatcher").unwrap();
    writeln!(output).unwrap();
    let mut statement = connection.prepare(
        "SELECT observation_id, overwatcher_role_instance_id, kind, go_id, cell_id,
                attempt, plan_revision, message_id, evidence_refs_json, details_json, occurred_at
         FROM operational_observations
         WHERE run_id=?1 ORDER BY occurred_at, observation_id",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, Option<String>>(3)?,
            row.get::<_, Option<String>>(4)?,
            row.get::<_, Option<i64>>(5)?,
            row.get::<_, i64>(6)?,
            row.get::<_, Option<String>>(7)?,
            row.get::<_, String>(8)?,
            row.get::<_, String>(9)?,
            row.get::<_, String>(10)?,
        ))
    })?;
    let mut count = 0;
    for row in rows {
        count += 1;
        let (id, role, kind, go, cell, attempt, revision, message, evidence, details, at) = row?;
        writeln!(output, "- `{kind}` `{id}` by `{role}` at `{at}` — plan v{revision} / GO `{}` / CELL `{}` / attempt `{}` / message `{}` — evidence {} — {}",
            go.as_deref().unwrap_or("none"), cell.as_deref().unwrap_or("none"),
            attempt.map(|value| value.to_string()).as_deref().unwrap_or("none"),
            message.as_deref().unwrap_or("none"), single_line(&evidence), single_line(&details)).unwrap();
    }
    if count == 0 {
        writeln!(output, "- None recorded.").unwrap();
    }
    Ok(())
}

fn render_overwatch_cycles(
    connection: &rusqlite::Connection,
    run_id: &str,
    output: &mut String,
) -> Result<(), StateError> {
    writeln!(output).unwrap();
    writeln!(output, "## Overwatch cycles").unwrap();
    writeln!(output).unwrap();
    let mut statement = connection.prepare(
        "SELECT cycle_sequence, cycle_id, overwatcher_role_instance_id, foreground_turn_id,
                cadence_seconds, plan_revision, go_id, cell_id, attempt, token_sequence,
                token_holder_role_instance_id, latest_event_id, checklist_json,
                anomaly_codes_json, evidence_refs_json, completed_at, next_cycle_at
         FROM overwatch_cycles WHERE run_id=?1 ORDER BY cycle_sequence",
    )?;
    let rows = statement.query_map([run_id], |row| {
        Ok((
            row.get::<_, i64>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, i64>(4)?,
            row.get::<_, i64>(5)?,
            row.get::<_, Option<String>>(6)?,
            row.get::<_, Option<String>>(7)?,
            row.get::<_, Option<i64>>(8)?,
            row.get::<_, i64>(9)?,
            row.get::<_, String>(10)?,
            row.get::<_, String>(11)?,
            row.get::<_, String>(12)?,
            row.get::<_, String>(13)?,
            row.get::<_, String>(14)?,
            row.get::<_, String>(15)?,
            row.get::<_, String>(16)?,
        ))
    })?;
    let mut count = 0;
    for row in rows {
        count += 1;
        let (
            sequence,
            id,
            role,
            turn,
            cadence,
            revision,
            go,
            cell,
            attempt,
            token,
            holder,
            event,
            checklist,
            anomalies,
            evidence,
            completed,
            next,
        ) = row?;
        writeln!(output, "- cycle `{sequence}` / `{id}` by `{role}` foreground `{turn}` — cadence {cadence}s — plan v{revision} / GO `{}` / CELL `{}` / attempt `{}` / TOKEN T{token} `{holder}` / event `{event}` — completed `{completed}` / next `{next}` — checklist {} — anomalies {} — evidence {}",
            go.as_deref().unwrap_or("none"), cell.as_deref().unwrap_or("none"),
            attempt.map(|value| value.to_string()).as_deref().unwrap_or("none"),
            single_line(&checklist), single_line(&anomalies), single_line(&evidence)).unwrap();
    }
    if count == 0 {
        writeln!(output, "- None recorded.").unwrap();
    }
    Ok(())
}

fn single_line(value: &str) -> String {
    value.replace(['\r', '\n'], " ")
}
