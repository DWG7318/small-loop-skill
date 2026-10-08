//! Closed, evidence-bound mapping from an actual Desktop recovery to its original handoff.

use super::*;
use serde_json::{json, Value};
use std::io::{BufRead, BufReader};

fn metadata_timeout(root: &Path, thread_id: &str) -> bool {
    let Ok(data) = fs::read(root.join("native.stdout.txt")) else {
        return false;
    };
    if data.len() > 262144 {
        return false;
    }
    let Ok(text) = std::str::from_utf8(&data) else {
        return false;
    };
    let mut client = Vec::new();
    let mut server = Vec::new();
    for line in text.lines() {
        let (target, body) = if let Some(body) = line.strip_prefix("C ") {
            (&mut client, body)
        } else if let Some(body) = line.strip_prefix("S ") {
            (&mut server, body)
        } else {
            continue;
        };
        let Ok(row) = serde_json::from_str::<Value>(body) else {
            return false;
        };
        if !row.is_object() {
            return false;
        }
        target.push(row);
    }
    if client.len() != 3
        || client[0]["method"] != "initialize"
        || !client[0]["params"].is_object()
        || !client[0]["id"].is_u64()
        || client[1] != json!({"method":"initialized","params":{}})
        || client[2]["method"] != "thread/read"
        || !client[2]["id"].is_u64()
        || client[0]["id"] == client[2]["id"]
        || !(client[2]["params"] == json!({"threadId":thread_id,"includeTurns":false})
            || client[2]["params"] == json!({"threadId":thread_id,"includeTurns":true}))
    {
        return false;
    }
    let initialized: Vec<_> = server
        .iter()
        .filter(|row| row["id"] == client[0]["id"])
        .collect();
    initialized.len() == 1
        && initialized[0]["result"].is_object()
        && initialized[0].get("error").is_none()
        && !server.iter().any(|row| row["id"] == client[2]["id"])
}

fn invalid() -> StateError {
    StateError::EvidenceInvalid(
        "Desktop recovery lineage or native platform readback is invalid".into(),
    )
}

fn closed(value: &Value, fields: &[&str]) -> bool {
    value.as_object().is_some_and(|object| {
        object.len() == fields.len() && fields.iter().all(|field| object.contains_key(*field))
    })
}

fn read(path: &Path) -> Result<Value, StateError> {
    serde_json::from_slice(&fs::read(path)?).map_err(|_| invalid())
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Delegation {
    source_thread_id: String,
    input: String,
}

pub(super) fn validate(
    bytes: &[u8],
    request: &CommitDeliveryStartRequest,
) -> Result<NativeStartReceipt, StateError> {
    let packet: Value = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    if !closed(
        &packet,
        &[
            "schema_version",
            "request_sha256",
            "host_receipt_sha256",
            "recovery_sha256",
            "started_sha256",
            "platform_record_path",
        ],
    ) || packet["schema_version"] != "slk.desktop-current-turn-start-evidence/v1"
    {
        return Err(invalid());
    }
    let root = Path::new(&request.start_evidence.stored_path)
        .parent()
        .ok_or_else(invalid)?;
    let original = root.parent().and_then(Path::parent).ok_or_else(invalid)?;
    if root.file_name().and_then(|v| v.to_str()) != Some("desktop-current-turn")
        || root
            .parent()
            .and_then(Path::file_name)
            .and_then(|v| v.to_str())
            != Some("recovery")
        || original.file_name().and_then(|v| v.to_str()) != Some(&request.message_id)
        || original
            .parent()
            .and_then(Path::file_name)
            .and_then(|v| v.to_str())
            != Some(&request.run_id)
        || original.join("started.json").exists()
        || original.join("active-writer.json").exists()
    {
        return Err(invalid());
    }
    let mut objects = Vec::new();
    for (name, hash) in [
        ("request.json", "request_sha256"),
        ("host-receipt.json", "host_receipt_sha256"),
        ("recovery.json", "recovery_sha256"),
        ("started.json", "started_sha256"),
    ] {
        let data = fs::read(root.join(name))?;
        if packet[hash].as_str() != Some(sha256_hex(&data).as_str()) {
            return Err(invalid());
        }
        objects.push(serde_json::from_slice::<Value>(&data).map_err(|_| invalid())?);
    }
    let (prepared, host, recovery, started) = (&objects[0], &objects[1], &objects[2], &objects[3]);
    let endpoint_bytes = fs::read(original.join("endpoint.json"))?;
    let envelope_bytes = fs::read(original.join("envelope.json"))?;
    if sha256_hex(&endpoint_bytes) != request.start_evidence.endpoint_sha256
        || sha256_hex(&envelope_bytes) != request.start_evidence.envelope_sha256
    {
        return Err(invalid());
    }
    let endpoint: Value = serde_json::from_slice(&endpoint_bytes).map_err(|_| invalid())?;
    let envelope: Value = serde_json::from_slice(&envelope_bytes).map_err(|_| invalid())?;
    let thread_id = endpoint["address"]["thread_id"]
        .as_str()
        .ok_or_else(invalid)?;
    let message_id = prepared["recovery_message_id"]
        .as_str()
        .ok_or_else(invalid)?;
    let challenge = prepared["challenge"].as_str().ok_or_else(invalid)?;
    let message = json!({"schema_version":"slk.transport-desktop-current-turn-message/v1",
        "challenge":challenge, "recovery_of_message_id":request.message_id, "recovery_message_id":message_id,
        "run_id":request.run_id, "go_id":request.go_id, "cell_id":request.cell_id,
        "token_sequence":request.token_sequence, "sender_role":"checker",
        "sender_role_instance_id":request.from_role_instance_id, "receiver_role":"supervisor",
        "receiver_role_instance_id":request.to_role_instance_id, "receiver_endpoint_version":request.endpoint_version,
        "payload_type":request.payload_type, "payload_sha256":request.payload_sha256});
    let prompt = format!("SLK Desktop current-turn recovery. Treat this as one new auditable delivery bound to the preserved failed Checker message; do not replay or rewrite the original.\n<slk-desktop-current-turn-recovery>{}</slk-desktop-current-turn-recovery>", serde_json::to_string(&message)?);
    let expected = json!({"schema_version":"slk.transport-desktop-current-turn-request/v1", "status":"PREPARED",
        "original_message_id":request.message_id, "recovery_message_id":message_id,
        "run_id":request.run_id,"go_id":request.go_id,"cell_id":request.cell_id,"token_sequence":request.token_sequence,
        "sender_role":"checker","sender_role_instance_id":request.from_role_instance_id,
        "receiver_role":"supervisor","receiver_role_instance_id":request.to_role_instance_id,
        "receiver_endpoint_version":request.endpoint_version,"payload_type":request.payload_type,
        "payload_sha256":request.payload_sha256,"endpoint_sha256":request.start_evidence.endpoint_sha256,
        "envelope_sha256":request.start_evidence.envelope_sha256,"target_thread_id":thread_id,
        "challenge":challenge,"prompt":prompt,"prompt_sha256":sha256_hex(prompt.as_bytes())});
    let before = &host["before"];
    let after = &host["after"];
    if prepared != &expected
        || message_id == request.message_id
        || !valid_identifier(message_id)
        || !is_lower_sha256(challenge)
        || endpoint["adapter"] != "codex-app-server"
        || endpoint["role_instance_id"] != request.to_role_instance_id
        || envelope["message_id"] != request.message_id
        || envelope["payload_sha256"] != request.payload_sha256
        || envelope["schema_version"] != "slk.transport-envelope/v1"
        || envelope["run_id"] != request.run_id
        || envelope["go_id"] != request.go_id
        || envelope["cell_id"] != request.cell_id
        || envelope["token_sequence"] != request.token_sequence
        || envelope["receiver_endpoint_version"] != request.endpoint_version
        || envelope["sender_role_instance_id"] != request.from_role_instance_id
        || envelope["receiver_role_instance_id"] != request.to_role_instance_id
        || envelope["payload_type"] != request.payload_type
        || sha256_hex(&serde_json::to_vec(&envelope["payload"])?) != request.payload_sha256
        || envelope["sender_role"] != "checker"
        || envelope["receiver_role"] != "supervisor"
        || !closed(
            host,
            &[
                "schema_version",
                "request_sha256",
                "host_thread_id",
                "host_turn_id",
                "host_session_id",
                "target_thread_id",
                "before",
                "after",
                "status",
            ],
        )
        || host["schema_version"] != "slk.transport-desktop-current-turn-host-receipt/v1"
        || host["request_sha256"] != sha256_hex(&serde_json::to_vec(prepared)?)
        || host["target_thread_id"] != thread_id
        || host["status"] != "PLATFORM_READBACK_CONFIRMED"
        || !closed(before, &["thread_status", "turn_id", "turn_status"])
        || !closed(
            after,
            &[
                "thread_status",
                "turn_id",
                "turn_status",
                "platform_item_id",
                "item_type",
                "item_name",
                "item_namespace",
                "message_sha256",
            ],
        )
        || before["turn_id"] != after["turn_id"]
        || before["thread_status"] != "active"
        || after["thread_status"] != "active"
        || !matches!(
            before["turn_status"].as_str(),
            Some("inProgress" | "active")
        )
        || !matches!(after["turn_status"].as_str(), Some("inProgress" | "active"))
        || after["item_type"] != "functionCallOutput"
        || after["item_name"] != "send_message_to_thread"
        || after["item_namespace"] != "codex_app"
        || after["message_sha256"] != prepared["prompt_sha256"]
    {
        return Err(invalid());
    }
    let expected_recovery = json!({"schema_version":"slk.transport-desktop-current-turn-recovery/v1",
        "recovery_of_message_id":request.message_id,"recovery_message_id":message_id,"run_id":request.run_id,
        "thread_id":thread_id,"turn_id":after["turn_id"],"platform_item_id":after["platform_item_id"],
        "payload_sha256":request.payload_sha256,"endpoint_sha256":request.start_evidence.endpoint_sha256,
        "envelope_sha256":request.start_evidence.envelope_sha256,"status":"started"});
    if recovery != &expected_recovery {
        return Err(invalid());
    }
    let mut failure_kind = None;
    for failed_root in [
        original.to_path_buf(),
        original
            .join("recovery/exact-1")
            .join(&request.run_id)
            .join(&request.message_id),
    ] {
        let failed = read(&failed_root.join("failed.json"))?;
        let kind = failed["error_code"].as_str().ok_or_else(invalid)?;
        if !(kind == "CODEX_ACTIVE_WRITER_UNRESOLVED"
            || kind == "CODEX_RPC_TIMEOUT" && metadata_timeout(&failed_root, thread_id))
            || failure_kind.is_some_and(|value| value != kind)
            || failed["status"] != "failed"
            || failed["adapter"] != "codex-app-server"
            || failed["run_id"] != request.run_id
            || failed["message_id"] != request.message_id
            || failed_root.join("started.json").exists()
            || failed_root.join("active-writer.json").exists()
            || failed_root.join("completed.json").exists()
            || read(&failed_root.join("endpoint.json"))? != endpoint
            || read(&failed_root.join("envelope.json"))? != envelope
        {
            return Err(invalid());
        }
        failure_kind = Some(kind.to_owned());
    }
    let native_path = Path::new(
        packet["platform_record_path"]
            .as_str()
            .ok_or_else(invalid)?,
    );
    let home = std::env::var_os("CODEX_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("USERPROFILE").map(|path| PathBuf::from(path).join(".codex")))
        .ok_or_else(invalid)?;
    if !native_path.is_absolute()
        || !fs::canonicalize(native_path)?.starts_with(fs::canonicalize(home.join("sessions"))?)
        || !native_path
            .file_name()
            .and_then(|s| s.to_str())
            .is_some_and(|s| s.starts_with("rollout-") && s.contains(thread_id))
    {
        return Err(invalid());
    }
    let stream = BufReader::new(fs::File::open(native_path)?);
    let mut found = 0;
    let mut wrappers = Vec::new();
    let mut delivered_output = None;
    for (index, line) in stream.lines().enumerate() {
        let line = line?;
        if index == 0 {
            let header: Value = serde_json::from_str(&line).map_err(|_| invalid())?;
            if header["type"] != "session_meta"
                || header["payload"]["id"] != thread_id
                || header["payload"]["originator"] != "Codex Desktop"
            {
                return Err(invalid());
            }
        }
        if !line.contains(after["platform_item_id"].as_str().ok_or_else(invalid)?) {
            continue;
        }
        let row: Value = serde_json::from_str(&line).map_err(|_| invalid())?;
        let payload = &row["payload"];
        if row["type"] == "event_msg"
            && payload["type"] == "item_completed"
            && payload["item"]["id"] == after["platform_item_id"]
        {
            if payload["item"]["type"] != "FunctionCallOutput" {
                return Err(invalid());
            }
            wrappers.push(payload.clone());
            continue;
        }
        if row["type"] != "response_item" || payload["id"] != after["platform_item_id"] {
            continue;
        }
        let output = payload["output"].as_str().ok_or_else(invalid)?;
        if !output.trim().starts_with("<codex_delegation>")
            || !output.trim().ends_with("</codex_delegation>")
            || output.matches("<codex_delegation>").count() != 1
        {
            return Err(invalid());
        }
        let delegation: Delegation = quick_xml::de::from_str(output).map_err(|_| invalid())?;
        let host_thread = host["host_thread_id"].as_str().ok_or_else(invalid)?;
        if payload["type"] != "function_call_output"
            || payload["name"] != "send_message_to_thread"
            || payload["namespace"] != "codex_app"
            || delegation.input != prompt
            || delegation.source_thread_id != host_thread
            || payload["internal_chat_message_metadata_passthrough"]["turn_id"] != after["turn_id"]
            || OffsetDateTime::parse(row["timestamp"].as_str().ok_or_else(invalid)?, &Rfc3339)
                .map_err(|_| invalid())?
                > OffsetDateTime::parse(
                    started["observed_at"].as_str().ok_or_else(invalid)?,
                    &Rfc3339,
                )
                .map_err(|_| invalid())?
        {
            return Err(invalid());
        }
        found += 1;
        delivered_output = Some(output.to_owned());
    }
    if found != 1 {
        return Err(invalid());
    }
    if wrappers.iter().any(|wrapper| {
        wrapper["thread_id"] != thread_id
            || wrapper["turn_id"] != after["turn_id"]
            || wrapper["item"]["name"] != "send_message_to_thread"
            || wrapper["item"]["namespace"] != "codex_app"
            || wrapper["item"]["output"].as_str() != delivered_output.as_deref()
    }) {
        return Err(invalid());
    }
    let mut recovered_request = request.clone();
    recovered_request.message_id = message_id.into(); // validation expectation only; never rewrite proof.
    let receipt = validate_native_start_v2(&serde_json::to_vec(started)?, &recovered_request)?;
    if receipt.native_task.kind != "codex-desktop-turn"
        || receipt.native_task.id
            != format!(
                "{thread_id}:{}:{}",
                after["turn_id"].as_str().ok_or_else(invalid)?,
                after["platform_item_id"].as_str().ok_or_else(invalid)?
            )
        || receipt.native_request_sha256
            != prepared["prompt_sha256"].as_str().ok_or_else(invalid)?
    {
        return Err(invalid());
    }
    Ok(receipt)
}

pub(super) fn target_matches(
    connection: &Connection,
    request: &CommitDeliveryStartRequest,
) -> Result<bool, StateError> {
    let root = Path::new(&request.start_evidence.stored_path)
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .ok_or_else(invalid)?;
    let endpoint = read(&root.join("endpoint.json"))?;
    let identity: Option<(String,String)> = connection.query_row(
        "SELECT session_id,host_identity FROM role_endpoints WHERE run_id=?1 AND role_instance_id=?2 AND endpoint_version=?3 AND state='active'",
        params![request.run_id,request.to_role_instance_id,request.endpoint_version],|row|Ok((row.get(0)?,row.get(1)?))).optional()?;
    Ok(identity.is_some_and(|(session, host)| {
        endpoint["address"]["thread_id"] == session && endpoint["host_id"] == host
    }))
}

/// A historical delivery is not a new FAIL message. Only an already-started recovery
/// of the exact subsequently corrected INCOMPLETE may finish its original handoff.
pub(super) fn historical_route(
    connection: &Connection,
    request: &CommitDeliveryStartRequest,
    receipt: &NativeStartReceipt,
) -> Result<bool, StateError> {
    if request.payload_type != "D1_INCOMPLETE_ESCALATION"
        || receipt.native_task.kind != "codex-desktop-turn"
    {
        return Ok(false);
    }
    let Some((kind, go, cell, author, corrected, details, attempt, occurred)) = connection.query_row(
        "SELECT event_type,go_id,cell_id,author_role_instance_id,corrects_event_id,details_json,attempt,occurred_at
         FROM work_events WHERE run_id=?1 AND event_type IN ('D1_FAILED','D1_PASSED','D1_INCOMPLETE','CELL_SPLIT') ORDER BY rowid DESC LIMIT 1",
        [&request.run_id], |row| Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?,row.get::<_,String>(3)?,
            row.get::<_,Option<String>>(4)?,row.get::<_,String>(5)?,row.get::<_,u64>(6)?,row.get::<_,String>(7)?))).optional()? else { return Ok(false); };
    let root = Path::new(&request.start_evidence.stored_path)
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .ok_or_else(invalid)?;
    let envelope = read(&root.join("envelope.json"))?;
    let detail: Value = serde_json::from_str(&details).map_err(|_| invalid())?;
    let proof = &detail["independent_fail"];
    let target = envelope["payload"]["d1_incomplete_event_id"]
        .as_str()
        .ok_or_else(invalid)?;
    if kind != "D1_FAILED"
        || go != request.go_id
        || cell != request.cell_id
        || author != request.from_role_instance_id
        || corrected.as_deref() != Some(target)
        || detail["verdict"] != "FAIL"
        || proof["schema_version"] != "slk.ocrv-independent-fail/v1"
        || proof["d1_incomplete_event_id"] != target
        || proof["engineering_attempt"] != attempt
        || proof["occurred_at"] != occurred
        || detail["candidate_message_id"] != envelope["payload"]["candidate_message_id"]
        || proof["candidate_commit"]
            != envelope["payload"]["candidate_payload"]["candidate"]["commit"]
        || OffsetDateTime::parse(&receipt.observed_at, &Rfc3339).map_err(|_| invalid())?
            >= OffsetDateTime::parse(&occurred, &Rfc3339).map_err(|_| invalid())?
    {
        return Ok(false);
    }
    let source: Option<(String,String,String,String,u64,String)> = connection.query_row(
        "SELECT event_type,go_id,cell_id,author_role_instance_id,attempt,details_json FROM work_events WHERE run_id=?1 AND event_id=?2",
        params![request.run_id,target], |row|Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?))).optional()?;
    let Some((kind, go, cell, author, attempt, details)) = source else {
        return Ok(false);
    };
    let source: Value = serde_json::from_str(&details).map_err(|_| invalid())?;
    Ok(kind == "D1_INCOMPLETE"
        && go == request.go_id
        && cell == request.cell_id
        && author == request.from_role_instance_id
        && attempt == u64::from(request.attempt)
        && proof["source_attempt"] == attempt
        && source["candidate_message_id"] == detail["candidate_message_id"]
        && source["native_terminal_sha256"] == envelope["payload"]["native_terminal_sha256"]
        && source["native_result_sha256"] == envelope["payload"]["native_result_sha256"])
}
