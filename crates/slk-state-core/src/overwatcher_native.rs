//! Read the caller-selected native records; never discover sessions or change them.
//! Native JSONL is local evidence, not a cryptographic platform attestation.
use super::{sha256_hex, validate_evidence_reference, EvidenceReference, StateError};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::{BufRead, BufReader},
    path::Path,
};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

pub(super) struct Binding<'a> {
    pub run_id: &'a str,
    pub role_instance_id: &'a str,
    pub method_version: &'a str,
    pub native_address: &'a Value,
    pub canonical_task_id: &'a str,
    pub execution_id: &'a str,
}

pub(super) struct Observation {
    pub status: &'static str,
    pub previous_status: Option<&'static str>,
    pub previous_execution_id: Option<String>,
    pub metadata: Value,
}

fn invalid() -> StateError {
    StateError::OverwatcherCycleInvalid(
        "exact native Overwatcher evidence is absent, stale, conflicting, or unsupported".into(),
    )
}
fn require(ok: bool) -> Result<(), StateError> {
    if ok {
        Ok(())
    } else {
        Err(invalid())
    }
}
fn text(value: &Value) -> Result<&str, StateError> {
    value
        .as_str()
        .filter(|s| !s.is_empty() && *s == s.trim())
        .ok_or_else(invalid)
}
fn timestamp(value: &Value) -> Result<OffsetDateTime, StateError> {
    OffsetDateTime::parse(text(value)?, &Rfc3339).map_err(|_| invalid())
}

// Reject duplicate keys at every depth, including embedded tool JSON. A later
// duplicate must not silently override the identity that another reader saw.
struct Strict(Value);
impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct Visitor;
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = Strict;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("unambiguous JSON")
            }
            fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<Strict, E> {
                Ok(Strict(v.into()))
            }
            fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<Strict, E> {
                Ok(Strict(v.into()))
            }
            fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<Strict, E> {
                Ok(Strict(v.into()))
            }
            fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Strict, E> {
                serde_json::Number::from_f64(v)
                    .map(|n| Strict(n.into()))
                    .ok_or_else(|| E::custom("invalid number"))
            }
            fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Strict, E> {
                Ok(Strict(v.into()))
            }
            fn visit_string<E: serde::de::Error>(self, v: String) -> Result<Strict, E> {
                Ok(Strict(v.into()))
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<Strict, E> {
                Ok(Strict(Value::Null))
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(self, mut a: A) -> Result<Strict, A::Error> {
                let mut values = Vec::new();
                while let Some(Strict(v)) = a.next_element()? {
                    values.push(v);
                }
                Ok(Strict(values.into()))
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(self, mut a: A) -> Result<Strict, A::Error> {
                let mut values = serde_json::Map::new();
                while let Some((k, Strict(v))) = a.next_entry::<String, Strict>()? {
                    if values.insert(k, v).is_some() {
                        return Err(serde::de::Error::custom("duplicate key"));
                    }
                }
                Ok(Strict(values.into()))
            }
        }
        d.deserialize_any(Visitor)
    }
}
fn object(raw: &[u8]) -> Result<Value, StateError> {
    let value = serde_json::from_slice::<Strict>(raw)
        .map_err(|_| invalid())?
        .0;
    require(value.is_object())?;
    Ok(value)
}
fn regular(path: &Path) -> Result<(), StateError> {
    require(path.is_absolute())?;
    for ancestor in path.ancestors() {
        let meta = fs::symlink_metadata(ancestor).map_err(|_| invalid())?;
        require(!meta.file_type().is_symlink())?;
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            require(meta.file_attributes() & 0x400 == 0)?;
        }
    }
    require(path.is_file())
}
fn hashed_object(path: &Path, hash: &Value) -> Result<Value, StateError> {
    regular(path)?;
    let bytes = fs::read(path).map_err(|_| invalid())?;
    require(sha256_hex(&bytes) == text(hash)?)?;
    object(&bytes)
}
fn execution(value: &str) -> Result<(&str, &str), StateError> {
    let (kind, id) = value.split_once(':').ok_or_else(invalid)?;
    require(
        matches!(kind, "codex-subagent-spawn" | "codex-subagent-followup")
            && id.starts_with("call_")
            && id.len() > 5
            && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_'),
    )?;
    Ok((kind, id))
}
fn child_path(value: &str) -> bool {
    value.starts_with("/root/")
        && value[6..].split('/').all(|s| {
            !s.is_empty()
                && s.bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
        })
}
fn target(arguments: &Value, child: &str) -> Result<bool, StateError> {
    let value = text(&arguments["target"])?;
    require(
        child_path(value)
            || value
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_'),
    )?;
    Ok(value == child || Some(value) == child.rsplit('/').next())
}
fn covered(arguments: &Value, child: &str) -> Result<bool, StateError> {
    let fields = arguments.as_object().ok_or_else(invalid)?;
    require(fields.keys().all(|k| k == "path_prefix"))?;
    if let Some(prefix) = fields.get("path_prefix") {
        let prefix = text(prefix)?;
        require(prefix == "/root" || child_path(prefix))?;
        Ok(child == prefix || child.starts_with(&format!("{prefix}/")))
    } else {
        Ok(true)
    }
}

struct Record {
    sequence: usize,
    value: Value,
    hash: String,
    location: Value,
}
impl Record {
    fn payload(&self) -> &Value {
        &self.value["payload"]
    }
    fn at(&self) -> Result<OffsetDateTime, StateError> {
        timestamp(&self.value["timestamp"])
    }
}
struct Records {
    calls: BTreeMap<String, Vec<Record>>,
    outputs: BTreeMap<String, Vec<Record>>,
    metadata: Vec<Value>,
    session_metadata: Vec<Value>,
    child_links: Vec<Record>,
}
impl Records {
    fn pair(&self, id: &str, name: &str) -> Result<(&Record, &Record, Value, Value), StateError> {
        let calls = self.calls.get(id).ok_or_else(invalid)?;
        let outputs = self.outputs.get(id).ok_or_else(invalid)?;
        require(calls.len() == 1 && outputs.len() == 1)?;
        let (call, output) = (&calls[0], &outputs[0]);
        require(
            call.sequence < output.sequence
                && call.at()? <= output.at()?
                && call.payload()["namespace"] == "collaboration"
                && call.payload()["name"] == name,
        )?;
        let args = object(text(&call.payload()["arguments"])?.as_bytes())?;
        let body = output.payload()["output"].as_str().ok_or_else(invalid)?;
        let result = if name == "followup_task" {
            require(body.is_empty())?;
            Value::Null
        } else {
            object(body.as_bytes())?
        };
        Ok((call, output, args, result))
    }
    fn sample(
        &self,
        id: &str,
        child: &str,
    ) -> Result<(&Record, &Record, &'static str), StateError> {
        let (call, output, args, result) = self.pair(id, "list_agents")?;
        require(covered(&args, child)? && result.as_object().is_some_and(|o| o.len() == 1))?;
        let agents = result["agents"].as_array().ok_or_else(invalid)?;
        let selected: Vec<_> = agents.iter().filter(|a| a["agent_name"] == child).collect();
        require(selected.len() == 1 && selected[0].as_object().is_some_and(|o| o.len() == 2))?;
        let value = &selected[0]["agent_status"];
        let status = if value == "running" {
            "RUNNING"
        } else if value == "interrupted" {
            "FAILED"
        } else if value
            .as_object()
            .is_some_and(|o| o.len() == 1 && o.get("completed").is_some_and(Value::is_string))
        {
            "COMPLETED"
        } else {
            return Err(invalid());
        };
        Ok((call, output, status))
    }
}
fn raw_records(proof: &Value, parent: &str) -> Result<Records, StateError> {
    require(
        proof.get("native_source_path").is_some() != proof.get("native_source_paths").is_some(),
    )?;
    let paths = if let Some(paths) = proof.get("native_source_paths") {
        paths.as_array().ok_or_else(invalid)?.clone()
    } else {
        vec![proof["native_source_path"].clone()]
    };
    require(!paths.is_empty())?;
    let mut seen = BTreeSet::new();
    let mut records = Records {
        calls: BTreeMap::new(),
        outputs: BTreeMap::new(),
        metadata: Vec::new(),
        session_metadata: Vec::new(),
        child_links: Vec::new(),
    };
    let mut sequence = 0;
    let mut previous_time = None;
    for source in paths {
        let path = Path::new(text(&source)?);
        regular(path)?;
        require(seen.insert(fs::canonicalize(path).map_err(|_| invalid())?))?;
        let mut metas = Vec::new();
        let mut stream = BufReader::new(fs::File::open(path).map_err(|_| invalid())?);
        let mut raw = Vec::new();
        let mut line = 0;
        loop {
            raw.clear();
            if stream.read_until(b'\n', &mut raw).map_err(|_| invalid())? == 0 {
                break;
            }
            line += 1;
            sequence += 1;
            while matches!(raw.last(), Some(b'\r' | b'\n')) {
                raw.pop();
            }
            let value = object(&raw)?;
            let payload = &value["payload"];
            require(payload.is_object())?;
            let hash = sha256_hex(&raw);
            let location = json!({"path":source,"line":line,"sha256":hash});
            if value["type"] == "session_meta" {
                metas.push(payload["id"].clone());
                records.metadata.push(location.clone());
                records.session_metadata.push(payload.clone());
            }
            if value["type"] == "event_msg"
                && payload["type"] == "item_completed"
                && payload["item"]["type"] == "SubAgentActivity"
            {
                records.child_links.push(Record {
                    sequence,
                    value,
                    hash,
                    location,
                });
                continue;
            }
            if value["type"] != "response_item"
                || !matches!(
                    payload["type"].as_str(),
                    Some("function_call" | "function_call_output")
                )
            {
                continue;
            }
            if payload.get("call_id").is_none()
                && payload["namespace"] == "codex_app"
                && payload["name"] == "send_message_to_thread"
            {
                continue;
            }
            let id = text(&payload["call_id"])?.to_owned();
            let at = timestamp(&value["timestamp"])?;
            require(previous_time.is_none_or(|before| at >= before))?;
            previous_time = Some(at);
            let map = if payload["type"] == "function_call" {
                &mut records.calls
            } else {
                &mut records.outputs
            };
            map.entry(id).or_default().push(Record {
                sequence,
                value,
                hash,
                location,
            });
        }
        require(metas == vec![Value::String(parent.into())])?;
    }
    Ok(records)
}
fn frozen(proof: &Value, prefix: &str, call: &Record, output: &Record) -> Result<(), StateError> {
    for (part, row) in [("call", call), ("output", output)] {
        require(
            proof[format!("{prefix}_{part}_sha256")] == row.hash
                && proof[format!(
                    "{prefix}_{}_timestamp",
                    if part == "call" { "query" } else { "output" }
                )] == row.value["timestamp"],
        )?;
        if proof.get("native_source_paths").is_some() {
            require(proof["record_sources"][format!("{prefix}_{part}")] == row.location)?;
        }
    }
    Ok(())
}

/// Re-read exact parent records and return only status/identity/hash metadata.
/// The same observation serves resume (RUNNING) and authenticated close (terminal).
pub(super) fn observe(
    reference: &EvidenceReference,
    binding: Binding<'_>,
    observed_at: &str,
) -> Result<Observation, StateError> {
    validate_evidence_reference(reference)?;
    let path = Path::new(&reference.path);
    let proof = hashed_object(path, &json!(reference.sha256))?;
    require(
        proof["schema_version"] == "slk.subagent-overwatcher-proof/v1"
            && proof["run_id"] == binding.run_id
            && proof["role_instance_id"] == binding.role_instance_id
            && proof["method_version"] == binding.method_version
            && &proof["native_address"] == binding.native_address
            && proof["canonical_task_id"] == binding.canonical_task_id
            && proof["native_execution_id"] == binding.execution_id
            && proof["agent_status"] == "RUNNING",
    )?;
    let request = hashed_object(
        &path.with_file_name("subagent-overwatcher-request.json"),
        &proof["request_sha256"],
    )?;
    require(request["schema_version"] == "slk.subagent-overwatcher-request/v1")?;
    for (key, value) in request.as_object().ok_or_else(invalid)? {
        if key != "schema_version" {
            require(proof.get(key) == Some(value))?;
        }
    }
    for key in [
        "run_id",
        "role_instance_id",
        "method_version",
        "native_address",
        "native_execution_id",
        "endpoint_ref",
    ] {
        require(request.get(key).is_some() && request[key] == proof[key])?;
    }
    for key in [
        "native_source_path",
        "native_source_paths",
        "spawn_call_id",
        "previous_native_execution_id",
        "pre_activation_sample_call_id",
        "child_source_path",
    ] {
        require(request.get(key) == proof.get(key))?;
    }
    let (kind, activation_id) = execution(binding.execution_id)?;
    let followup = kind == "codex-subagent-followup";
    let spawn_id = if followup {
        text(&proof["spawn_call_id"])?
    } else {
        activation_id
    };
    execution(&format!("codex-subagent-spawn:{spawn_id}"))?;
    text(&proof["endpoint_ref"])?;
    let child = text(&proof["native_address"]["agent_id"])?;
    let parent = text(&proof["native_address"]["parent"]["session_id"])?;
    require(
        child_path(child)
            && binding.canonical_task_id == format!("codex-subagent-spawn-{spawn_id}")
            && proof["native_task_id"]
                == format!("codex-subagent:{parent}:{activation_id}:{child}"),
    )?;
    let start = hashed_object(
        &path.with_file_name("started.json"),
        &proof["started_sha256"],
    )?;
    serde_json::from_value::<super::NativeStartReceipt>(start.clone()).map_err(|_| invalid())?;
    timestamp(&start["observed_at"])?;
    require(
        start["schema_version"] == "slk.native-start/v2"
            && start["status"] == "STARTED"
            && start["adapter"] == "codex-overwatcher"
            && start["run_id"] == binding.run_id
            && start["cell_id"] == "RUN-OVERWATCH"
            && start["message_id"] == format!("{kind}-{activation_id}")
            && start["request_sha256"] == proof["request_sha256"]
            && start["native_request_sha256"]
                == proof[if followup {
                    "activation_call_sha256"
                } else {
                    "spawn_call_sha256"
                }]
            && start["native_task"]["kind"] == "codex-subagent"
            && start["native_task"]["id"] == proof["native_task_id"]
            && start["native_task"]["status"] == "RUNNING",
    )?;
    let records = raw_records(&proof, parent)?;
    if proof.get("native_source_paths").is_some() {
        require(proof["source_metadata"] == json!(records.metadata))?;
    }
    let (spawn, spawned, args, result) = records.pair(spawn_id, "spawn_agent")?;
    require(
        args["task_name"] == child.rsplit('/').next().unwrap()
            && result == json!({"task_name":child}),
    )?;
    frozen(&proof, "spawn", spawn, spawned)?;
    let (activation, activated) = if followup {
        let (a, b, args, _) = records.pair(activation_id, "followup_task")?;
        require(target(&args, child)?)?;
        frozen(&proof, "activation", a, b)?;
        (a, b)
    } else {
        (spawn, spawned)
    };
    let mut previous_status = None;
    let mut previous_execution_id = None;
    let mut previous_sequence = spawn.sequence;
    if followup {
        let previous = text(&proof["previous_native_execution_id"])?;
        let (previous_kind, previous_id) = execution(previous)?;
        let (a, b, args, _) = records.pair(
            previous_id,
            if previous_kind == "codex-subagent-spawn" {
                "spawn_agent"
            } else {
                "followup_task"
            },
        )?;
        require(
            (previous_kind == "codex-subagent-spawn" && previous_id == spawn_id)
                || (previous_kind == "codex-subagent-followup"
                    && a.sequence > spawned.sequence
                    && target(&args, child)?),
        )?;
        require(b.sequence < activation.sequence && b.at()? <= activation.at()?)?;
        frozen(&proof, "previous_activation", a, b)?;
        previous_sequence = a.sequence;
        let pre_id = text(&proof["pre_activation_sample_call_id"])?;
        let (pre, pre_output, status) = records.sample(pre_id, child)?;
        require(
            matches!(status, "COMPLETED" | "FAILED")
                && pre.sequence > b.sequence
                && pre_output.sequence < activation.sequence
                && pre.at()? >= b.at()?
                && activation.at()? >= pre_output.at()?
                && activation.at()? - pre.at()? <= time::Duration::seconds(300),
        )?;
        // Optional on historical proofs. New self-contained resume requires it.
        if let Some(declared) = proof.get("pre_activation_agent_status") {
            require(declared == status)?;
            previous_status = Some(status);
        }
        frozen(&proof, "pre_activation_sample", pre, pre_output)?;
        previous_execution_id = Some(previous.to_owned());
        for calls in records.calls.values() {
            for call in calls {
                if call.sequence > pre.sequence
                    && call.sequence < activation.sequence
                    && call.payload()["name"] == "list_agents"
                {
                    require(call.payload()["namespace"] == "collaboration")?;
                    let args = object(text(&call.payload()["arguments"])?.as_bytes())?;
                    require(!covered(&args, child)?)?;
                }
            }
        }
    }
    let mut latest = None;
    for (id, calls) in &records.calls {
        for call in calls {
            let name = call.payload()["name"].as_str().unwrap_or("");
            if name == "followup_task" && call.sequence > previous_sequence && id != activation_id {
                require(call.payload()["namespace"] == "collaboration")?;
                let args = object(text(&call.payload()["arguments"])?.as_bytes())?;
                require(!target(&args, child)?)?;
            }
            if name == "spawn_agent" && id != spawn_id && call.sequence > spawn.sequence {
                if let Ok((_, _, _, result)) = records.pair(id, "spawn_agent") {
                    require(result != json!({"task_name":child}))?;
                }
            }
            if name == "list_agents" && call.sequence > activated.sequence {
                let scope = (|| {
                    require(call.payload()["namespace"] == "collaboration")?;
                    covered(
                        &object(text(&call.payload()["arguments"])?.as_bytes())?,
                        child,
                    )
                })();
                // Unknown query scope is a candidate, never proof of absence.
                // A later valid covering query can supersede it.
                if scope.unwrap_or(true) && latest.is_none_or(|(_, seq)| call.sequence > seq) {
                    latest = Some((id.as_str(), call.sequence));
                }
            }
        }
    }
    let (original, original_output, original_status) =
        records.sample(text(&proof["sample_call_id"])?, child)?;
    require(
        original_status == "RUNNING"
            && original.sequence > activated.sequence
            && original.at()? >= activated.at()?,
    )?;
    frozen(&proof, "sample", original, original_output)?;
    require(timestamp(&proof["checked_at"])? >= original_output.at()?)?;
    let (latest_id, _) = latest.ok_or_else(invalid)?;
    let (sample, output, status) = records.sample(latest_id, child)?;
    let mut current_sample = (sample, output);
    let child_records;
    if proof.get("child_source_path").is_some() {
        let links: Vec<_> = records
            .child_links
            .iter()
            .filter(|r| r.payload()["item"]["id"] == spawn_id)
            .collect();
        require(links.len() == 1)?;
        let link = links[0];
        let item = &link.payload()["item"];
        require(
            link.hash == proof["child_link_sha256"]
                && link.sequence > spawn.sequence
                && link.at()? >= spawn.at()?
                && link.payload()["thread_id"] == parent
                && item["kind"] == "started"
                && item["agent_path"] == child
                && item["agent_thread_id"] == proof["child_session_id"],
        )?;
        if proof.get("native_source_paths").is_some() {
            require(proof["record_sources"]["child_link"] == link.location)?;
        }
        if status == "RUNNING" {
            let child_id = text(&proof["child_session_id"])?;
            require(uuid::Uuid::parse_str(child_id).is_ok_and(|id| id.to_string() == child_id))?;
            child_records = raw_records(
                &json!({"native_source_path":proof["child_source_path"]}),
                child_id,
            )?;
            require(
                child_records.metadata.len() == 1
                    && child_records.metadata[0]["sha256"] == proof["child_meta_sha256"],
            )?;
            let meta = &child_records.session_metadata[0];
            let spawned = &meta["source"]["subagent"]["thread_spawn"];
            require(
                meta["parent_thread_id"] == parent
                    && meta["agent_path"] == child
                    && spawned["parent_thread_id"] == parent
                    && spawned["agent_path"] == child
                    && spawned["depth"].as_u64() == Some((child.matches('/').count() - 1) as u64),
            )?;
            let mut latest_child = None;
            for (id, calls) in &child_records.calls {
                for call in calls {
                    if call.payload()["name"] == "list_agents" {
                        require(call.payload()["namespace"] == "collaboration")?;
                        let args = object(text(&call.payload()["arguments"])?.as_bytes())?;
                        if covered(&args, child)?
                            && latest_child.is_none_or(|(_, seq)| call.sequence > seq)
                        {
                            latest_child = Some((id.as_str(), call.sequence));
                        }
                    }
                }
            }
            let (child_query, child_output, child_status) =
                child_records.sample(latest_child.ok_or_else(invalid)?.0, child)?;
            require(child_status == "RUNNING" && child_query.at()? >= activated.at()?)?;
            if child_query.at()? > sample.at()? {
                current_sample = (child_query, child_output);
            }
        }
    }
    let (sample, output) = current_sample;
    let now = OffsetDateTime::now_utc();
    let observed = OffsetDateTime::parse(observed_at, &Rfc3339).map_err(|_| invalid())?;
    // Match the existing adapter's five-minute native observation freshness.
    require(
        sample.at()? >= activated.at()?
            && output.at()? <= observed
            && observed <= now
            && now - sample.at()? <= time::Duration::seconds(300)
            && observed - sample.at()? <= time::Duration::seconds(300),
    )?;
    Ok(Observation {
        status,
        previous_status,
        previous_execution_id,
        metadata: json!({"agent_status":status,"pre_activation_agent_status":previous_status,
            "native_execution_id":binding.execution_id,"sample_call_id":sample.payload()["call_id"],
            "sample_call_sha256":sample.hash,"sample_output_sha256":output.hash,
            "sample_query_timestamp":sample.value["timestamp"],"sample_output_timestamp":output.value["timestamp"],
            "record_sources":{"sample_call":sample.location,"sample_output":output.location}}),
    })
}
