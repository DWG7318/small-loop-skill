# SLK Cross-Agent Transport

`slk-transport 4.3.6` carries one closed delivery into an exact native Agent endpoint, verifies native activity read-only and implements deterministic readiness/OCRV preflight without moving D1 authority. `preflight-run` verifies the concrete Codex Supervisor, DSH Worker and OCRV Checker bindings, workspace/capacity, installed activity capabilities and explicit Owner decisions. DSH stages the immutable Worker candidate; an independent headless OCRV host starts and records Checker D1.

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

DSH receives one canonical `slk.transport-task/v1` file containing the exact endpoint, envelope, result contract and absolute result path. The contract is a descriptor, not an output wrapper: a completed Worker writes exactly the seven-field flat `slk.worker-result/v1` instance, while a non-completed Worker writes exactly the eight-field flat instance with one blocker. The file is created once and named by an independently supplied SHA-256; mutation, nesting, extra fields, an unreadable path or hash drift fails closed. OCRV receives closed `slk.ocrv-d1-request/v2`: exact scope plus capacity. It materializes a compact background and runs `review --preview`; a segment starts only when preview-selected paths equal its manifest and all remaining candidate paths are excluded. Segments are sequential, stop on a blocking finding, and form one compact D1 aggregate without reinjecting complete segment results. Public contracts are in [`../contracts`](../contracts).

`message_id` is a canonical UUID. The payload hash is SHA-256 over canonical JSON. Run, receiving role, role instance, and endpoint version have to match before dispatch.

`D1_FAILURE_ESCALATION` is a closed Checker→Supervisor payload binding the failure event, candidate hash, round, CELL goal, acceptance criteria, findings, reproduction, expected result, and evidence. `D1_REWORK_DIRECTIVE` is a closed Supervisor→same-Worker payload binding those failure facts plus one root-cause hypothesis, one minimal experiment, the minimal repair scope, and regression target. `WORKER_COMPLETION_RECOVERY` is a closed Supervisor→same-Checker payload binding the exact source attempt, runtime snapshot/revisions, role credential paths, commands, and occurrence time. Missing, extra, empty, mismatched, or out-of-order fields fail closed; D1 INCOMPLETE cannot use the rework payloads.

## Exact adapter addresses

- Codex Supervisor: `command`, exact `thread_id`, absolute `cwd`, `startup_timeout_seconds`, `turn_timeout_seconds`. Transport reads the thread before resume; an active writer is not activation evidence and is recorded without a conflicting resume. If an absolute Codex Desktop executable disappeared after update, only the current PATH-resolved `codex.exe` replaces the process command and `command-rebind.json` records both paths; endpoint role/session identity remains immutable.
- DSH Worker: `command`, Run-scoped deterministic `instance_id` (maximum 64 characters), recorded `session_id` or `null`, `runtime_root`, absolute `cwd`, `timeout_seconds`, and expected Git repository identity. A bounded preflight requires an independent writable clone/simple layout whose Git common-dir, objects and refs remain inside the Worker sandbox; an external linked-worktree common-dir is rejected before native start. The closed result is either `completed` with candidate/next payload, or `incomplete|blocked|execution_failure|timed_out` with no candidate and one exact blocker.
- OCRV Checker: `command`, `runtime_root`, `timeout_seconds`. `CELL_DISPATCH` creates the exact Worker delivery; `CANDIDATE_READY` first performs executable preview/capacity preflight, then persists each truly scoped segment request/preflight/result/session/hash and produces one compact closed D1 result. Scope mismatch, oversize, preview failure or timeout returns `OCRV_REVIEW_INCOMPLETE`; `WORKER_COMPLETION_RECOVERY` keeps its narrow deterministic identity.

Addresses are selected by identity, never by conversation title. Secrets stay in the native runtime configuration and do not belong in endpoint, envelope, result, or evidence files.

## Commands

```text
slk-transport validate --endpoint ENDPOINT.json --envelope ENVELOPE.json
slk-transport send --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
slk-transport inspect --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
slk-transport inspect-native-activity --started STARTED.json [--completed COMPLETED.json] [--failed FAILED.json]
slk-transport retry-exact --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
slk-transport recover-active-writer --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
slk-transport prepare-desktop-current-turn --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
slk-transport complete-desktop-current-turn --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT --host-receipt HOST-RECEIPT.json
slk-transport checker-escalate-d1 --request CHECKER-POST-D1.json --sha256 REQUEST-SHA256 [--host-receipt HOST-RECEIPT.json]
slk-transport prepare-invalid-result-recovery --source-attempt SOURCE-ATTEMPT --checker-endpoint CHECKER.json --runtime-projection RUN.json --supervisor-role-instance-id SUPERVISOR-ID --plan-revision PLAN --runtime-revision RUNTIME --token-sequence TOKEN --worker-credential WORKER-CREDENTIAL --checker-credential CHECKER-CREDENTIAL --state-command STATE-COMMAND --transport-command TRANSPORT-COMMAND --occurred-at RFC3339 --output RECOVERY-ENVELOPE.json
slk-transport recover-staged-checker-commit --continuation CONTINUATION.json --outcome STAGED-RESULT.json --failed-request FAILED-COMMIT.json
slk-transport consume-staged-checker-terminal --request ORIGINAL-CHECKER-RECOVERY.json --sha256 ORIGINAL-REQUEST-SHA256
slk-transport inspect-worker-completion --source-attempt ATTEMPT --runtime-projection RUN.json --observed-at RFC3339 --cadence-seconds SECONDS --output INSPECTION.json
slk-transport inspect-overwatcher-cadence --runtime-projection RUN.json --observed-at RFC3339
slk-transport drill-verify --evidence-root EVIDENCE_ROOT
```

The managed install places `slk-transport.cmd` beside the hash-bound `slk-transport.pyz`; that launcher is the standard command. A stale user-site Python console script is not an accepted entrance, while explicit `python <managed-slk-transport.pyz>` remains the diagnostic fallback.

`validate` checks closed identities without delivery. `send` returns only on independently observed `slk.native-start/v2`, terminal failure after start, or bounded startup failure. `inspect-native-activity` queries the exact current process/native task without wake or model call; missing, stale, mismatched or permission-blocked evidence is `UNKNOWN`. OCRV segments publish their own start/activity, so an exited first-segment PID cannot mask a live later segment. `inspect` reports immutable evidence without creating work; `inspect-worker-completion` writes one exact observation and rejects conflicting reuse. `retry-exact` is limited to an inactive target and the same identity once. `recover-active-writer` handles the bounded external App Server route. If that exact Checker→Supervisor attempt and retry end as `CODEX_ACTIVE_WRITER_UNRESOLVED`, `prepare-desktop-current-turn` freezes a new identity-bound prompt under the original attempt; the current Codex Desktop host performs read/send/read and records the exact platform item, then `complete-desktop-current-turn` validates the same active target turn and writes separate recovery/start evidence. Visible text, send success, a changed turn or a self-authored receipt never qualifies. Changed, unsupported or unproved recovery returns `SUPERVISOR_DECISION_REQUIRED`, after which only a real Owner/Main activation can continue. `job` is the internal foreground form used by `send`.

`checker-escalate-d1` is the FAIL-only suffix behind OCRV's headless `--slk-post-d1` entry. It revalidates the unchanged Checker-owned D1 failure and immutable candidate, uses the sealed Checker credential only inside the Tool, and reuses `send → retry-exact → Desktop current-turn bridge → commit-delivery-start`. TOKEN remains at Checker until the registered Supervisor's exact native start is proved. It does not rerun review, decide D1, dispatch Worker, or handle PASS/INCOMPLETE. A preserved D1 record without `candidate_sha256` is accepted only when its `candidate_message_id` resolves to exactly one same-scope/attempt Worker-authored `CANDIDATE_SUBMITTED` and exactly one matching `TRANSPORT_STARTED`; the candidate object is canonically re-hashed and any absence, duplication or drift is rejected.

`prepare-invalid-result-recovery` is a read-only Run preflight that writes one closed Supervisor→original-Checker recovery envelope; it does not decrypt credentials, start a model, resume a Session, create supplement evidence or mutate central state. It accepts only a preserved DSH `DSH_RESULT_INVALID` attempt whose immutable legacy **result descriptor**, matching `slk.native-start/v2`, endpoint, envelope, original Session, invalid raw result, candidate repository/commit/parent/paths and Worker-held runtime/TOKEN all match. This is distinct from the separate 4.3.4 flat-native-start compatibility path, which cannot qualify for a result supplement. The ordinary `send` command then delivers that envelope to the registered Checker. Checker uses the sealed Worker credential internally to resume the same DSH Session once with one physical-line, result-only instruction, and accepts only the frozen flat result fields before reusing the existing authenticated Checker recovery. Root, Supervisor and the Tool never transform the old nested object or author Worker engineering facts; any drift or second supplement fails closed.

After the Worker-owned `WORK_STARTED`, `D0_COMPLETED`, and `CANDIDATE_SUBMITTED` writes, the continuation authenticates the same sealed Worker again and stages the resulting current runtime revision. If an older 4.3.6 Tool instead preserved a valid native Checker start but its immutable commit request failed only because it carried the pre-event revision, `recover-staged-checker-commit` is the single commit-only repair. It requires the exact continuation, staged result, original failed request, existing endpoint/envelope and `slk.native-start/v2`; authenticates the original Worker internally; preserves the failed request; writes a separate immutable request under `commit-only-recovery`; changes only `expected_runtime_revision`; and invokes `commit-delivery-start` once. It never sends another candidate, restarts Worker/OCRV, decides D1 or exposes the credential. A later competing state write remains a revision conflict rather than being silently retried.

After that commit moves TOKEN to Checker, the external standard command is `slk-transport consume-staged-checker-terminal --request ORIGINAL-CHECKER-RECOVERY.json --sha256 ORIGINAL-REQUEST-SHA256`. It validates the commit-only chain first, then starts the installed OCRV companion headlessly with the frozen original Checker identity; Root neither supplies nor receives the Checker credential and must not set `SLK_OCRV_RECOVERY_*` itself. The companion internally runs the unchanged `checker-recover-worker` command. That path recognizes the hash-bound commit-only result, skips Worker continuation, delivery send and OCRV activation, and feeds the already completed native attempt into the existing Checker-owned D1 recorder. Only that original Checker path may write `D1_STARTED` and the native PASS/FAIL/INCOMPLETE verdict; Root must not invoke a second review or author D1.

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

Here `--attempt-root` is the attempts root shown above, never the already-expanded `<run_id>/<message_id>` directory. On PowerShell invoke a zipapp as `python <slk-transport.pyz> ...`, not `& <slk-transport.pyz> ...`.

The common files are `endpoint.json`, `envelope.json`, `accepted.json`, immutable task/request evidence with hashes, independently written `started.json`, `completed.json` or `failed.json`, plus adapter-native stdout, stderr, result and identity evidence when applicable. Desktop current-turn recovery preserves those files and adds `recovery/desktop-current-turn/{request,host-receipt,recovery,started}.json`; it never backfills the original directory's `started.json`. Native stdout/stderr capture is bounded with byte counts and SHA-256 so very large diagnostics remain traceable without entering model context. Worker continuation keeps bulk stdout/stderr locally and sends Checker only essential receipts plus `checker-evidence-index.json`, whose entries bind each retained file's path, byte length and SHA-256. Stable continuation event IDs reuse the first request's exact stored bytes and `occurred_at`; a semantic difference still conflicts. Job launcher logs are under `<attempt-root>/.jobs/`.

Nested Windows sends remain detached and headless. If and only if a containing Windows Job rejects `CREATE_BREAKAWAY_FROM_JOB` with access denied before a child exists, the launcher retries once without the breakaway flag; every other creation failure remains terminal. Worker-completion recovery starts its wrapper from the registered OCRV `runtime_root`; the immutable source attempt and every request/evidence destination remain absolute paths, so a long evidence path is never repurposed as process `cwd`. Internal command results are captured as bytes under a forced UTF-8 environment, and non-UTF-8 or empty output becomes a closed hashed transport error rather than an inferred result.

`accepted.json`, a database row, launcher exit, terminal result, legacy start, wrapper ACK or visible conversation does not prove delivery. A matching v2 receipt separately binds envelope `request_sha256` and native-input `native_request_sha256`. In the normal path, the sender retains TOKEN until its sealed credential atomically commits that receipt, event and post-event runtime revision. Worker→Checker is deliberately two-stage: DSH records D0/candidate, re-authenticates its resulting state, and stages one immutable Checker package; the external OCRV host starts the real review, then the sender commits. If a 4.3.4 legacy false start already placed TOKEN at that exact Checker, recovery first requires the closed six-field flat start, re-hashes its preserved `transport-task.json`, and matches the original endpoint/envelope/result contract, instance/Session, completed terminal, Worker result, candidate and central candidate/handoff events. Only then may it reuse the same candidate/message/attempt under `.native-recovery-v2`; it never resumes Worker, recommits/rolls back TOKEN, edits old evidence or treats the old marker as current activity. The sealed Checker credential is used internally to record actual `D1_STARTED` plus the terminal verdict. Before that event, the tool binds terminal run/message, current OCRV native identity, result SHA-256 and any aggregate/segment hashes. Supervisor, Overwatcher and ordinary shells neither receive credentials nor author Checker D1.

## Retry and session rebound

An inactive-target exact retry reuses the same endpoint, envelope, `message_id`, endpoint version, TOKEN number, Run/CELL/attempt scope, and payload. Recovery evidence has one deterministic `recovery/exact-1` identity. Existing start proof stops recovery; changed content/identity or any second retry is rejected. The active-Supervisor exception does the opposite deliberately: it never replays the old envelope, and accepts only the new message bound to the exact active turn.

When a native task or session is replaced, register a higher endpoint version, mark the old endpoint `retired`, and create the next handoff for the new endpoint identity. A retired endpoint rejects delivery. Session rebound is an identity change, not an excuse to guess by title or reuse an unverified session.

If an adapter explicitly fails or lacks start evidence, the sender keeps TOKEN and follows the existing SLK communication-recovery route; it does not claim the receiver or D2 started. An active writer follows only the narrow rule above. Recovery does not create a receipt-only turn, auto-upgrade a model, activate BoM, or move D0/D1/D2, exemption or planning authority into transport.

On Windows, Codex App Server, DSH, OCRV, detached transport jobs, and drill/recovery helper processes use the shared hidden-start flags by default. A bounded timeout terminates the whole wrapper process tree so inherited pipes cannot hang after the outer `.cmd` exits. No helper may flash a PowerShell/console window; a visible interactive window is an explicit Owner choice, not a recovery fallback.

## Acceptance

The accepted live two-Run evidence and immutable artifact hash are recorded in [`SLK-TRANSPORT-LIVE-ACCEPTANCE.md`](SLK-TRANSPORT-LIVE-ACCEPTANCE.md).
