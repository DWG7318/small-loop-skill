# SLK Cross-Agent Transport

`slk-transport 4.4.2` carries one closed delivery into an exact native Agent endpoint, verifies native activity read-only and implements deterministic four-role readiness/OCRV preflight without moving D1 authority. `preflight-conformance-sample` is the only first-source bootstrap: one disposable CELL, Run evidence/consumers/Temporal attempts under `slk-conformance/<SLK-CONFORMANCE-…>`, Worker bound to one separate clean, fixed-HEAD, no-remote sample Git, and every other role retaining its true native workspace/cwd. The frozen `root_record_path` must resolve to the exact same-Run automatic export below the currently configured SLK data root, never a hand-written/copied file in the sample Git. `seal-normal-chain-source` then binds its complete real seven-leg drill. `preflight-new-run` joins that distinct source to a product Run's initial TOKEN, current identities, consumers, BI and real Temporal pair without inventing future engineering events. `preflight-admission` remains the in-flight adoption gate. DSH stages the immutable Worker candidate; an headless OCRV invokes its own explicit standard action to record D1.

## Role edges

The exact normal edges are initial Supervisor→Checker, ordinary Checker→Worker→Checker, formal FAIL Checker→Supervisor→same Worker→Checker, INCOMPLETE Checker→Supervisor→original Checker and final Checker→Supervisor D2. Only an explicit D1_REWORK_DIRECTIVE authorizes Supervisor→Worker. Overwatcher observes and reports only to Supervisor; Temporal owns continuity/timing, not engineering decisions.

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

DSH receives one immutable hash-bound slk.transport-task/v1 descriptor. Its result_contract is optional communication guidance, not a report-release schema. OCRV receives slk.ocrv-d1-request/v2 with factual candidate/scope/capacity, then performs one native review; preview is planning only. Aggregate budget/timeout use native 0 and tool rounds use verified template default; line/file/context estimates never open automatic segments or generate D1. Public transport-owned contracts remain closed; Agent report bodies do not.

`message_id` is a canonical UUID. The payload hash is SHA-256 over canonical JSON. Run, receiving role, role instance, and endpoint version have to match before dispatch.

D1_FAILURE_ESCALATION and D1_INCOMPLETE_ESCALATION bind the original Checker's explicit event and exact candidate/scope. Missing report fields are not transport permission failures; no findings/reproduction/expected outcome is fabricated. Explicit live actions bind their native start and decision receipt rather than future terminal files. D1_REWORK_DIRECTIVE retains Supervisor→same Worker identity. Old WORKER_COMPLETION_RECOVERY/PRE_D0_BLOCKED_RECOVERY are retired, not new dispatches.

## Exact adapter addresses

- Codex Supervisor: `command`, exact `thread_id`, absolute `cwd`, `startup_timeout_seconds`, `turn_timeout_seconds`. Transport reads metadata with `includeTurns:false`, then uses the bounded current-turn summary when needed; `notLoaded` and an active writer are not activation evidence, so only an explicit `idle` status may start a turn and transport never blind-resumes a Desktop-owned thread. If an absolute Codex Desktop executable disappeared after update, only the current PATH-resolved `codex.exe` replaces the process command and `command-rebind.json` records both paths; endpoint role/session identity remains immutable.
- DSH Worker: command, deterministic Run-scoped instance_id (≤64), recorded session_id or null, runtime_root, cwd, timeout_seconds and exact Git identity. Startup timeout never kills verified engineering work. A writable clone/simple Git common-dir must stay inside the sandbox. Original report bytes remain arbitrary; native exit/activity is separate.
- OCRV Checker: command, runtime_root, timeout_seconds and optional closed review_capacity (max_tokens, max_tokens_budget, timeout_minutes). Normal aggregate budget/timeout are native 0; max-tools=0 selects verified template default, not unlimited tools. CELL_DISPATCH validates the registered Worker endpoint and frozen payload; CANDIDATE_READY invokes one full native review. Invocation/input/start failure is a communication fact, not D1.

Addresses are selected by identity, never by conversation title. Secrets stay in the native runtime configuration and do not belong in endpoint, envelope, result, or evidence files.

Desktop-owned Supervisor endpoints may add exactly `desktop: {caller_thread_id, model, reasoning_effort, plugin_sha256}`. Their immutable command pins Node/plugin paths and plugin bytes. Only a missing `node`/`node.exe` path may use the existing PATH Node for execution, with separate `slk.codex-desktop-command-rebind/v1` evidence binding original/resolved commands, target, address/plugin hashes and current executable bytes; no endpoint, envelope, role, Session, model or plugin is replaced. A valid original runtime is unchanged; an existing non-file path, missing non-Node runtime, absent PATH Node or changed plugin fails closed. Never copy an executable into a deleted app directory or treat command recovery as receipt. Only authenticated Checker→registered Supervisor `D1_FAILURE_ESCALATION`, `D1_INCOMPLETE_ESCALATION` and `D2_READY` may use another genuinely inherited Desktop executor; Run, receiver identity, active endpoint/version and frozen model/effort remain exact, and native readback records the actual caller without rewriting its environment or endpoint. This uses Desktop App Tools, never CLI takeover or a second writer. Missing capability, plugin drift or wrong thread/host/workspace rejects delivery. An idle target must produce a new native turn/item; one unambiguous active turn may receive a fresh exact item. Bounded native status/turn identities retain the first pre-send observation; unknown status is not terminal proof. Request metadata is not actual-model attestation. Exact escaped input/platform caller readback proves receipt, not acceptance or repair; sealed authorization proves the engineering sender, and uncertain sends are never blindly repeated.

Desktop's initial metadata-only read retains native item IDs at 4096 characters per item; post-send and late readback request at most the actual API's 20000-character limit. These are native readback representations, not limits on engineering material. New Desktop and App Server sends both use immutable `desktop-material.json` (`slk.desktop-material/v1`, retaining the existing format): it holds the complete original prompt and closed envelope, while the short sent instruction binds its absolute path, byte length, SHA-256 and original Run/CELL/message/payload identity. The receiver must fully read and verify it before following the unchanged decision/result/submit instructions. Historical inline receipts remain readable. Missing or changed material reports the exact failed original; do not guess its contents, resend uncertain work or choose another endpoint. Native item/ACK requirements remain unchanged: delivery of a path proves neither reading nor acceptance. A proven pre-send Tool failure uses the existing same-message `retry-exact`, preserving its original failure.

Preparation freezes slk.role-host/v1 or v2, exact endpoint hashes, sealed-consumer paths, serial tasks, D2 criteria and optional existing Temporal binding. Jobs save/deliver native outputs independently; original roles explicitly submit engineering actions. Credentials stay sealed inside the relevant consumer. Current plan/role/native/attempt/TOKEN and atomic receive-start remain checked; no report hard veto or automatic second-FAIL decision is reinstated.

Every subsequent CELL retains cell_id, cell_ordinal, required_cell_count, task, d1_criteria and root_record_path; frozen plans are validated before dispatch. Candidate goals come from that plan, not a report replacement. Supervisor explicit actions retain incoming source/failure/candidate/round and intent, not a closed engineering-report field set. Non-wait management returns the unchanged candidate to the original Checker; no management result authors D1.

The isolated source accepts only same-Run `slk.communication-rehearsal/v2`: it joins every original-role endpoint/envelope/send/native-start and engineering commit by absolute path and SHA-256. `seal-normal-chain-source` binds that source Run's plan, minimal role registry, complete rehearsal and exact state config path/hash. `preflight-new-run` then authenticates the product Run's exact initial Supervisor TOKEN, four current identities and sealed consumers, Host, BI and post-bootstrap Temporal identity/admission without replaying a product D1/FAIL/D2. Source child calls use the source config without changing the parent environment. Config drift, cross-database lookup, echo v1, missing commits/consumers, stale identities/plan and recovery presented as normal all fail closed.

`notify-supervisor --request <json>` is the existing host's operational notice entrance, not an engineering handoff. Its closed request contains `notification, endpoint_path, runtime_projection_path, attempt_root`; notice is either the closed OW notice or the existing six-field Temporal alarm. The native Supervisor endpoint is rejoined to current registration/model request. It proves exact native receipt without waiting for the Supervisor turn to finish or moving TOKEN. Temporal receives the original event ID, native start and receipt hash; accepted-only notices stay unproved. `observe_overwatcher_exit` in the same transport package is called by the owning host's exit hook or existing Temporal audit: it reads exact native evidence independently, retains one compact exit record and returns the existing exit notice, without requiring OW's last message. An anomaly notification never proves Supervisor takeover.

## Commands and role actions

```text
slk-transport validate --endpoint ENDPOINT.json --envelope ENVELOPE.json
slk-transport send --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
slk-transport inspect --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
slk-transport inspect-native-activity --started STARTED.json [--completed COMPLETED.json] [--failed FAILED.json]
slk-transport retry-exact --endpoint ENDPOINT.json --envelope ENVELOPE.json --attempt-root EVIDENCE_ROOT
slk-transport continue-staged-handoff --binding HOST.json --sha256 HOST-SHA256 --source-attempt EXACT-ATTEMPT [--temporal-request ORIGINAL.json --temporal-request-sha256 SHA256]
slk-transport submit-worker-action --event WORK_STARTED|D0_COMPLETED|CANDIDATE_SUBMITTED [--details OWN-ACTION.json]
slk-transport start-d2 --request SEALED-ADMIN.json --sha256 ADMIN-SHA256
slk-transport submit-supervisor-decision --binding HOST.json --sha256 HOST-SHA256 --source-attempt EXACT-ATTEMPT
```

Worker action source comes only from its bound native invocation, never a selectable source argument. D0/candidate are its explicit authenticated actions; CANDIDATE_SUBMITTED includes its actual candidate locator. The completed native job preserves arbitrary report bytes and uses that recorded candidate—not report JSON—to deliver one standard message to the original Checker and atomically commit the exact receive/start. Without that action, reports still travel, but cannot silently author D0/candidate/TOKEN. Missing candidate is not replaced with a fabricated workspace review; the Checker interface fact and original report go to Supervisor.

The original OCRV Checker uses the existing stdio MCP bridge: `slk_checker_decide(verdict, message?)` submits its decision; `slk_read_evidence(index, offset?, limit?)` reads hash-checked indexed originals outside Git without arbitrary paths. Reads return the full original by default, with no content-length ceiling; optional offset/limit ranges are chosen by OCRV, not imposed by the tool. Its deliberate PASS/FAIL/INCOMPLETE call authenticates only that role, records its actual decision time and runs the existing normal successor: next Required CELL/final D2, Supervisor rework, or Supervisor management. After the action returns and its reply is flushed, invocation-bound cleanup ends only the exact old review, preserving logs and successor processes. Optional message is its own original text; absent reproduction/expected-result facts are not invented. No shell tool or second review role is added. See [installed MCP setup](../../integrations/ocrv/OCRV-SLK-CONFIGURATION.md).

Supervisor saves arbitrary output independently. Only its explicit same-Session submit changes D2/rework/management state; outgoing identity/failure/candidate intent remains checked, not report quality, field completeness or evidence availability. The same CELL's second formal FAIL still requires more serious investigation and consideration of smaller successor CELLs in Skill guidance; it is no longer a report/rework hard veto.

At actual D2 start, the original Supervisor uses the existing [sealed admin request](../contracts/slk-supervisor-admin.schema.json) with `operation=start-d2`. Its hash-bound operation file has exactly `run_id`, `role_instance_id`, `binding_path`, `binding_sha256`, and `source_attempt_path`; these point to the current prepared RoleHost and the original received `D2_READY` attempt, not an outgoing/recovery directory guessed by name. The Host verifies native caller/start, current plan/TOKEN and committed delivery before writing the single `D2_STARTED`. Replaying that start preserves its original time; a 4.4.3 final D2 decision references it and never synthesizes a start at completion. Earlier-version history remains readable under its original contract.

## Evidence and responsibility

Save and deliver original long, partial, non-JSON and nonzero-exit reports, plus path/bytes/SHA-256 indexes. Never infer D0/D1/D2 from output format, severity, coverage, exit code, missing result or a successful host call. Worker D0 conclusions are excluded from initial D1 background: independently inspect candidate/criteria first, then reconcile indexed original evidence before final D1. Objective native identity is separate from any claimed model or Session in a report.

Native inspection starts with the exact Run/current holder/message/operation and its authoritative endpoint/envelope/start hashes. It never selects an arbitrary latest segment or uses another Run's activity. The existing bound DSH hook samples the exact live Agent registry every 60 seconds, keeping sample time separate from the original last-event time/sequence and excluding an archived Session only from the native registry marker. OCRV's launcher receipt proves an invocation, not a Go PID or native Session: a unique invocation/request marker in the original input binds an immutable native header/input record to one exact Session; subsequent queries read only its public `session_start`, `tool_call` and `session_end` metadata. The original MCP bridge separately observes its direct native parent under that launcher tree; only the exact native PID/creation-time plus Session binding can establish that this execution is still running, never engineering progress. Missing, ambiguous, stale or contradictory evidence remains UNKNOWN with any verified last action retained. Historical OCRV inputs without the marker cannot be guessed into a binding.

These are the original bound hook/reader paths, not a proven all-tool/all-Session collector. Owner's headless, at-most-once-per-tool-per-minute and total 10MB collected-persistence boundaries remain requirements; 10MB is not a size limit on original native logs. Streaming metadata inspection neither copies private messages/arguments/results/reasoning/native payloads nor authenticates a mutable log by its whole-file hash. No OCRV native archive flag is confirmed, and BI absence is not an archive marker.

`send` acknowledges only `NATIVE_RECEIVE_START_ONLY`; saving, accepting or starting is not engineering acceptance or proof that later output arrived. `job` exposes `native_result`, `output_delivery` and any explicit-action `handoff` separately. Failed delivery/action returns a real error without changing native terminal bytes. `inspect` reads saved later delivery evidence or reports UNOBSERVED; it cannot manufacture success or retry.

Report delivery does not wait for TOKEN/Temporal/OW readiness. An explicit engineering action still requires registered authority, exact native input/start, current plan/attempt/TOKEN and atomic commit; a guard failure does not withdraw an already-delivered report. Each outgoing action retains its original engineering attempt, including D1_MANAGEMENT_RETURN and second-attempt rework. Next-CELL PASS starts the next CELL at its own attempt 1.

Exact saved native/central delivery (including historical `recovery/exact-1`) is reused without new IDs, sends, review or rollback. An existing external Temporal operation is ACKed only from its exact original request or saved ACK. A newly delivered explicit Worker output registers that same immutable message in the existing Temporal path before its remaining commit; guard failure is reported separately. No new relay, recovery layer, daemon or model is added.

Retired format/partial/context/terminal-budget recovery commands reject instead of launching review or synthesizing a verdict. Their old contracts/evidence are historical only; see [retirement note](SLK-OCRV-CONTEXT-RECOVERY.md).

## Retry and session rebound

An inactive-target exact retry reuses the same endpoint, envelope, `message_id`, endpoint version, TOKEN number, Run/CELL/attempt scope, and payload. Recovery evidence has one deterministic `recovery/exact-1` identity. Existing start proof stops recovery; changed content/identity or any second retry is rejected. The active-Supervisor exception does the opposite deliberately: it never replays the old envelope, and accepts only the new message bound to the exact active turn.

When a native task or session is replaced, register a higher endpoint version, mark the old endpoint `retired`, and create the next handoff for the new endpoint identity. A retired endpoint rejects delivery. Saved Supervisor authority is consumed only by hash-bound `supervisor-admin`; it may call `rebind-session` for the exact current binding. An OW endpoint-only correction preserves its role instance, native Session, adapter and host and changes only the versioned native address. OW cycle/status writes use `overwatcher-admin` and the OW's own sealed credential, never Supervisor authority. Before a Worker-held cycle write, that consumer re-queries current scope, binds the original `started.json` plus endpoint/envelope hashes to the authoritative start event, and re-inspects the unique completion receipt read-only; hand-written/changed status, missing/duplicate proof and stale or unreal cycle times are rejected, not silently corrected. Each Tool uses its current UTC; cycle start and completion are distinct real observations. Session rebound is an identity change, not an excuse to guess by title or reuse an unverified session.

`prepare-runtime-binding-migration` is the narrow same-Checker exception for replacing a finite OCRV aggregate budget/timeout with the ordinary unlimited values while keeping the per-call token ceiling, role instance, Session, model, credential, adapter and host unchanged. It materializes endpoint v2, the next frozen RoleHost, the same-workflow Temporal config and both existing Supervisor-admin requests without changing the live Run. `migrate-runtime-binding` then installs a dispatch-denying config guard before consuming only `rebind-session`; it returns `RUNTIME_BINDING_REBOUND_AWAITING_PLAN_REVISION` and leaves the guard active. The Supervisor separately executes the frozen existing `revise-plan` request. A replay verifies that exact result/current revision and atomically publishes the new RoleHost config. Any mismatch or interrupted phase retains the guard, old endpoint/Host/config backup/history/attempts/results and forbids the next delivery; the migration consumer never authors product plan content or starts another workflow pair.

If an adapter explicitly fails or lacks start evidence, the sender keeps TOKEN and follows the existing SLK communication-recovery route; it does not claim the receiver or D2 started. An active writer follows only the narrow rule above. Recovery does not create a receipt-only turn, auto-upgrade a model, or move D0/D1/D2, exemption or planning authority into transport.

On Windows, Codex App Server, DSH, OCRV, detached transport jobs, and drill/recovery helper processes use the shared hidden-start flags by default. A bounded timeout terminates the whole wrapper process tree so inherited pipes cannot hang after the outer `.cmd` exits. No helper may flash a PowerShell/console window; a visible interactive window is an explicit Owner choice, not a recovery fallback.

## Acceptance

Historical live two-Run evidence is recorded in [`SLK-TRANSPORT-LIVE-ACCEPTANCE.md`](SLK-TRANSPORT-LIVE-ACCEPTANCE.md).
\nCurrent simplification evidence is in [the local validation ledger](../superpowers/specs/2026-10-09-output-delivery-without-host-review-validation.md); offline wiring does not claim actual model competence or product adoption.\n
