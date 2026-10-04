use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::process::ExitCode;

use serde::de::DeserializeOwned;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use slk_state_core::auth::Credential;
use slk_state_core::config::{configure_at, default_config_path, resolve_data_root_at};
use slk_state_core::evidence::{EvidenceRequest, EvidenceState};
use slk_state_core::model::{
    AdoptMethodContractRequest, BindOverwatcherRequest, CloseOverwatcherRequest, CloseRoleRequest,
    CommitDeliveryStartRequest, InitRunRequest, OperationalObservationRequest,
    OverwatchCycleRequest, RebindSessionRequest, ReconcileRunIdentitiesRequest,
    RecordOverwatcherStatusRequest, RegisterRoleRequest, ReplaceOverwatcherRequest,
    ReplaceRoleRequest, ResumeOverwatcherTurnRequest, RevisePlanRequest, ReviseRoleModelRequest,
    RotateOverwatcherCredentialRequest, TokenHandoffRequest, WriteRequest,
};
use slk_state_core::schema::open_database;
use slk_state_core::write::StateStore;

fn main() -> ExitCode {
    match run() {
        Ok(value) => {
            println!(
                "{}",
                serde_json::to_string(&value).expect("serialize response")
            );
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!(
                "{}",
                serde_json::to_string(&json!({
                    "status": "error",
                    "code": error.code,
                    "message": error.message
                }))
                .expect("serialize error")
            );
            ExitCode::FAILURE
        }
    }
}

#[derive(Debug)]
struct CliError {
    code: &'static str,
    message: String,
}

impl CliError {
    fn usage(message: impl Into<String>) -> Self {
        Self {
            code: "SLK_STATE_USAGE",
            message: message.into(),
        }
    }

    fn command(error: impl std::fmt::Display) -> Self {
        Self {
            code: "SLK_STATE_COMMAND_FAILED",
            message: error.to_string(),
        }
    }
}

fn run() -> Result<Value, CliError> {
    let arguments = env::args().skip(1).collect::<Vec<_>>();
    let command = arguments
        .first()
        .map(String::as_str)
        .ok_or_else(|| CliError::usage(help()))?;
    if matches!(command, "--help" | "-h" | "help") {
        return Ok(json!({"status":"ok","help":help()}));
    }
    if matches!(command, "--version" | "-V" | "version") {
        return Ok(json!({"status":"ok","version":env!("CARGO_PKG_VERSION")}));
    }
    match command {
        "configure" => configure(&arguments[1..]),
        "init-run" => init_run(&arguments[1..]),
        "reconcile-run-identities" => reconcile_run_identities(&arguments[1..]),
        "adopt-method-contract" => adopt_method_contract(&arguments[1..]),
        "bind-overwatcher" => bind_overwatcher(&arguments[1..]),
        "record-overwatch-cycle" => record_overwatch_cycle(&arguments[1..]),
        "record-overwatcher-status" => record_overwatcher_status(&arguments[1..]),
        "resume-overwatcher-turn" => resume_overwatcher_turn(&arguments[1..]),
        "replace-overwatcher" => replace_overwatcher(&arguments[1..]),
        "rotate-overwatcher-credential" => rotate_overwatcher_credential(&arguments[1..]),
        "wait-for-change" => wait_for_change(&arguments[1..]),
        "record-observation" => record_observation(&arguments[1..]),
        "close-overwatcher" => close_overwatcher(&arguments[1..]),
        "close-role" => close_role(&arguments[1..]),
        "register-role" => register_role(&arguments[1..]),
        "handoff" => handoff(&arguments[1..]),
        "commit-delivery-start" => commit_delivery_start(&arguments[1..]),
        "write" => write_event(&arguments[1..]),
        "revise-plan" => revise_plan(&arguments[1..]),
        "replace-role" => replace_role(&arguments[1..]),
        "rebind-session" => rebind_session(&arguments[1..]),
        "revise-role-model" => revise_role_model(&arguments[1..]),
        "register-evidence" => register_evidence(&arguments[1..]),
        "authenticate-role" => authenticate_role(&arguments[1..]),
        "export" => export(&arguments[1..]),
        "verify-evidence" => verify_evidence(&arguments[1..]),
        _ => Err(CliError::usage(format!(
            "unknown command {command}\n{}",
            help()
        ))),
    }
}

fn configure(arguments: &[String]) -> Result<Value, CliError> {
    let data_root = required_path(arguments, "--data-root")?;
    let configured = configure_at(&config_path()?, &data_root).map_err(CliError::command)?;
    open_database(&configured).map_err(CliError::command)?;
    Ok(json!({"status":"configured","data_root":configured}))
}

fn init_run(arguments: &[String]) -> Result<Value, CliError> {
    let request: InitRunRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let credential_target = optional_value(arguments, "--credential-out").map(PathBuf::from);
    let credential_stage = if let Some(target) = credential_target.as_ref() {
        if !target.is_absolute() {
            return Err(CliError::usage("--credential-out must be an absolute path"));
        }
        if target.exists() {
            return Err(CliError::usage("--credential-out target already exists"));
        }
        let parent = target
            .parent()
            .ok_or_else(|| CliError::usage("--credential-out has no parent directory"))?;
        if !parent.is_dir() {
            return Err(CliError::usage(
                "--credential-out parent must already exist",
            ));
        }
        let mut selected = None;
        for ordinal in 0..100_u32 {
            let temporary = parent.join(format!(
                ".{}.{}.{}.tmp",
                target
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or("credential"),
                std::process::id(),
                ordinal
            ));
            match OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)
            {
                Ok(file) => {
                    selected = Some((temporary, file));
                    break;
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(CliError::command(error)),
            }
        }
        Some(selected.ok_or_else(|| CliError::usage("cannot reserve credential output"))?)
    } else {
        None
    };
    let store = configured_store()?;
    let initialized = match store.init_run(request) {
        Ok(value) => value,
        Err(error) => {
            if let Some((temporary, _)) = credential_stage.as_ref() {
                let _ = fs::remove_file(temporary);
            }
            return Err(CliError::command(error));
        }
    };
    let export = refresh_export(&store, &run_id);
    if let (Some(target), Some((temporary, mut file))) =
        (credential_target.as_ref(), credential_stage)
    {
        let secret = initialized.supervisor_credential.expose_secret();
        file.write_all(secret.as_bytes())
            .map_err(CliError::command)?;
        file.write_all(b"\n").map_err(CliError::command)?;
        file.sync_all().map_err(CliError::command)?;
        drop(file);
        fs::rename(&temporary, target).map_err(CliError::command)?;
        let digest = format!("{:x}", Sha256::digest(secret.as_bytes()));
        Ok(json!({
            "status":"initialized",
            "run_id":run_id,
            "credential_delivery":"ATOMIC_FILE",
            "supervisor_credential_file":target,
            "supervisor_credential_sha256":digest,
            "export":export
        }))
    } else {
        Ok(json!({
            "status":"initialized",
            "run_id":run_id,
            "credential_delivery":"STDOUT_LEGACY",
            "supervisor_credential":initialized.supervisor_credential.expose_secret(),
            "export":export
        }))
    }
}

fn reconcile_run_identities(arguments: &[String]) -> Result<Value, CliError> {
    let request: ReconcileRunIdentitiesRequest = request(arguments)?;
    let store = configured_store()?;
    let result = store
        .reconcile_run_identities(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status": result.status.to_ascii_lowercase(),
        "receipt_id": result.receipt_id,
        "canonical_run_id": result.canonical_run_id
    }))
}

fn adopt_method_contract(arguments: &[String]) -> Result<Value, CliError> {
    let request: AdoptMethodContractRequest = request(arguments)?;
    let store = configured_store()?;
    let result = store
        .adopt_method_contract(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status": result.status.to_ascii_lowercase(),
        "receipt_id": result.receipt_id,
        "run_id": result.run_id,
        "effective_version": result.effective_version
    }))
}

fn register_role(arguments: &[String]) -> Result<Value, CliError> {
    let request: RegisterRoleRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let issued = store
        .register_role(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"registered",
        "run_id":run_id,
        "role_credential":issued.credential.expose_secret(),
        "credential_id":issued.credential_id,
        "export":refresh_export(&store, &run_id)
    }))
}

fn bind_overwatcher(arguments: &[String]) -> Result<Value, CliError> {
    let request: BindOverwatcherRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let role_instance_id = request.identity.role_instance_id.clone();
    let store = configured_store()?;
    let issued = store
        .bind_overwatcher(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"overwatcher_bound",
        "run_id":run_id,
        "overwatcher_role_instance_id":role_instance_id,
        "overwatcher_write_credential":issued.credential.expose_secret(),
        "overwatcher_credential_id":issued.credential_id,
        "write_credential_delivery":"ONE_TIME_NON_REPLAYABLE",
        "export":refresh_export(&store, &run_id)
    }))
}

fn record_observation(arguments: &[String]) -> Result<Value, CliError> {
    let request: OperationalObservationRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let observation_id = request.observation_id.clone();
    let store = configured_store()?;
    store
        .record_observation(&overwatcher_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"observation_recorded",
        "run_id":run_id,
        "observation_id":observation_id
    }))
}

fn record_overwatch_cycle(arguments: &[String]) -> Result<Value, CliError> {
    let request: OverwatchCycleRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let cycle_id = request.cycle_id.clone();
    let cycle_sequence = request.cycle_sequence;
    let store = configured_store()?;
    store
        .record_overwatch_cycle(&overwatcher_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"overwatch_cycle_recorded",
        "run_id":run_id,
        "cycle_id":cycle_id,
        "cycle_sequence":cycle_sequence
    }))
}

fn record_overwatcher_status(arguments: &[String]) -> Result<Value, CliError> {
    let request: RecordOverwatcherStatusRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let status_id = request.status_id.clone();
    let native_liveness = request.native_liveness.as_str();
    let store = configured_store()?;
    store
        .record_overwatcher_status(&overwatcher_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"overwatcher_status_recorded",
        "run_id":run_id,
        "status_id":status_id,
        "native_liveness":native_liveness
    }))
}

fn resume_overwatcher_turn(arguments: &[String]) -> Result<Value, CliError> {
    let request: ResumeOverwatcherTurnRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let session_id = request.session_id.clone();
    let foreground_turn_id = request.foreground_turn_id.clone();
    let store = configured_store()?;
    store
        .resume_overwatcher_turn(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"overwatcher_turn_resumed",
        "run_id":run_id,
        "session_id":session_id,
        "foreground_turn_id":foreground_turn_id,
        "export":refresh_export(&store, &run_id)
    }))
}

fn wait_for_change(arguments: &[String]) -> Result<Value, CliError> {
    let run_id = required_value(arguments, "--run-id")?;
    let after_revision = required_value(arguments, "--after-revision")?
        .parse::<u64>()
        .map_err(|_| CliError::usage("--after-revision must be an unsigned integer"))?;
    let timeout_seconds = required_value(arguments, "--timeout-seconds")?
        .parse::<u64>()
        .map_err(|_| CliError::usage("--timeout-seconds must be an unsigned integer"))?;
    let result = configured_store()?
        .wait_for_change(&run_id, after_revision, timeout_seconds)
        .map_err(CliError::command)?;
    Ok(json!(result))
}

fn close_overwatcher(arguments: &[String]) -> Result<Value, CliError> {
    let request: CloseOverwatcherRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    store
        .close_overwatcher(&overwatcher_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({"status":"overwatcher_closed","run_id":run_id}))
}

fn close_role(arguments: &[String]) -> Result<Value, CliError> {
    let request: CloseRoleRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let result = store
        .close_role(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":result.status,
        "run_id":run_id,
        "role_instance_id":result.role_instance_id,
        "export":refresh_export(&store, &run_id)
    }))
}

fn replace_overwatcher(arguments: &[String]) -> Result<Value, CliError> {
    let request: ReplaceOverwatcherRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let binding_revision = request.expected_binding_revision + 1;
    let role_instance_id = request.replacement.role_instance_id.clone();
    let store = configured_store()?;
    let issued = store
        .replace_overwatcher(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"overwatcher_replaced",
        "run_id":run_id,
        "binding_revision":binding_revision,
        "overwatcher_role_instance_id":role_instance_id,
        "overwatcher_write_credential":issued.credential.expose_secret(),
        "overwatcher_credential_id":issued.credential_id,
        "write_credential_delivery":"ONE_TIME_NON_REPLAYABLE"
    }))
}

fn rotate_overwatcher_credential(arguments: &[String]) -> Result<Value, CliError> {
    let request: RotateOverwatcherCredentialRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let result = store
        .rotate_overwatcher_credential(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"overwatcher_credential_rotated",
        "run_id":run_id,
        "binding_revision":result.binding_revision,
        "runtime_revision":result.runtime_revision,
        "overwatcher_role_instance_id":result.role_instance_id,
        "overwatcher_write_credential":result.issued.credential.expose_secret(),
        "overwatcher_credential_id":result.issued.credential_id,
        "write_credential_delivery":"ONE_TIME_NON_REPLAYABLE"
    }))
}

fn handoff(arguments: &[String]) -> Result<Value, CliError> {
    let request: TokenHandoffRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let token = store
        .handoff_token(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({"status":"handed_off","token":{
        "sequence":token.sequence,
        "owner_role_instance_id":token.owner_role_instance_id,
        "go_id":token.go_id,
        "cell_id":token.cell_id
    },"export":refresh_export(&store, &run_id)}))
}

fn commit_delivery_start(arguments: &[String]) -> Result<Value, CliError> {
    let request: CommitDeliveryStartRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let result = store
        .commit_delivery_start(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status": result.status.to_ascii_lowercase(),
        "run_id": run_id,
        "runtime_revision": result.runtime_revision,
        "token_sequence": result.token.sequence,
        "token_owner_role_instance_id": result.token.owner_role_instance_id,
        "event_id": result.event_id,
        "message_id": result.message_id
    }))
}

fn write_event(arguments: &[String]) -> Result<Value, CliError> {
    let request: WriteRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    store
        .write_event(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({"status":"recorded","run_id":run_id,"export":refresh_export(&store, &run_id)}))
}

fn revise_plan(arguments: &[String]) -> Result<Value, CliError> {
    let request: RevisePlanRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let revision = store
        .revise_plan(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(
        json!({"status":"revised","run_id":run_id,"revision":revision,"export":refresh_export(&store, &run_id)}),
    )
}

fn revise_role_model(arguments: &[String]) -> Result<Value, CliError> {
    let request: ReviseRoleModelRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let result = store
        .revise_role_model(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status": result.status.to_ascii_lowercase(),
        "run_id": run_id,
        "role_instance_id": result.role_instance_id,
        "previous_model": result.previous_model,
        "previous_reasoning": result.previous_reasoning,
        "model": result.model,
        "reasoning": result.reasoning,
        "runtime_revision": result.runtime_revision,
        "export": refresh_export(&store, &run_id)
    }))
}

fn replace_role(arguments: &[String]) -> Result<Value, CliError> {
    let request: ReplaceRoleRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let issued = store
        .replace_role(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"replaced",
        "run_id":run_id,
        "replacement_credential":issued.credential.expose_secret(),
        "credential_id":issued.credential_id,
        "export":refresh_export(&store, &run_id)
    }))
}

fn rebind_session(arguments: &[String]) -> Result<Value, CliError> {
    let request: RebindSessionRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let role_instance_id = request.role_instance_id.clone();
    let endpoint_version = request.endpoint.endpoint_version;
    let store = configured_store()?;
    store
        .rebind_session(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"rebound",
        "run_id":run_id,
        "role_instance_id":role_instance_id,
        "endpoint_version":endpoint_version,
        "export":refresh_export(&store, &run_id)
    }))
}

fn register_evidence(arguments: &[String]) -> Result<Value, CliError> {
    let request: EvidenceRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let saved = store
        .register_evidence(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"registered",
        "run_id":run_id,
        "evidence_id":saved.evidence_id,
        "stored_path":saved.stored_path,
        "sha256":saved.sha256,
        "byte_length":saved.byte_length,
        "export":refresh_export(&store, &run_id)
    }))
}

fn export(arguments: &[String]) -> Result<Value, CliError> {
    let run_id = required_value(arguments, "--run-id")?;
    let store = configured_store()?;
    store
        .authenticate_active_role(&run_id, &role_credential()?)
        .map_err(CliError::command)?;
    let path = store.export_run(&run_id).map_err(CliError::command)?;
    Ok(json!({"status":"exported","run_id":run_id,"path":path}))
}

fn authenticate_role(arguments: &[String]) -> Result<Value, CliError> {
    let run_id = required_value(arguments, "--run-id")?;
    let expected_role_instance_id = required_value(arguments, "--role-instance-id")?;
    let store = configured_store()?;
    let actor = store
        .authenticate_active_role(&run_id, &role_credential()?)
        .map_err(CliError::command)?;
    if actor.role_instance_id != expected_role_instance_id {
        return Err(CliError::command(
            "credential does not match the requested active role instance",
        ));
    }
    let snapshot = store
        .query_run(&run_id)
        .map_err(CliError::command)?
        .runtime_snapshot
        .ok_or_else(|| CliError::command("runtime snapshot is unavailable"))?;
    Ok(json!({
        "status":"authenticated",
        "run_id":run_id,
        "role_instance_id":actor.role_instance_id,
        "role":actor.role.as_str(),
        "runtime_revision":snapshot.runtime_revision
    }))
}

fn verify_evidence(arguments: &[String]) -> Result<Value, CliError> {
    let run_id = required_value(arguments, "--run-id")?;
    let store = configured_store()?;
    store
        .authenticate_active_role(&run_id, &role_credential()?)
        .map_err(CliError::command)?;
    let run = store.query_run(&run_id).map_err(CliError::command)?;
    let mut results = Vec::new();
    for evidence in run.evidence {
        let state = match store
            .verify_evidence(&evidence.evidence_id)
            .map_err(CliError::command)?
        {
            EvidenceState::PresentAndMatching => "present_and_matching",
            EvidenceState::Missing => "missing",
            EvidenceState::HashMismatch => "hash_mismatch",
        };
        results.push(json!({"evidence_id":evidence.evidence_id,"state":state}));
    }
    Ok(json!({"status":"verified","run_id":run_id,"evidence":results}))
}

fn request<T: DeserializeOwned>(arguments: &[String]) -> Result<T, CliError> {
    let path = required_path(arguments, "--request")?;
    let bytes = fs::read(&path).map_err(CliError::command)?;
    serde_json::from_slice(&bytes).map_err(CliError::command)
}

fn required_path(arguments: &[String], option: &str) -> Result<PathBuf, CliError> {
    required_value(arguments, option).map(PathBuf::from)
}

fn required_value(arguments: &[String], option: &str) -> Result<String, CliError> {
    let index = arguments
        .iter()
        .position(|value| value == option)
        .ok_or_else(|| CliError::usage(format!("missing {option}")))?;
    arguments
        .get(index + 1)
        .cloned()
        .ok_or_else(|| CliError::usage(format!("missing value for {option}")))
}

fn optional_value(arguments: &[String], option: &str) -> Option<String> {
    arguments
        .iter()
        .position(|value| value == option)
        .and_then(|index| arguments.get(index + 1))
        .cloned()
}

fn configured_store() -> Result<StateStore, CliError> {
    let root = resolve_data_root_at(&config_path()?).map_err(CliError::command)?;
    Ok(StateStore::new(root))
}

fn config_path() -> Result<PathBuf, CliError> {
    if let Some(path) = env::var_os("SLK_CONFIG_PATH") {
        return Ok(PathBuf::from(path));
    }
    default_config_path().map_err(CliError::command)
}

fn role_credential() -> Result<Credential, CliError> {
    let secret = env::var("SLK_ROLE_CREDENTIAL").map_err(|_| CliError {
        code: "SLK_ROLE_CREDENTIAL_REQUIRED",
        message: "SLK_ROLE_CREDENTIAL must be supplied through the environment".into(),
    })?;
    Ok(Credential::from_secret(secret))
}

fn overwatcher_credential() -> Result<Credential, CliError> {
    let secret = env::var("SLK_OVERWATCHER_CREDENTIAL").map_err(|_| CliError {
        code: "SLK_OVERWATCHER_CREDENTIAL_REQUIRED",
        message: "SLK_OVERWATCHER_CREDENTIAL must be supplied through the environment".into(),
    })?;
    Ok(Credential::from_secret(secret))
}

fn refresh_export(store: &StateStore, run_id: &str) -> Value {
    match store.export_run(run_id) {
        Ok(path) => json!({"path":path}),
        Err(error) => json!({"warning":error.to_string()}),
    }
}

fn help() -> &'static str {
    "slk-state <configure|init-run|reconcile-run-identities|adopt-method-contract|bind-overwatcher|record-overwatch-cycle|record-overwatcher-status|resume-overwatcher-turn|replace-overwatcher|rotate-overwatcher-credential|wait-for-change|record-observation|close-overwatcher|close-role|register-role|handoff|commit-delivery-start|write|revise-plan|revise-role-model|replace-role|rebind-session|register-evidence|authenticate-role|export|verify-evidence> [options]\nRole credentials use SLK_ROLE_CREDENTIAL; Overwatcher observation commands use SLK_OVERWATCHER_CREDENTIAL."
}
