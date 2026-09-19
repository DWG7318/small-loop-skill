//! Durable evidence copying, identity, and verification.

use std::fs::{self, OpenOptions};
use std::io::{BufReader, Read, Write};
use std::path::{Path, PathBuf};

use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::auth::{authorize_event, Credential, StateError};
use crate::model::EventType;
use crate::schema::open_database;
use crate::write::{current_token_from, valid_identifier, StateStore};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceRequest {
    pub evidence_id: String,
    pub run_id: String,
    pub go_id: Option<String>,
    pub cell_id: Option<String>,
    pub evidence_type: String,
    pub source_path: PathBuf,
    pub occurred_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SavedEvidence {
    pub evidence_id: String,
    pub stored_path: PathBuf,
    pub sha256: String,
    pub byte_length: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvidenceState {
    PresentAndMatching,
    Missing,
    HashMismatch,
}

impl StateStore {
    pub fn register_evidence(
        &self,
        credential: &Credential,
        request: EvidenceRequest,
    ) -> Result<SavedEvidence, StateError> {
        if !valid_identifier(&request.evidence_id) || !request.source_path.is_file() {
            return Err(StateError::EvidenceInvalid(
                request.source_path.display().to_string(),
            ));
        }
        let file_name = request
            .source_path
            .file_name()
            .ok_or_else(|| StateError::EvidenceInvalid("source has no file name".into()))?
            .to_string_lossy();

        let connection = open_database(&self.data_root)?;
        let project_id: String = connection
            .query_row(
                "SELECT project_id FROM runs WHERE run_id=?1",
                [&request.run_id],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| StateError::RunNotFound(request.run_id.clone()))?;
        drop(connection);

        let directory = self
            .data_root
            .join("evidence")
            .join(&project_id)
            .join(&request.run_id);
        fs::create_dir_all(&directory)?;
        let stored_path = directory.join(format!("{}-{file_name}", request.evidence_id));
        let temporary_path = directory.join(format!(".{}.tmp", request.evidence_id));
        if stored_path.exists() || temporary_path.exists() {
            return Err(StateError::EvidenceInvalid(format!(
                "evidence identity already exists: {}",
                request.evidence_id
            )));
        }

        let (sha256, byte_length) = copy_and_hash(&request.source_path, &temporary_path)?;
        if let Err(error) = fs::rename(&temporary_path, &stored_path) {
            let _ = fs::remove_file(&temporary_path);
            return Err(error.into());
        }

        let relative_path = stored_path
            .strip_prefix(&self.data_root)
            .map_err(|_| StateError::EvidenceInvalid("stored path escaped data root".into()))?
            .to_string_lossy()
            .replace('\\', "/");
        let insert_result = self.with_immediate_transaction(|transaction| {
            let actor = authorize_event(
                transaction,
                &request.run_id,
                credential,
                EventType::EvidenceRegistered,
            )?;
            let token = current_token_from(transaction, &request.run_id)?;
            if token.owner_role_instance_id != actor.role_instance_id {
                return Err(StateError::TokenOwnerMismatch {
                    requested_owner: actor.role_instance_id,
                    current_owner: token.owner_role_instance_id,
                });
            }
            if let Some(cell_id) = request.cell_id.as_deref() {
                let exists: Option<i64> = transaction
                    .query_row(
                        "SELECT 1 FROM cell_nodes WHERE run_id=?1 AND cell_id=?2",
                        params![request.run_id, cell_id],
                        |row| row.get(0),
                    )
                    .optional()?;
                if exists.is_none() {
                    return Err(StateError::CellNotFound(cell_id.to_string()));
                }
            }
            transaction.execute(
                "INSERT INTO evidence
                 (evidence_id, project_id, run_id, go_id, cell_id, producing_role_instance_id,
                  evidence_type, stored_path, sha256, byte_length, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
                params![
                    request.evidence_id,
                    project_id,
                    request.run_id,
                    request.go_id,
                    request.cell_id,
                    actor.role_instance_id,
                    request.evidence_type,
                    relative_path,
                    sha256,
                    byte_length,
                    request.occurred_at
                ],
            )?;
            Ok(())
        });
        if let Err(error) = insert_result {
            let _ = fs::remove_file(&stored_path);
            return Err(error);
        }

        Ok(SavedEvidence {
            evidence_id: request.evidence_id,
            stored_path,
            sha256,
            byte_length,
        })
    }

    pub fn verify_evidence(&self, evidence_id: &str) -> Result<EvidenceState, StateError> {
        let connection = open_database(&self.data_root)?;
        let record: Option<(String, String)> = connection
            .query_row(
                "SELECT stored_path, sha256 FROM evidence WHERE evidence_id=?1",
                [evidence_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        let (stored_path, expected_hash) =
            record.ok_or_else(|| StateError::EvidenceNotFound(evidence_id.to_string()))?;
        let path = self.data_root.join(stored_path);
        if !path.is_file() {
            return Ok(EvidenceState::Missing);
        }
        let actual_hash = hash_file(&path)?;
        if actual_hash == expected_hash {
            Ok(EvidenceState::PresentAndMatching)
        } else {
            Ok(EvidenceState::HashMismatch)
        }
    }
}

fn copy_and_hash(source: &Path, destination: &Path) -> Result<(String, u64), StateError> {
    let mut input = BufReader::new(fs::File::open(source)?);
    let mut output = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(destination)?;
    let mut hasher = Sha256::new();
    let mut total = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = input.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        output.write_all(&buffer[..read])?;
        hasher.update(&buffer[..read]);
        total += read as u64;
    }
    output.sync_all()?;
    Ok((hex_digest(hasher.finalize().as_slice()), total))
}

fn hash_file(path: &Path) -> Result<String, StateError> {
    let mut input = BufReader::new(fs::File::open(path)?);
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = input.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hex_digest(hasher.finalize().as_slice()))
}

fn hex_digest(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
