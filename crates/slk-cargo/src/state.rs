use std::path::{Path, PathBuf};

use serde_json::json;
use slk_state_core::auth::Credential;
use slk_state_core::model::{EventType, WriteRequest};
use slk_state_core::write::StateStore;
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;
use uuid::Uuid;

use crate::ContentionKind;

#[derive(Clone)]
pub struct StateContext {
    data_root: PathBuf,
    credential: Credential,
    run_id: String,
    go_id: Option<String>,
    cell_id: Option<String>,
    attempt: Option<u32>,
}

impl StateContext {
    pub fn new(
        data_root: impl AsRef<Path>,
        credential: Credential,
        run_id: impl Into<String>,
        go_id: Option<String>,
        cell_id: Option<String>,
        attempt: Option<u32>,
    ) -> Self {
        Self {
            data_root: data_root.as_ref().to_path_buf(),
            credential,
            run_id: run_id.into(),
            go_id,
            cell_id,
            attempt,
        }
    }

    pub(crate) fn record_contended(
        &self,
        kind: ContentionKind,
        target: &Path,
        cargo_attempt: u32,
    ) -> Result<(), String> {
        self.record(
            EventType::ResourceContended,
            json!({
                "resource":"cargo",
                "contention":kind.label(),
                "cargo_attempt":cargo_attempt,
                "target":target
            }),
        )
    }

    pub(crate) fn record_recovered(
        &self,
        kind: ContentionKind,
        target: &Path,
        cargo_attempt: u32,
    ) -> Result<(), String> {
        self.record(
            EventType::ResourceRecovered,
            json!({
                "resource":"cargo",
                "contention":kind.label(),
                "cargo_attempt":cargo_attempt,
                "target":target
            }),
        )
    }

    fn record(&self, event_type: EventType, details: serde_json::Value) -> Result<(), String> {
        let store = StateStore::new(&self.data_root);
        let actor = store
            .authenticate_active_role(&self.run_id, &self.credential)
            .map_err(|error| error.to_string())?;
        let run = store
            .query_run(&self.run_id)
            .map_err(|error| error.to_string())?;
        let occurred_at = OffsetDateTime::now_utc()
            .format(&Rfc3339)
            .map_err(|error| error.to_string())?;
        store
            .write_event(
                &self.credential,
                WriteRequest {
                    event_id: format!("slk-cargo-{}", Uuid::new_v4().simple()),
                    run_id: self.run_id.clone(),
                    go_id: self.go_id.clone(),
                    cell_id: self.cell_id.clone(),
                    attempt: self.attempt,
                    plan_revision: run.summary.current_plan_revision,
                    role_instance_id: actor.role_instance_id,
                    event_type,
                    details,
                    corrects_event_id: None,
                    occurred_at,
                },
            )
            .map_err(|error| error.to_string())
    }
}
