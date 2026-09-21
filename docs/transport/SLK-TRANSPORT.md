# SLK Cross-Agent Transport

`slk-transport 4.0.0` carries one closed SLK handoff into one exact native Agent endpoint. It implements transport only: it does not decide CELL scope, D0/D1/D2, PASS/FAIL, rework, exemptions, plan changes, TOKEN ownership beyond a proven handoff, or future BI state.

## Role edges

The accepted edges are `Supervisor → Checker → Worker → Checker → Supervisor`. The transport adds no role, relay Agent, resident service, acknowledgement-only turn, peer watcher, or database queue.

## Closed contracts

An endpoint uses `slk.transport-endpoint/v1` and exactly these fields:

```text
schema_version, run_id, role, role_instance_id, agent_runtime,
adapter, host_id, endpoint_version, state, address
```

An envelope uses `slk.transport-envelope/v1` and exactly these fields:

```text
schema_version, message_id, token_sequence, run_id, go_id, cell_id,
sender_role, sender_role_instance_id, receiver_role,
receiver_role_instance_id, receiver_endpoint_version,
payload_type, payload_sha256, payload
```

A result uses `slk.transport-result/v1` and exactly these fields:

```text
schema_version, message_id, run_id, adapter, status,
native_identity, error_code, evidence
```

`message_id` is a canonical UUID. The payload hash is SHA-256 over canonical JSON. Run, receiving role, role instance, and endpoint version have to match before dispatch.

## Exact adapter addresses

- Codex Supervisor: `command`, exact `thread_id`, absolute `cwd`, `startup_timeout_seconds`, `turn_timeout_seconds`. The adapter resumes that thread ID only when it is idle, starts one native turn, and records the exact thread and turn IDs; an active writer is a delivery failure, not activation evidence.
- DSH Worker: `command`, Run-scoped `instance_id`, recorded `session_id` or `null` for the first activation, `runtime_root`, absolute `cwd`, `timeout_seconds`. The Worker returns one closed `slk.worker-result/v1`; a successful process exit alone is not completion.
- OCRV Checker: `command`, `runtime_root`, `timeout_seconds`. `CELL_DISPATCH` creates the exact Worker handoff; `CANDIDATE_READY` produces a closed D1 result with Run, CELL, review invocation, provider, model, session, verdict, and exit identity.

Addresses are selected by identity, never by conversation title. Secrets stay in the native runtime configuration and do not belong in endpoint, envelope, result, or evidence files.

## Commands

```text
python path\to\slk-transport.pyz validate --endpoint ENDPOINT.json --envelope ENVELOPE.json
python path\to\slk-transport.pyz send --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
python path\to\slk-transport.pyz drill-verify --evidence-root EVIDENCE_ROOT
```

`validate` checks closed identities without delivery. `send` starts one short-lived native delivery job and returns after it observes `started.json`, a terminal result, or a bounded startup failure. `job` is the internal foreground form used by `send`.

Exit codes are:

- `0`: validated, native start observed, completed, or drill verified;
- `2`: rejected contract, adapter address, input, or drill evidence;
- `3`: terminal delivery failure;
- `4`: native start was not observed within the startup bound.

## Evidence and responsibility

Each attempt is immutable under:

```text
<attempt-root>/<run_id>/<message_id>/
```

The common files are `endpoint.json`, `envelope.json`, `accepted.json`, `started.json`, `completed.json` or `failed.json`, plus adapter-native stdout, stderr, request, result, and identity evidence when applicable. Job launcher logs are under `<attempt-root>/.jobs/`.

`accepted.json` or a database record does not prove delivery. A matching `started.json` proves that the exact native target actually began this message, not merely that a launcher existed or exited. Until that proof exists, the sender retains the same TOKEN and responsibility. After proof, the sender ends its activity instead of watching the receiver.

## Retry and session rebound

An exact retry reuses the same endpoint, envelope, `message_id`, endpoint version, TOKEN number, and payload. The immutable terminal result is returned again; different content under the same identity is rejected as a collision.

When a native task or session is replaced, register a higher endpoint version, mark the old endpoint `retired`, and create the next handoff for the new endpoint identity. A retired endpoint rejects delivery. Session rebound is an identity change, not an excuse to guess by title or reuse an unverified session.

If an adapter explicitly fails, reports an active writer, or lacks start evidence, the sender keeps the TOKEN and follows the existing SLK communication-recovery route; it does not claim the receiver or D2 started. Recovery does not create a receipt-only turn and does not move D0, D1, D2, exemption, or planning authority into the transport.

## Acceptance

The accepted live two-Run evidence and immutable artifact hash are recorded in [`SLK-TRANSPORT-LIVE-ACCEPTANCE.md`](SLK-TRANSPORT-LIVE-ACCEPTANCE.md).
