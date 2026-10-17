//! Creator-authored closeout notes, stored as immutable evidence, not engineering events.
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Component, Path},
};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

use crate::{
    auth::{authorize_role, Credential, StateError},
    model::Role,
    write::{valid_identifier, StateStore},
};

pub const CLOSEOUT_EVIDENCE_TYPE: &str = "run_closeout_summary";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeviceSignature {
    pub computer_name: Option<String>,
    pub ip_address: Option<String>,
    pub os_version: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordCloseoutSummaryRequest {
    pub run_id: String,
    /// A stable caller idempotency key; never a caller-selected source revision.
    pub original_id: String,
    pub body: String,
    pub recorded_at: String,
    #[serde(default)]
    pub device_signature: Option<DeviceSignature>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CloseoutSummary {
    pub body: String,
    pub authored_by: String,
    pub recorded_at: String,
    pub source_id: String,
    pub source_revision: u64,
    pub content_sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CloseoutSummaryResult {
    pub status: String,
    pub run_id: String,
    pub original_id: String,
    pub closeout_summary: CloseoutSummary,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub device_signature: Option<DeviceSignature>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CloseoutOriginal {
    run_id: String,
    original_id: String,
    pub(crate) closeout_summary: CloseoutSummary,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub(crate) device_signature: Option<DeviceSignature>,
}

impl CloseoutSummary {
    fn computed_hash(&self) -> Result<String, StateError> {
        // Struct order is the cross-language wire contract. Do not use a map:
        // body, authored_by, recorded_at, source_id, source_revision, compact UTF-8.
        #[derive(Serialize)]
        struct Canonical<'a> {
            body: &'a str,
            authored_by: &'a str,
            recorded_at: &'a str,
            source_id: &'a str,
            source_revision: u64,
        }
        Ok(hash(&serde_json::to_vec(&Canonical {
            body: &self.body,
            authored_by: &self.authored_by,
            recorded_at: &self.recorded_at,
            source_id: &self.source_id,
            source_revision: self.source_revision,
        })?))
    }
}

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn source_id(run_id: &str, original_id: &str) -> Result<String, StateError> {
    Ok(format!(
        "closeout-{}",
        hash(&serde_json::to_vec(&(run_id, original_id))?)
    ))
}
fn invalid(message: &str) -> StateError {
    StateError::EvidenceInvalid(message.into())
}

impl StateStore {
    pub fn record_closeout_summary(
        &self,
        credential: &Credential,
        request: RecordCloseoutSummaryRequest,
    ) -> Result<CloseoutSummaryResult, StateError> {
        if !valid_identifier(&request.original_id)
            || request.body.trim().is_empty()
            || OffsetDateTime::parse(&request.recorded_at, &Rfc3339).is_err()
        {
            return Err(invalid(
                "summary requires original_id, nonempty body and RFC3339 recorded_at",
            ));
        }
        self.with_immediate_transaction(|transaction| {
            let actor = authorize_role(transaction, &request.run_id, credential)?;
            let creator: String = transaction.query_row(
                "SELECT author_role_instance_id FROM work_events WHERE run_id=?1 AND event_type='RUN_INITIALIZED' ORDER BY rowid LIMIT 1",
                [&request.run_id], |row| row.get(0))?;
            let current_endpoint: bool = transaction.query_row(
                "SELECT EXISTS(SELECT 1 FROM role_instances r JOIN role_endpoints e
                 ON e.run_id=r.run_id AND e.role_instance_id=r.role_instance_id
                 WHERE r.run_id=?1 AND r.role_instance_id=?2 AND r.lifecycle='active'
                 AND e.state='active' AND r.session_id=e.session_id)",
                params![request.run_id, actor.role_instance_id], |row| row.get(0))?;
            if actor.role != Role::Supervisor || actor.role_instance_id != creator || !current_endpoint {
                return Err(invalid("only the authenticated current creator Supervisor may record a closeout summary"));
            }
            let id = source_id(&request.run_id, &request.original_id)?;
            let existing: bool = transaction.query_row("SELECT EXISTS(SELECT 1 FROM evidence WHERE evidence_id=?1)", [&id], |r| r.get(0))?;
            if existing {
                let original = read_original(transaction, &self.data_root, &request.run_id, &id)?;
                if original.original_id != request.original_id || original.closeout_summary.body != request.body
                    || original.closeout_summary.authored_by != actor.role_instance_id
                    || original.closeout_summary.recorded_at != request.recorded_at
                    || original.device_signature != request.device_signature {
                    return Err(invalid("closeout original_id conflicts with immutable content"));
                }
                return Ok(CloseoutSummaryResult { status:"summary_replayed".into(), run_id:request.run_id.clone(),
                    original_id:request.original_id.clone(), closeout_summary:original.closeout_summary,
                    device_signature:original.device_signature });
            }
            // A different request key alone is not a correction. Return the existing
            // canonical original (including its id) without reserving an unused key.
            // Compare only the latest source: reverting a later correction is a change.
            if let Some(original) = load_closeout(transaction, &self.data_root, &request.run_id)? {
                if original.closeout_summary.body == request.body
                    && original.closeout_summary.authored_by == actor.role_instance_id
                    && original.closeout_summary.recorded_at == request.recorded_at
                    && original.device_signature == request.device_signature {
                    return Ok(CloseoutSummaryResult { status:"summary_replayed".into(), run_id:request.run_id.clone(),
                        original_id:original.original_id, closeout_summary:original.closeout_summary,
                        device_signature:original.device_signature });
                }
            }
            let revision: u64 = transaction.query_row(
                "SELECT COUNT(*)+1 FROM evidence WHERE run_id=?1 AND evidence_type=?2",
                params![request.run_id, CLOSEOUT_EVIDENCE_TYPE], |r| r.get(0))?;
            let mut summary = CloseoutSummary { body:request.body.clone(), authored_by:actor.role_instance_id.clone(),
                recorded_at:request.recorded_at.clone(), source_id:id.clone(), source_revision:revision, content_sha256:String::new() };
            summary.content_sha256 = summary.computed_hash()?;
            let original = CloseoutOriginal { run_id:request.run_id.clone(), original_id:request.original_id.clone(),
                closeout_summary:summary.clone(), device_signature:request.device_signature.clone() };
            let bytes = serde_json::to_vec(&original)?;
            let original_hash = hash(&bytes);
            let project_id: String = transaction.query_row("SELECT project_id FROM runs WHERE run_id=?1",[&request.run_id],|r|r.get(0))?;
            let relative = format!("evidence/{project_id}/{}/{id}-{original_hash}.json",request.run_id);
            let path = self.data_root.join(&relative);
            let parent = path.parent().ok_or_else(||invalid("summary evidence directory unavailable"))?;
            fs::create_dir_all(parent)?;
            // Durable original first. Content-addressed files preserve crash remnants
            // even if another committed summary consumes the tentative revision before
            // this request retries. Only the committed evidence row binds original_id.
            if path.exists() {
                if fs::read(&path)? != bytes { return Err(invalid("summary evidence identity already has different content")); }
            } else {
                let temporary = parent.join(format!(".{id}.{}.tmp",uuid::Uuid::new_v4().simple()));
                let result = (|| -> Result<(), StateError> {
                    let mut file = OpenOptions::new().create_new(true).write(true).open(&temporary)?;
                    file.write_all(&bytes)?; file.sync_all()?; drop(file);
                    fs::rename(&temporary,&path)?;
                    Ok(())
                })();
                if result.is_err() { let _=fs::remove_file(&temporary); }
                result?;
            }
            transaction.execute("INSERT INTO evidence (evidence_id,project_id,run_id,producing_role_instance_id,evidence_type,stored_path,sha256,byte_length,created_at)
                VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",params![id,project_id,request.run_id,actor.role_instance_id,CLOSEOUT_EVIDENCE_TYPE,relative,original_hash,bytes.len() as u64,request.recorded_at])?;
            // Deliberately no event, TOKEN, plan, runtime snapshot, D2 or archival write.
            Ok(CloseoutSummaryResult { status:"summary_recorded".into(),run_id:request.run_id.clone(),original_id:request.original_id.clone(),
                closeout_summary:summary,device_signature:request.device_signature.clone() })
        })
    }
}

fn read_original(
    connection: &Connection,
    root: &Path,
    run_id: &str,
    id: &str,
) -> Result<CloseoutOriginal, StateError> {
    let (stored_path,expected_hash,length,author,at,revision):(String,String,u64,String,String,u64)=connection.query_row(
        "SELECT e.stored_path,e.sha256,e.byte_length,e.producing_role_instance_id,e.created_at,
          (SELECT COUNT(*) FROM evidence old WHERE old.run_id=e.run_id AND old.evidence_type=e.evidence_type AND old.rowid<=e.rowid)
         FROM evidence e WHERE e.run_id=?1 AND e.evidence_id=?2 AND e.evidence_type=?3",
        params![run_id,id,CLOSEOUT_EVIDENCE_TYPE],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?)))?;
    if Path::new(&stored_path)
        .components()
        .any(|c| !matches!(c, Component::Normal(_)))
    {
        return Err(invalid("summary evidence path is not relative"));
    }
    let path = root.join(stored_path);
    if !path.canonicalize()?.starts_with(root.canonicalize()?) {
        return Err(invalid("summary evidence escaped data root"));
    }
    let bytes = fs::read(&path)?;
    if bytes.len() as u64 != length || hash(&bytes) != expected_hash {
        return Err(invalid(
            "summary original evidence does not match its registered hash",
        ));
    }
    let original: CloseoutOriginal = serde_json::from_slice(&bytes)?;
    let creator:String=connection.query_row("SELECT author_role_instance_id FROM work_events WHERE run_id=?1 AND event_type='RUN_INITIALIZED' ORDER BY rowid LIMIT 1",[run_id],|r|r.get(0))?;
    let summary = &original.closeout_summary;
    if original.run_id != run_id
        || summary.source_id != id
        || source_id(run_id, &original.original_id)? != id
        || summary.authored_by != author
        || author != creator
        || summary.recorded_at != at
        || summary.source_revision != revision
        || summary.content_sha256 != summary.computed_hash()?
    {
        return Err(invalid(
            "summary original provenance does not match registered evidence",
        ));
    }
    Ok(original)
}

pub(crate) fn load_closeout(
    connection: &Connection,
    root: &Path,
    run_id: &str,
) -> Result<Option<CloseoutOriginal>, StateError> {
    let id:Option<String>=connection.query_row(
        "SELECT evidence_id FROM evidence WHERE run_id=?1 AND evidence_type=?2 ORDER BY rowid DESC LIMIT 1",
        params![run_id,CLOSEOUT_EVIDENCE_TYPE],|r|r.get(0)).optional()?;
    // Never fall back to a stale older conclusion when the latest original is corrupt.
    Ok(id.and_then(|id| read_original(connection, root, run_id, &id).ok()))
}
