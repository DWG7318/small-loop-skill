# SLK Cross-Agent Transport

`slk-transport 4.3.0` carries one closed SLK delivery into one exact native Agent endpoint, writes native start evidence before any terminal result, and can recover only the explicitly allowed identity. Worker completion inspection binds run/CELL/attempt to the exact candidate and derived handoff message; a D1 event for another candidate/message cannot prove delivery. Rework `acceptance_criteria` is normalized to Checker `d1_criteria`. Active-writer delivery reads before any resume, stale Codex executable paths are rebound with evidence, and a resumed DSH starts OCRV through a detached headless Checker host. It implements transport only and does not decide D1.

## Role edges

The normal direct edges remain `Supervisor ↔ Checker` and `Checker ↔ Worker`. `Supervisor → Worker` is rejected except for a `D1_REWORK_DIRECTIVE` immediately following the current CELL's formal `D1_FAILED` and Checker-owned `D1_FAILURE_ESCALATION`; it is not a general dispatch or recovery edge. An optional Overwatcher may inspect immutable evidence and request one exact replay, but it is not a receiver role, relay, TOKEN holder, resident service, acknowledgement turn, or database queue; a Run without it uses the same direct edges.

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

DSH receives one canonical `slk.transport-task/v1` file containing the exact endpoint, envelope, result contract and absolute result path. The file is created once and named by an independently supplied SHA-256; mutation, extra fields, an unreadable path or hash drift fails closed. OCRV receives the installed closed `slk.ocrv-d1-request/v1` field set; OCRV itself creates the `review_invocation_id` returned in the result, while transport records its separate start invocation. Both adapters write `started.json` immediately after native process creation and before reading any terminal result. The public JSON contracts are in [`../contracts`](../contracts).

`message_id` is a canonical UUID. The payload hash is SHA-256 over canonical JSON. Run, receiving role, role instance, and endpoint version have to match before dispatch.

`D1_FAILURE_ESCALATION` is a closed Checker→Supervisor payload binding the failure event, candidate hash, round, CELL goal, acceptance criteria, findings, reproduction, expected result, and evidence. `D1_REWORK_DIRECTIVE` is a closed Supervisor→same-Worker payload binding those failure facts plus one root-cause hypothesis, one minimal experiment, the minimal repair scope, and regression target. `WORKER_COMPLETION_RECOVERY` is a closed Supervisor→same-Checker payload binding the exact source attempt, runtime snapshot/revisions, role credential paths, commands, and occurrence time. Missing, extra, empty, mismatched, or out-of-order fields fail closed; D1 INCOMPLETE cannot use the rework payloads.

## Exact adapter addresses

- Codex Supervisor: `command`, exact `thread_id`, absolute `cwd`, `startup_timeout_seconds`, `turn_timeout_seconds`. Transport reads the thread before resume; an active writer is not activation evidence and is recorded without a conflicting resume. If an absolute Codex Desktop executable disappeared after update, only the current PATH-resolved `codex.exe` replaces the process command and `command-rebind.json` records both paths; endpoint role/session identity remains immutable.
- DSH Worker: `command`, Run-scoped deterministic `instance_id` (maximum 64 characters), recorded `session_id` or `null`, `runtime_root`, absolute `cwd`, `timeout_seconds`, and expected Git repository/worktree identity. A bounded preflight rejects wrong root/common-dir, missing writable boundary or identity drift before work starts. The Worker result contract includes `candidate_repository`; only a legacy omission may fall back to the authenticated immutable endpoint `cwd`.
- OCRV Checker: `command`, `runtime_root`, `timeout_seconds`. `CELL_DISPATCH` creates the exact Worker delivery; `CANDIDATE_READY` produces a closed D1 result with Run, CELL, fresh review invocation, provider, model, session, verdict, and exit identity; `WORKER_COMPLETION_RECOVERY` starts the same registered command with the narrow recovery flag and deterministic invocation identity.

Addresses are selected by identity, never by conversation title. Secrets stay in the native runtime configuration and do not belong in endpoint, envelope, result, or evidence files.

## Commands

```text
python path\to\slk-transport.pyz validate --endpoint ENDPOINT.json --envelope ENVELOPE.json
python path\to\slk-transport.pyz send --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
python path\to\slk-transport.pyz inspect --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
python path\to\slk-transport.pyz retry-exact --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
python path\to\slk-transport.pyz recover-active-writer --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
python path\to\slk-transport.pyz inspect-overwatcher-cadence --runtime-projection RUN.json --observed-at RFC3339
python path\to\slk-transport.pyz drill-verify --evidence-root EVIDENCE_ROOT
```

`validate` checks closed identities without delivery. `send` starts one short-lived native delivery job and returns only on independently observed `started.json`, terminal failure after start, or bounded startup failure. `inspect` reports immutable evidence without creating work. `retry-exact` is limited to an inactive target and the same identity once. `recover-active-writer` is limited to an exact Checker→Supervisor handoff whose immutable attempt failed with `CODEX_ACTIVE_WRITER`; it rereads the same canonical task and active turn, creates one new logical message, uses native steer with `expectedTurnId`, and persists a distinct immutable recovery/start receipt. It never schedules a later process, waits for the turn to end, promises a number of seconds, or manufactures self-wake. Changed, unsupported or exhausted recovery returns `SUPERVISOR_DECISION_REQUIRED`, after which only a real Owner/Main activation can continue. `job` is the internal foreground form used by `send`.

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

The common files are `endpoint.json`, `envelope.json`, `accepted.json`, immutable task/request evidence with hashes, independently written `started.json`, `completed.json` or `failed.json`, plus adapter-native stdout, stderr, result and identity evidence when applicable. Active-writer recovery additionally records the source message, exact turn, new message and native receipt. Worker continuation keeps bulk stdout/stderr locally and sends Checker only essential receipts plus `checker-evidence-index.json`, whose entries bind each retained file's path, byte length and SHA-256. Stable continuation event IDs reuse the first request's exact stored bytes and `occurred_at`; a semantic difference still conflicts. Job launcher logs are under `<attempt-root>/.jobs/`.

`accepted.json`, a database row, successful launcher exit, terminal result, or visible conversation does not prove delivery. A matching early `started.json` proves that the exact native target began this message. The sender retains TOKEN until `slk-state commit-delivery-start` verifies that evidence and atomically advances TOKEN, event and runtime snapshot; the returned `runtime_revision` is checked and propagated. After commit, the sender ends its activity instead of watching the receiver. If a DSH terminal result exists while its Worker-owned D0/candidate facts and Checker start are absent, `inspect-worker-completion` allows one cadence measured from the trustworthy terminal evidence time, then keeps every unresolved cycle anomalous. Supervisor may only deliver `WORKER_COMPLETION_RECOVERY` to the exact Checker endpoint. Its early `started.json` states authentication pending and unauthorized; the native OCRV companion strips inherited secrets, and internal `checker-recover-worker` must authenticate that Checker against the current runtime revision before the exact DSH instance/session can resume. `continue-worker` re-injects and verifies both recorded DSH instance and Session identities inside that Worker process, accepts only strict UTF-8 or UTF-16LE DPAPI output with at most one terminal NUL, records idempotent Worker facts, sends minimal `CANDIDATE_READY`, verifies exact headless Checker start outside the Worker job, reads a fresh runtime revision, and commits the handoff. State-command process exit, JSON parsing and business status remain three separate facts; valid nonzero JSON is not discarded, while malformed/non-object output fails closed. The deterministic recovery invocation and removed public direct-resume command make this a Checker-authorized suffix, not a scheduler or CELL rerun.

## Retry and session rebound

An inactive-target exact retry reuses the same endpoint, envelope, `message_id`, endpoint version, TOKEN number, Run/CELL/attempt scope, and payload. Recovery evidence has one deterministic `recovery/exact-1` identity. Existing start proof stops recovery; changed content/identity or any second retry is rejected. The active-Supervisor exception does the opposite deliberately: it never replays the old envelope, and accepts only the new message bound to the exact active turn.

When a native task or session is replaced, register a higher endpoint version, mark the old endpoint `retired`, and create the next handoff for the new endpoint identity. A retired endpoint rejects delivery. Session rebound is an identity change, not an excuse to guess by title or reuse an unverified session.

If an adapter explicitly fails or lacks start evidence, the sender keeps TOKEN and follows the existing SLK communication-recovery route; it does not claim the receiver or D2 started. An active writer follows only the narrow rule above. Recovery does not create a receipt-only turn, auto-upgrade a model, activate BoM, or move D0/D1/D2, exemption or planning authority into transport.

On Windows, Codex App Server, DSH, OCRV, detached transport jobs, and drill/recovery helper processes use the shared hidden-start flags by default. A bounded timeout terminates the whole wrapper process tree so inherited pipes cannot hang after the outer `.cmd` exits. No helper may flash a PowerShell/console window; a visible interactive window is an explicit Owner choice, not a recovery fallback.

## Acceptance

The accepted live two-Run evidence and immutable artifact hash are recorded in [`SLK-TRANSPORT-LIVE-ACCEPTANCE.md`](SLK-TRANSPORT-LIVE-ACCEPTANCE.md).
