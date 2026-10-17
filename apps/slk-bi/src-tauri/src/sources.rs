//! BI-owned, read-only source adapters. No method-version admission list.
//! Registration/archival receipts are BI metadata, never engineering completion.
use regex::Regex;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{fs, io::Write, path::Path};

fn text<'a>(value: &'a Value, key: &str) -> &'a str {
    value[key].as_str().unwrap_or("")
}
fn digest(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}
fn now() -> String {
    time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .unwrap()
}
fn read_json(path: &Path) -> Result<Value, String> {
    serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?).map_err(|e| e.to_string())
}
fn write_new(path: &Path, value: &Value) -> Result<(), String> {
    // Publish a complete receipt atomically; never replace another creator's record.
    let parent = path.parent().ok_or("SLK_BI_METADATA_PARENT_MISSING")?;
    let mut file = tempfile::NamedTempFile::new_in(parent).map_err(|e| e.to_string())?;
    let bytes = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
    file.write_all(&bytes).map_err(|e| e.to_string())?;
    file.as_file().sync_all().map_err(|e| e.to_string())?;
    file.persist_noclobber(path).map_err(|e| e.to_string())?;
    Ok(())
}
fn section<'a>(input: &'a str, name: &str) -> Result<&'a str, String> {
    let starts: Vec<_> = input
        .match_indices("## ")
        .filter(|(i, _)| {
            (*i == 0 || input.as_bytes()[i - 1] == b'\n') && input[*i + 3..].starts_with(name)
        })
        .collect();
    if starts.len() > 1 {
        return Err(format!("SLK_BI_AMBIGUOUS_SECTION:{name}"));
    }
    let Some((start, _)) = starts.first() else {
        return Ok("");
    };
    let body = &input[*start..];
    let body = body.split_once('\n').map(|(_, s)| s).unwrap_or("");
    Ok(body.split("\n## ").next().unwrap_or(body))
}
fn field<'a>(section: &'a str, keys: &[&str]) -> &'a str {
    for line in section.lines() {
        let line = line.trim().trim_start_matches("- ");
        for key in keys {
            if let Some(tail) = line.strip_prefix(key) {
                if let Some(value) = tail.strip_prefix('：').or_else(|| tail.strip_prefix(':')) {
                    return value.trim();
                }
            }
        }
    }
    ""
}

pub fn project_markdown(input: &str, project: &str, project_name: &str) -> Result<Value, String> {
    let input = input.trim_start_matches('\u{feff}').replace("\r\n", "\n");
    let id = input
        .lines()
        .next()
        .and_then(|s| s.strip_prefix("# SLK Run — "))
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or("SLK_BI_MARKDOWN_FORMAT_UNKNOWN")?;
    let definition = section(&input, "Run 定义")?;
    let summary = section(&input, "当前摘要")?;
    if summary.is_empty() {
        return Err("SLK_BI_CURRENT_SUMMARY_MISSING".into());
    }
    let version_re = Regex::new(r"\b\d+\.\d+\.\d+\b").unwrap();
    let version = version_re
        .find(field(definition, &["SLK版本"]))
        .map(|m| m.as_str())
        .unwrap_or("未提供");
    let status = field(summary, &["当前状态"]);
    let terminal = status
        .split(|c: char| c.is_whitespace() || matches!(c, '/' | '（' | '(' | '；' | ';'))
        .next()
        .unwrap_or("");
    let closure = if terminal == "CLOSED" {
        "closed"
    } else if terminal == "ABANDONED" {
        "abandoned"
    } else {
        "open"
    };
    let goal = field(definition, &["目标"]);
    let created_at = field(definition, &["开始时间", "开始"]);
    let members = section(&input, "成员")?;
    let mut roles = vec![];
    let mut member_columns = Vec::new();
    for line in members.lines().filter(|s| s.trim().starts_with('|')) {
        let cols: Vec<_> = line.split('|').map(str::trim).collect();
        if cols.len() < 4 {
            continue;
        }
        if cols[1] == "角色" {
            member_columns = cols;
            continue;
        }
        let role = cols[1].to_ascii_lowercase();
        if !["supervisor", "checker", "worker", "overwatcher"].contains(&role.as_str()) {
            continue;
        }
        let session = cols[2].trim_matches('`');
        if session.is_empty() || session.starts_with('<') {
            continue;
        }
        if roles.iter().any(|r: &Value| r["role"] == role) {
            return Err("SLK_BI_AMBIGUOUS_MEMBER".into());
        }
        let value_at = |name: &str| {
            member_columns
                .iter()
                .position(|c| *c == name)
                .and_then(|i| cols.get(i))
                .filter(|s| !s.is_empty())
                .copied()
                .unwrap_or("未提供")
        };
        roles.push(json!({"role":role, "role_instance_id":session,"session_id":session,
            "agent_runtime":value_at("Agent"),"provider":value_at("平台"),"model":value_at("模型"),"reasoning":value_at("推理"),
            "lifecycle":if cols[3].starts_with("ARCHIVED") {"archived"} else {"active"},
            "predecessor_role_instance_id":null,"successor_role_instance_id":null,
            "current_go_id":null,"current_cell_id":null,"created_at":created_at,
            "takeover_at":null,"exited_at":null,"endpoints":[],"display_state":"unknown","binding_mode":null}));
    }
    let explicit_creator =
        field(definition, &["创建Supervisor", "创建 Supervisor"]).trim_matches('`');
    let creator = if explicit_creator.is_empty() {
        roles
            .iter()
            .find(|r| r["role"] == "supervisor")
            .map(|r| text(r, "session_id"))
            .unwrap_or("")
    } else {
        explicit_creator
    };
    if creator.is_empty() {
        return Err("SLK_BI_CREATOR_ID_MISSING".into());
    }
    let progress = field(summary, &["最终CELL与进度", "当前CELL与进度", "当前CELL"]);
    let count_re = Regex::new(r"(?:^|\s|/)(\d+)\s*/\s*(\d+)(?:\D|$)").unwrap();
    let counts = count_re
        .captures(progress)
        .and_then(|c| Some((c[1].parse::<u64>().ok()?, c[2].parse::<u64>().ok()?)));
    let mut cells = vec![];
    let plan = section(&input, "GO 与 CELL 计划")?;
    let cell_re =
        Regex::new(r"^-\s*(?:CELL\s*)?([0-9][A-Za-z0-9.\-]*)(?:（[^）]*）)?[：:]\s*(.+)$").unwrap();
    let mut cell_columns = Vec::new();
    for line in plan.lines() {
        let cols: Vec<_> = line.split('|').map(str::trim).collect();
        if cols.len() > 3 && cols[1] == "CELL" {
            cell_columns = cols;
            continue;
        }
        if !cell_columns.is_empty()
            && cols.len() > 3
            && !cols[1].is_empty()
            && !cols[1].starts_with('-')
        {
            let at = |name: &str| {
                cell_columns
                    .iter()
                    .position(|c| *c == name)
                    .and_then(|i| cols.get(i))
                    .copied()
                    .unwrap_or("")
            };
            let state = at("状态");
            let state = if [
                "planned",
                "working",
                "d1_passed",
                "d1_failed",
                "split",
                "exempt",
            ]
            .contains(&state)
            {
                state
            } else {
                "unknown"
            };
            cells.push(json!({"cell_id":cols[1],"ordinal":cells.len()+1,"title":at("目标"),"objective":at("目标"),
                "state":state,"attempt":at("次数").parse::<u64>().unwrap_or(0),"outcome":null}));
            continue;
        }
        if let Some(c) = cell_re.captures(line) {
            cells.push(json!({"cell_id":&c[1],"ordinal":cells.len()+1,"title":&c[2],"objective":&c[2],"state":"unknown","attempt":0,"outcome":null}));
        }
    }
    // Only the current summary's explicit per-CELL PASS list is authoritative.
    // Historical FAILs and a total count alone never manufacture CELL outcomes.
    if let Some((ids, _)) = progress.split_once(" D1 PASS") {
        let ids: Vec<_> = ids
            .split('、')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .collect();
        if cell_columns.is_empty()
            && counts.is_some_and(|(passed, total)| passed == total && passed == ids.len() as u64)
        {
            cells = ids.iter().enumerate().map(|(index, id)| {
                let title = cells.iter().find(|c| c["cell_id"] == *id).map(|c| text(c,"title")).unwrap_or(id);
                json!({"cell_id":id,"ordinal":index+1,"title":title,"objective":title,"state":"d1_passed","attempt":0,"outcome":null})
            }).collect();
        }
    }
    let split_re = Regex::new(r"^(\d+)\s*\+\s*(\d+)$").unwrap();
    let count_origin = split_re
        .captures(field(summary, &["CELL数量来源"]))
        .and_then(|c| {
            let initial = c[1].parse::<u64>().ok()?;
            let added = c[2].parse::<u64>().ok()?;
            let total = counts
                .map(|(_, total)| total)
                .unwrap_or(cells.iter().filter(|c| c["state"] != "split").count() as u64);
            (initial.checked_add(added) == Some(total))
                .then(|| json!({"initial":initial,"split_added":added}))
        });
    Ok(json!({"schema_version":"slk.bi.run/v1","run_id":id,
        "summary":{"archive_control":"creator","run_id":id,"project_id":project,"run_name":id,"run_description":goal,"goal":goal,
            "slk_version":version,"origin_slk_version":version,"source_kind":"solo","source_project_name":project_name,
            "state":if closure == "open" {"unknown"} else {"closed"},"closure_state":closure,"current_plan_revision":0,
            "created_at":created_at,"closed_at":null,"archived_at":null,"archive_reason":null,
            "superseded_by_run_id":null,"predecessor_run_id":null,"lineage_root_run_id":id,"identity_state":"CURRENT"},
        "administrative_snapshot":{"run_id":id,"project_id":project,"slk_version":version,"state":"unknown",
            "closure_state":closure,"archived_at":null,"superseded_by_run_id":null,"predecessor_run_id":null,
            "event_count":0,"latest_event_id":"","token_sequence":0,"token_holder_role_instance_id":"","role_count":roles.len(),"evidence_count":0},
        "source_record":{"kind":"markdown","creator_supervisor_id":creator,"revision":digest(input.as_bytes()),
            "creator_basis":if explicit_creator.is_empty() {"member_record"} else {"creation_record"},
            "status_text":status,"progress":counts.map(|(passed,total)| json!({"passed":passed,"total":total})),"timing_available":false},
        "boundaries_json":"{}","go_nodes":[{"go_id":"record","ordinal":1,"title":"CELL","objective":"","state":"unknown","outcome":null,"cell_nodes":cells}],
        "roles":roles,"plan_revisions":[],"events":[],"token_history":[],"evidence":[],"cell_count_origin":count_origin,
        "overwatch_cycles":[],"overwatcher_native_status_receipts":[],"overwatcher_incident_transitions":[],
        "overwatcher_binding_transitions":[],"operational_observations":[],"reconciliation_receipts":[],"method_adoption_receipts":[]}))
}

fn entry_path(root: &Path, run_id: &str) -> std::path::PathBuf {
    root.join(format!("{}.json", digest(run_id.as_bytes())))
}
fn project_entry(entry: &Value) -> Result<Value, String> {
    let input = fs::read_to_string(text(entry, "path")).map_err(|e| e.to_string())?;
    let run = project_markdown(
        &input,
        text(entry, "project_id"),
        text(entry, "project_name"),
    )?;
    if run["run_id"] != entry["run_id"]
        || run["source_record"]["creator_supervisor_id"] != entry["creator_supervisor_id"]
    {
        return Err("SLK_BI_SOURCE_IDENTITY_CHANGED".into());
    }
    Ok(run)
}
pub fn register(
    root: &Path,
    path: &Path,
    project: &str,
    project_name: &str,
    caller: &str,
) -> Result<Value, String> {
    if project.trim().is_empty() || project_name.trim().is_empty() {
        return Err("SLK_BI_PROJECT_REQUIRED".into());
    }
    let path = fs::canonicalize(path).map_err(|e| e.to_string())?;
    let input = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let run = project_markdown(&input, project, project_name)?;
    if run["source_record"]["creator_basis"] != "creation_record" {
        return Err("SLK_BI_CREATION_FACT_REQUIRED: add the original creator identity to Run 定义/创建Supervisor from the actual creation record".into());
    }
    if caller.is_empty() || run["source_record"]["creator_supervisor_id"] != caller {
        return Err("SLK_BI_CREATOR_REQUIRED".into());
    }
    let entry = json!({"run_id":run["run_id"],"path":path,"project_id":project,"project_name":project_name,
        "creator_supervisor_id":caller,"registered_at":now()});
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let target = entry_path(root, text(&run, "run_id"));
    if target.exists() {
        let previous = read_json(&target)?;
        for key in ["run_id", "path", "project_id", "creator_supervisor_id"] {
            if previous[key] != entry[key] {
                return Err("SLK_BI_REGISTRATION_CONFLICT".into());
            }
        }
        return Ok(previous);
    }
    write_new(&target, &entry)?;
    Ok(entry)
}
pub fn archive(root: &Path, run_id: &str, caller: &str) -> Result<Value, String> {
    let target = entry_path(root, run_id);
    let entry = read_json(&target)?;
    if caller.is_empty() || entry["creator_supervisor_id"] != caller {
        return Err("SLK_BI_CREATOR_REQUIRED".into());
    }
    let receipt = target.with_extension("archive");
    if receipt.exists() {
        return read_json(&receipt);
    }
    let mut run = project_entry(&entry)?;
    if run["summary"]["closure_state"] == "open" {
        return Err("SLK_BI_SOURCE_NOT_CLOSED".into());
    }
    let at = now();
    run["summary"]["archived_at"] = json!(at);
    run["summary"]["archive_reason"] = json!("Creator Supervisor archived closed Run information");
    run["administrative_snapshot"]["archived_at"] = json!(at);
    run["source_record"]["archived_by"] = json!(caller);
    write_new(&receipt, &run)?;
    Ok(run)
}
#[derive(Default)]
pub struct Collection {
    pub runs: Vec<Value>,
    pub projects: Vec<Value>,
    pub warnings: Vec<String>,
}

pub fn load_run(root: &Path, run_id: &str) -> Result<Option<Value>, String> {
    let path = entry_path(root, run_id);
    if !path.exists() {
        return Ok(None);
    }
    let entry = read_json(&path)?;
    let receipt = path.with_extension("archive");
    let run = if receipt.exists() {
        read_json(&receipt)?
    } else {
        project_entry(&entry)?
    };
    if run["run_id"] != run_id
        || run["source_record"]["creator_supervisor_id"] != entry["creator_supervisor_id"]
    {
        return Err("SLK_BI_SOURCE_IDENTITY_CHANGED".into());
    }
    Ok(Some(run))
}
pub fn collect(root: &Path) -> Collection {
    let mut result = Collection::default();
    if !root.exists() {
        return result;
    }
    let entries = match fs::read_dir(root) {
        Ok(v) => v,
        Err(e) => {
            result.warnings.push(e.to_string());
            return result;
        }
    };
    for path in entries {
        let path = match path {
            Ok(p) => p.path(),
            Err(e) => {
                result.warnings.push(e.to_string());
                continue;
            }
        };
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let loaded = (|| {
            let entry = read_json(&path)?;
            let archive = path.with_extension("archive");
            let run = if archive.exists() {
                read_json(&archive)?
            } else {
                project_entry(&entry)?
            };
            Ok::<_, String>((entry, run))
        })();
        match loaded {
            Ok((entry, run)) => {
                let id = text(&entry, "project_id");
                if let Some(project) = result.projects.iter_mut().find(|p| p["project_id"] == id) {
                    project["run_count"] = json!(project["run_count"].as_u64().unwrap_or(0) + 1);
                } else {
                    result.projects.push(json!({"project_id":id,"name":entry["project_name"],"repository_url":null,"last_known_path":"","run_count":1}));
                }
                result.runs.push(run);
            }
            Err(e) => result.warnings.push(format!(
                "{}: {e}",
                path.file_name().unwrap_or_default().to_string_lossy()
            )),
        }
    }
    result.runs.sort_by_key(|r| text(r, "run_id").to_owned());
    result
}

pub fn native_caller() -> Result<String, String> {
    let thread = std::env::var("CODEX_THREAD_ID")
        .ok()
        .filter(|s| !s.trim().is_empty());
    let session = std::env::var("CODEX_SESSION_ID")
        .ok()
        .filter(|s| !s.trim().is_empty());
    if thread.is_some() && session.is_some() && thread != session {
        return Err("SLK_BI_CALLER_ID_CONFLICT".into());
    }
    thread
        .or(session)
        .ok_or("SLK_BI_NATIVE_CALLER_MISSING".into())
}
