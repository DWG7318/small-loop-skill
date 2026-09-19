//! Run-scoped write credentials and fixed role/event ownership.

use std::fmt;

use rusqlite::{params, Connection, OptionalExtension};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::config::ConfigError;
use crate::model::{EventType, Role};
use crate::schema::SchemaError;

#[derive(Clone, PartialEq, Eq)]
pub struct Credential(String);

impl Credential {
    pub fn from_secret(secret: impl Into<String>) -> Self {
        Self(secret.into())
    }

    pub fn expose_secret(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for Credential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("Credential([REDACTED])")
    }
}

#[derive(Debug, Clone)]
pub struct IssuedCredential {
    pub credential_id: String,
    pub credential: Credential,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthorizedActor {
    pub role_instance_id: String,
    pub role: Role,
}

#[derive(Debug, Error)]
pub enum StateError {
    #[error("write credential is invalid for this Run")]
    CredentialInvalid,
    #[error("write credential has been revoked")]
    CredentialRevoked,
    #[error("role instance is not current and active: {0}")]
    RoleInstanceNotCurrent(String),
    #[error("{role:?} cannot author {event:?}")]
    RoleNotAuthorized { role: Role, event: EventType },
    #[error("stored role value is invalid: {0}")]
    StoredRoleInvalid(String),
    #[error("role {actor:?} cannot create role {target:?}")]
    RoleCreationNotAuthorized { actor: Role, target: Role },
    #[error("request role instance does not match authenticated role instance")]
    RoleInstanceMismatch,
    #[error("Run already exists: {0}")]
    RunAlreadyExists(String),
    #[error("invalid linear plan: {0}")]
    InvalidPlan(String),
    #[error("plan revision {requested} is not current revision {current}")]
    PlanRevisionMismatch { requested: u32, current: u32 },
    #[error("SLK TOKEN sequence {requested} already exists; current sequence is {current}")]
    TokenSequenceConflict { requested: u64, current: u64 },
    #[error("SLK TOKEN sequence must be {expected}, not {requested}")]
    TokenSequenceGap { requested: u64, expected: u64 },
    #[error("SLK TOKEN is owned by {current_owner}, not {requested_owner}")]
    TokenOwnerMismatch {
        requested_owner: String,
        current_owner: String,
    },
    #[error("role endpoint is not active at requested version")]
    EndpointNotCurrent,
    #[error("SLK TOKEN route {from:?} -> {to:?} is not part of the SLK loop")]
    InvalidTokenRoute { from: Role, to: Role },
    #[error("Run was not found: {0}")]
    RunNotFound(String),
    #[error("an explicit Run ID is required")]
    RunIdRequired,
    #[error("CELL was not found: {0}")]
    CellNotFound(String),
    #[error("evidence source or identity is invalid: {0}")]
    EvidenceInvalid(String),
    #[error("evidence was not found: {0}")]
    EvidenceNotFound(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error(transparent)]
    Schema(#[from] SchemaError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Sqlite(#[from] rusqlite::Error),
}

pub fn issue_credential(
    connection: &Connection,
    run_id: &str,
    role_instance_id: &str,
    issued_at: &str,
) -> Result<IssuedCredential, StateError> {
    let active: Option<i64> = connection
        .query_row(
            "SELECT 1 FROM role_instances WHERE run_id=?1 AND role_instance_id=?2 AND lifecycle='active'",
            params![run_id, role_instance_id],
            |row| row.get(0),
        )
        .optional()?;
    if active.is_none() {
        return Err(StateError::RoleInstanceNotCurrent(
            role_instance_id.to_string(),
        ));
    }

    let credential_id = format!("credential-{}", Uuid::new_v4().simple());
    let secret = format!("slk_{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
    let hash = hash_secret(&secret);
    connection.execute(
        "INSERT INTO role_credentials (credential_id, run_id, role_instance_id, credential_sha256, state, issued_at) VALUES (?1, ?2, ?3, ?4, 'active', ?5)",
        params![credential_id, run_id, role_instance_id, encode_hex(&hash), issued_at],
    )?;
    Ok(IssuedCredential {
        credential_id,
        credential: Credential::from_secret(secret),
    })
}

pub fn revoke_credential(
    connection: &Connection,
    credential_id: &str,
    revoked_at: &str,
) -> Result<(), StateError> {
    let changed = connection.execute(
        "UPDATE role_credentials SET state='revoked', revoked_at=?2 WHERE credential_id=?1 AND state='active'",
        params![credential_id, revoked_at],
    )?;
    if changed == 0 {
        return Err(StateError::CredentialInvalid);
    }
    Ok(())
}

pub fn authorize_event(
    connection: &Connection,
    run_id: &str,
    credential: &Credential,
    event: EventType,
) -> Result<AuthorizedActor, StateError> {
    let candidate = hash_secret(credential.expose_secret());
    let mut statement = connection.prepare(
        "SELECT c.credential_sha256, c.state, r.role_instance_id, r.role, r.lifecycle
         FROM role_credentials c
         JOIN role_instances r ON r.role_instance_id=c.role_instance_id
         WHERE c.run_id=?1",
    )?;
    let mut rows = statement.query([run_id])?;
    while let Some(row) = rows.next()? {
        let stored_text: String = row.get(0)?;
        let Some(stored) = decode_hash(&stored_text) else {
            continue;
        };
        if !constant_shape_equal(&candidate, &stored) {
            continue;
        }

        let credential_state: String = row.get(1)?;
        let role_instance_id: String = row.get(2)?;
        let role_text: String = row.get(3)?;
        let lifecycle: String = row.get(4)?;
        if credential_state != "active" || lifecycle != "active" {
            return Err(StateError::CredentialRevoked);
        }
        let role = Role::parse(&role_text)
            .ok_or_else(|| StateError::StoredRoleInvalid(role_text.clone()))?;
        if !event.is_owned_by(role) {
            return Err(StateError::RoleNotAuthorized { role, event });
        }
        return Ok(AuthorizedActor {
            role_instance_id,
            role,
        });
    }
    Err(StateError::CredentialInvalid)
}

fn hash_secret(secret: &str) -> [u8; 32] {
    Sha256::digest(secret.as_bytes()).into()
}

fn constant_shape_equal(left: &[u8; 32], right: &[u8; 32]) -> bool {
    let mut difference = 0_u8;
    for index in 0..left.len() {
        difference |= left[index] ^ right[index];
    }
    difference == 0
}

fn encode_hex(bytes: &[u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in bytes {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

fn decode_hash(value: &str) -> Option<[u8; 32]> {
    if value.len() != 64 {
        return None;
    }
    let mut bytes = [0_u8; 32];
    for (index, chunk) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = decode_nibble(chunk[0])?;
        let low = decode_nibble(chunk[1])?;
        bytes[index] = (high << 4) | low;
    }
    Some(bytes)
}

fn decode_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}
