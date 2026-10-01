# SLK Migration Guide

## Current patch migration: 4.3.5 to 4.3.6

Install the complete 4.3.6 package transactionally. Installation alone does not adopt, resume, dispatch, inspect, move TOKEN or mutate product files. At an Owner-authorized Supervisor boundary, an exact snapshot may adopt `4.3.5 → 4.3.6`; schema remains v8 and Run identity, plan, CELL/attempt, roles/endpoints, TOKEN, candidate, D0/D1/D2 history, Overwatcher history, transport attempts and product changes are preserved.

The only new compatibility path applies when a preserved 4.3.4 DSH attempt has a closed flat start, a completed Worker result and terminal receipt, and the exact immutable candidate already owns TOKEN at the registered Checker. The standard tool must match the old start's six-field shape, re-hash `transport-task.json`, bind its endpoint/envelope/result contract, match the original instance/Session and terminal identity, and prove the same candidate's central `CANDIDATE_SUBMITTED` plus Checker handoff `TRANSPORT_STARTED` chain. Missing or changed evidence fails closed. A fresh complete engineering projection is required; a previously trimmed or failed recovery projection is not reused.

After adoption, issue a new outer recovery message and retain every prior failed recovery and the original legacy evidence unchanged. Recovery reuses the staged candidate, starts only the external OCRV review under `.native-recovery-v2`, does not resume Worker or move TOKEN again, and lets the authenticated Checker record the actual D1. The flat marker remains invalid as normal native-start or current-activity evidence.

An already-running 4.3.4 Temporal Workflow keeps its 4.3.4 workflow/contracts package and frozen Start input. Its Worker may be restarted only to load the corrected Run-local thin adapter while that adapter calls the installed 4.3.6 transport query; do not replace the in-flight Workflow package with 4.3.6 or rewrite its fingerprint. No role, model, CELL/D0/D1/D2 authority, BI authority, Docker service, daemon, heartbeat, MCP or product file changes automatically.

## Current patch migration: 4.3.4 to 4.3.5

Install the complete 4.3.5 package plus matching DSH and OCRV integrations transactionally. The package installs a hash-bound `slk-transport.cmd` beside the managed pyz; verify the standard command resolves there rather than to an old Python user-site console script. Installation alone does not adopt, resume, dispatch, inspect, change TOKEN or mutate product files. At an Owner-authorized Supervisor boundary, an exact snapshot may adopt `4.3.4 → 4.3.5`; schema remains v8 and Run identity, plan, CELL/attempt, TOKEN, roles/endpoints, candidate, D0/D1/D2 history, Overwatcher history, old transport attempts and product changes are preserved.

New delivery starts require `slk.native-start/v2`; a 4.3.4 `started.json` is retained as history but is not reinterpreted. When that legacy receipt already caused TOKEN to reach the exact Checker, the 4.3.5 recovery entrance must reuse the same Run/CELL/candidate/message, keep the old attempt immutable, avoid Worker replay and TOKEN recommit, write actual OCRV native evidence under the deterministic `.native-recovery-v2` path, then let the authenticated Checker record its actual D1 result. If TOKEN did not move, the normal v2 start and atomic commit path applies.

Before dispatch, `preflight-run` must resolve the installed DSH/OCRV native-activity capability files. Overwatcher and an enabled Temporal adapter use `slk-transport inspect-native-activity`; they do not infer activity from old TOKEN, old session cache, a wrapper PID, log growth or a legacy marker. `UNKNOWN` is preserved and escalated rather than normalized to ACTIVE.

No role, model, CELL/D0/D1/D2 authority, BI authority, Temporal default, Docker service, daemon, heartbeat, MCP or product file changes automatically.

## Current patch migration: 4.3.3 to 4.3.4

Install the complete 4.3.4 package and matching OCRV integration transactionally. Installation alone does not adopt, resume, dispatch, inspect or mutate a Run. At an existing Supervisor boundary, an Owner-authorized exact snapshot may adopt `4.3.3 → 4.3.4`; schema remains v8 and Run identity, plan, CELL/attempt, TOKEN, roles/endpoints, candidate, D0/D1/D2 history, Overwatcher state, evidence and product changes are preserved.

Before new construction, readiness records Owner ON/OFF decisions only for Ponytail, Temporal, Overwatcher, RTK, Probe CLI and future genuinely optional features. BoM is not configurable and must not appear in a readiness request; any declaration returns `OPTION_FORBIDDEN` and stays outside the normalized result.

No role, model, CELL/D0/D1/D2 authority, TOKEN, BI authority, Temporal default, Docker service, daemon, heartbeat, MCP or product file changes automatically.

## Current patch migration: 4.3.2 to 4.3.3

Install the complete 4.3.3 package and the four-file OCRV integration transactionally. Installation alone does not adopt, resume, dispatch, inspect or mutate a Run. At an existing Supervisor boundary, an Owner-authorized exact snapshot may adopt `4.3.2 → 4.3.3`; schema remains v8 and Run identity, plan, CELL/attempt, TOKEN, roles/endpoints, candidate, D0/D1/D2 history, Overwatcher state, evidence and product changes are preserved.

This historical 4.3.3 preparation rule is superseded by 4.3.4 and should not be used for new construction. Existing 4.3.2 OCRV attempts remain frozen evidence; do not reinterpret their descriptive segments as scoped review. A new 4.3.3 D1 attempt uses request v2, exact background/capacity metrics and native preview scope. Missing optional RTK/Probe tools use native fallback; missing required role capability remains `REPAIR_NEEDED`, while identity mismatch or task overflow is `INCOMPATIBLE`.

No role, model, CELL/D0/D1/D2 authority, TOKEN, BI authority, Temporal default, Docker service, daemon, heartbeat, MCP or product file changes automatically.

## Current patch migration: 4.3.1 to 4.3.2

Install the complete 4.3.2 package. Installation alone does not adopt, resume, dispatch, inspect or mutate an existing Run. At an existing Supervisor-controlled boundary, an Owner-authorized exact snapshot may explicitly adopt `4.3.1 → 4.3.2`; Run ID, plan revision, current CELL/attempt, TOKEN holder/sequence, roles/endpoints, candidate and D0/D1/D2 history, Overwatcher state, transport evidence, product working tree and uncommitted product changes are preserved. Schema remains v8 with migrations `0001.sql` through `0008.sql`.

One preserved 4.3.1 Checker→registered Supervisor attempt that failed `CODEX_ACTIVE_WRITER_UNRESOLVED` may use the 4.3.2 Desktop current-turn bridge without first rewriting the Run's method history. This exception is transport-only: preserve the original attempt and exhausted exact retry, run `prepare-desktop-current-turn` against the attempts root, have the current Codex Desktop host read the target thread, inject the generated prompt, and read the same active turn back. Only the exact platform `functionCallOutput/codex_app/send_message_to_thread` item and matching message hash may enter the closed host receipt used by `complete-desktop-current-turn`. The resulting start belongs to a new recovery message under `recovery/desktop-current-turn`; it never backfills the original attempt.

PowerShell invokes the artifact as `python <slk-transport.pyz> ...`, not `& <slk-transport.pyz> ...`; `--attempt-root` names the attempts root above `<run_id>/<message_id>`. Missing readback, changed thread/turn/host/role/endpoint/payload, a visible message alone, or a self-authored success receipt remains unresolved. Transport never advances TOKEN; the original Checker inspects the matching recovery start and uses the existing authenticated `commit-delivery-start`. No other role route, Temporal workflow, Overwatcher authority, BI fact or product file changes automatically.

## Current patch migration: 4.3.0 to 4.3.1

Install the complete 4.3.1 package. Installation alone does not adopt, resume, dispatch, inspect or mutate an existing Run. At an existing Supervisor-controlled boundary, an Owner-authorized exact snapshot may explicitly adopt `4.3.0 → 4.3.1`. The adoption preserves the Run ID, plan revision, current CELL/attempt, T006 TOKEN holder and sequence, role/session endpoints, candidate and D0/D1/D2 history, Overwatcher binding and incidents, transport/attempt evidence, product working tree and every uncommitted product change. No SQLite migration is added; schema v8 and migrations `0001.sql` through `0008.sql` remain authoritative.

Before new Worker dispatch under 4.3.1, prove the visible worktree and the actual Git common store (`index`, `objects`, `refs`) are writable inside the supported Worker root; otherwise move the planned work to a separately authorized standalone writable clone before dispatch. A 4.3.0 in-flight attempt is not silently reinterpreted as the new closed Worker outcome contract. Preserve it unchanged and either finish it under its frozen contract or authorize a versioned same-scope recovery with exact evidence.

Checker still owns D1 and Supervisor still owns D2. For a formal D1 failure, Checker writes the exact `D1_FAILED`; Supervisor alone writes the successor `REWORK_REQUESTED` for the same candidate, CELL and attempt. OCRV segment results are durable review inputs, never separate D1 verdicts. An Overwatcher remains optional and non-authoritative; each later pause/resume occurrence gets a new incident identity while retaining the same binding. Temporal remains opt-in and direct mode remains valid. No product Run, model binding, BI authority, Docker service, remote tag or Release changes automatically.

## Current minor migration: 4.2.11 to 4.3.0

Install the complete 4.3.0 package. Existing 4.2.11 Runs keep schema v8, topology, role identities, CELL/D0/D1/D2 history, TOKEN, candidates, direct communication and Overwatcher history. At an existing Supervisor-controlled boundary, an Owner-authorized exact snapshot may explicitly adopt `4.2.11 → 4.3.0`; adoption does not automatically enable Temporal.

Temporal continuity is opt-in per Run. Before selecting it, supply an already-operated endpoint, explicit task queue, closed role endpoint bindings, bounded ACK timeout and adapter module, then preserve the startup fingerprint and workflow IDs. If the SDK, adapter or service is missing, continue the existing direct path or report the startup blockage; do not infer activation. Existing Runs and new direct-mode Runs require no Temporal migration.

No role responsibility, model policy, TOKEN rule, CELL, D0/D1/D2, BI authority, product candidate or database migration changes. Docker is not installed or required. The package ships templates and documentation only; service operation is a separate deployment choice.

## Current patch migration: 4.2.10 to 4.2.11

Install the complete 4.2.11 package. Existing 4.2.10 Runs retain topology, CELL/D0/D1/D2 history, TOKEN, candidates, BI facts, schema-v8 data, role identities, and Overwatcher history; adopt 4.2.11 only at an existing Supervisor-controlled boundary with the exact current snapshot. No database migration is added.

For a Run that already has its terminal event but still projects an active Checker or Worker, the current Supervisor uses the installed 4.2.11 `slk-state close-role` once for each exact role instance. A terminal legacy Run is not reopened or silently re-versioned; the compatible maintenance action preserves its recorded effective version. The command confirms the terminal Run, final record, non-TOKEN-holder target, active endpoint, and active credential. Exact replay is harmless; changed replay, open Run, wrong role or credential, and nonterminal state fail closed. Do not use `replace-role`, edit SQLite, invent a successor, or report a planned archive as actual archival. Overwatcher continues to use `close-overwatcher`; Supervisor remains available as the closed Run's authority record.

No role responsibility, TOKEN semantics, CELL, D0/D1/D2, model policy, product candidate, database schema, remote tag, or Release changes in this migration.

## Current patch migration: 4.2.9 to 4.2.10

Install the complete 4.2.10 package. Existing 4.2.9 Runs retain topology, CELL/D0/D1/D2 history, TOKEN, candidates, BI facts, schema-v8 data and Overwatcher identity; adopt 4.2.10 only at an existing Supervisor-controlled boundary with the exact current snapshot. No database migration is added.

Do not preserve any 4.2.9 prompt or wrapper that promises a delayed post-turn self-wake. An active-writer collision keeps the failed delivery immutable and sends one new auditable recovery message to the exact canonical task/active turn, or waits for a real Owner/Main activation. Worker continuation now returns the committed runtime revision, retains bulk logs by path/hash rather than sending them to Checker, revalidates resumed DSH identity, and starts OCRV headlessly outside the Worker job. LE BI separates Overwatcher binding, native liveness, cycle/incident pause and terminal closure; none changes CELL progress.

DeepSeek V4 Flash remains the Worker, Pro is not introduced, and BoM remains disabled. No role responsibility, TOKEN semantics, CELL, D0/D1/D2, model policy, product candidate, remote tag or Release changes in this migration.

## Current patch migration: 4.2.8 to 4.2.9

Install the complete 4.2.9 package. Existing 4.2.8 Runs retain the same topology, CELL/D0/D1/D2 history, TOKEN, candidates, BI facts, schema-v8 database and Overwatcher identity. This patch adds no database migration.

If the current exact Overwatcher binding is already `VIOLATION` because its latest native status is `COMPLETED`, `MISSING` or `MISMATCHED`, the current Supervisor may resume the same Session with `last_native_status_id`, a fresh runtime snapshot, the old/new foreground turns and hash-valid active-session evidence. Do not also send `last_anomaly_cycle_id`; do not select an older status, replace the Session, edit SQLite or write an ordinary cycle while continuity remains `VIOLATION`. After recovery, adopt 4.2.9 at the existing Supervisor-controlled boundary with a fresh exact snapshot.

No role responsibility, TOKEN semantics, CELL, D0/D1/D2, model policy, BI authority, product candidate, remote tag or Release changes in this migration.

## Current patch migration: 4.2.7 to 4.2.8

Install the complete 4.2.8 package. Existing 4.2.7 Runs retain the same topology, CELL/D0/D1/D2 history, TOKEN, candidates, BI facts and Overwatcher identity. The schema-v8 migration creates a verified backup and one append-only credential-rotation receipt table; it does not expose credential metadata to BI.

If the current Overwatcher write secret was lost or a caller stored `overwatcher_credential_id` instead, the current Supervisor may call `rotate-overwatcher-credential` against the exact ACTIVE binding. Capture the one-time `overwatcher_write_credential`, immediately run `authenticate-role`, and let the same Session record a valid current-binding cycle. Only then adopt 4.2.8 with a fresh snapshot and `PRESERVED_ACTIVE`. Do not invent a continuity violation, replace the Session/turn/binding, replay the rotation, or edit SQLite.

No role responsibility, TOKEN semantics, CELL, D0/D1/D2, model policy, BI authority, product candidate, remote tag or Release changes in this migration.

## Current patch migration: 4.2.6 to 4.2.7

Install the complete 4.2.7 package. Existing 4.2.6 Runs keep their role topology, CELL/D0/D1/D2 history, TOKEN, candidates, BI facts, and optional Overwatcher binding; adopt the new method contract only at an existing Supervisor-controlled boundary with the exact current snapshot.

Worker and Checker now perform role-local lightweight preflight. Internal Worker work segments and Checker `D1-A/B/C...` inspection segments are sequential planning aids only: they do not create another formal CELL, D1, TOKEN, role, or acceptance count. Supervisor intervenes only after a member report or an Overwatcher anomaly.

Codex endpoint files stay immutable when a Desktop update moves `codex.exe`; transport records the resolved executable separately. OCRV requests now match the installed closed v1 contract. Legacy Worker results that omit repository may use only the authenticated immutable endpoint `cwd`; new results include repository explicitly. Exact continuation retries reuse the first stored event bytes and timestamp.

No D2, LCaS product candidate, BoM, model binding, remote tag, or release is changed by migration.

## Current patch migration: 4.2.5 to 4.2.6

Install the complete 4.2.6 package, then explicitly adopt each still-open 4.2.5 Run with its exact current snapshot and Overwatcher assertion. Adoption preserves topology, plan, role/session identities, TOKEN, engineering history, current candidate and all prior Overwatcher cycles.

If an Overwatcher has already reported an anomaly and the Supervisor later wakes the same Session into a new foreground turn, call `slk-state resume-overwatcher-turn` with the current runtime/binding revision, exact prior turn, exact latest anomalous cycle, new turn and hash-verified native evidence before recording the next cycle. Do not create a replacement Session or rewrite the prior cycle.

Worker completion recovery in 4.2.6 requires the exact current attempt, candidate and derived handoff message. A legacy 4.2.5 record that lacks these facts remains unproved and must be recovered through the existing roles; it is not silently reinterpreted. Rework `acceptance_criteria` is passed to OCRV as `d1_criteria`. Active-writer delivery uses read+steer, and long OCRV work must run under the detached headless Checker transport host or a persistent Supervisor host. Tool failure remains the same attempt and is not a product D1 FAIL.

No model policy changes are included. DSH remains the frozen Worker runtime for affected LCaS Runs; Pro and BoM remain disabled.

## Migration from SLK 2.6.0 to 3.0.0

SLK 3.0.0 is a new method boundary. Existing Runs can remain on their bound 2.6.0 method. A new Run can choose 3.0.0 and create a fresh root Run record.

## Topology

```text
2.6.0: Control responsibilities ↔ Worker + Patrol
3.0.0: Supervisor ↔ Checker ↔ Worker
```

- Supervisor, Checker, and Worker use separate visible project conversations.
- Checker owns CELL-level D1.
- Supervisor owns Run-level D2.
- Supervisor is event-activated for setup, escalated help, recovery, exemptions, and D2; Checker and Worker own the daily CELL loop.
- Worker keeps a minimum D0 before delivery.
- The previous GO-level verification layer leaves the current method; the previous Run-level D3 becomes D2.
- Patrol, Pin governance, runtime index, fixed model binding, capacity gate, and Owner acceptance receipts leave the active Skill surface.

## Guidance model

The 2.6.0 monolith becomes one small router plus 12 sibling situational Skills. Role-based model choice becomes a small on-demand Skill used during Run planning or capability adjustment; it describes capability tiers rather than fixed vendor models. Generic root-cause diagnosis is routed to an available project-appropriate Debug Skill rather than duplicated inside SLK.

## Records

Create `SLK-RUN-<RUN-ID>.md` in the project root from the 3.0 template. Each role writes its own work, including failures, rework, exemptions and handoffs. Existing 2.6 receipts can remain with the old Run rather than being reinterpreted as 3.0 records.

## Recovery

The `v2.6.0` tag and Release preserve the previous repository and install tree. Choosing 3.0.0 installs the Skill collection as sibling directories and leaves the historical release available.

## 3.0.5 planning clarification

Runs adopting 3.0.5 keep D0, D1, and D2 as inspection layers rather than adding inspection-only CELLs. For midstream adoption into completed or partly completed work, re-plan only the still-needed construction: preserve and reuse completed results, and size the route, scope, and engineering activities needed to reach the current target reliably. Findings enter the CELL plan only when they require implementation work.

## Migration from 3.0.8 to 4.0.0

SLK 4.0 keeps the 3.0.8 three-role method and extends the collection to 14 Skills with one compact resource-continuity guard. It does not introduce another construction role, inspection layer, scheduler, watcher, acknowledgement loop, or Owner write path.

For a new 4.0 Run, configure one machine-wide SLK data root and initialize the Run through `slk-state`. Supervisor, Checker, and Worker then append only the facts at their existing boundaries. Native transport remains responsible for real Agent activation; the state row is written after accepted delivery evidence and never substitutes for it. Existing 3.0.8 Markdown records remain historical records rather than being silently imported as live state.

Other Agents and BI read through `slk-bi-query` or the same core projections. The standalone BI is optional for construction and read-only by design. Existing prompt-only Runs may finish on 3.0.8; adopting 4.0 requires an explicit new 4.0 Run identity and configured state root rather than partially mixing both state models.

## Migration from 4.1.1 to 4.2.0

Existing 4.1.1 Runs remain valid and may finish without an Overwatcher. Before a 4.2 writer or BI opens an older state root, run the normal writable `slk-state configure` migration so the verified backup and schema-v4 tables are created atomically. Do not reinterpret an old Run as having an Overwatcher or infer lineage from its title.

New 4.2 Runs keep the same Supervisor ↔ Checker ↔ Worker direct routes, TOKEN flow, CELL, D0, D1, and D2 semantics. They use the versioned closed role Eval before binding and may optionally bind one dedicated Overwatcher Agent Session. The Overwatcher has a separate observation credential, cannot write engineering facts or BI/TOKEN, cannot become a mandatory relay, and is closed and archived with its Run. Successor Runs name `predecessor_run_id` explicitly; independent Runs leave it empty.

New role registrations use the fixed Codex Supervisor, OCRV Checker, and DSH Worker identities; old prompt-only or all-Codex substitutions are not silently accepted. D1 INCOMPLETE leaves TOKEN with Checker. A formal D1 FAIL uses the closed Checker failure escalation and Supervisor rework directive for the same Worker; this exception does not create a general Supervisor→Worker route or move D1 authority.

Communication recovery now inspects the original immutable attempt first and permits at most one exact retry with the same message, endpoint, payload, and scope. A semantic change returns `SUPERVISOR_DECISION_REQUIRED`. Windows helper processes default to hidden/no-window operation. No Temporal service, daemon, broker, MCP, additional engineering role, or hard optional-tool dependency is introduced.

## Migration from withdrawn 4.2.0 to 4.2.1

Do not start a new Run on 4.2.0. It was a local-only candidate with defective end-turn Overwatcher semantics and was never tagged or released. Install 4.2.1, then run the normal writable `slk-state configure` against the configured data root so a verified schema-v4 backup is created before the atomic schema-v5 migration.

An existing 4.2.0 Overwatcher binding remains visible but receives no inferred active status. Close or explicitly rebind it under 4.2.1 with one exact Session, `FOREGROUND_ACTIVE_TURN`, a Supervisor-and-Owner-confirmed 180–300 second interval, foreground turn identity, and native active-session evidence. Do not convert its former wake fallback into a heartbeat, automation, cron, Windows Scheduled Task, daemon, service, detached helper, background Agent, or second observer. Existing 4.1.1 Runs without an Overwatcher retain the compatibility path above.

## Migration from 4.2.1 to 4.2.2

Run the normal writable `slk-state configure` once before read-only tools so the verified schema-v5 backup and atomic schema-v6 migration add `origin_slk_version` plus the append-only reconciliation and method-adoption receipt tables. Existing Runs keep their effective and origin version values equal; 4.2.1 Runs may continue normally and may bind an Overwatcher without an adoption receipt.

For several already-created Run roots that the Owner has identified as one real continuation, the canonical Run's current Supervisor obtains closed Owner evidence and exact live snapshots, then executes `slk-state reconcile-run-identities --request <json>` with the explicit canonical and source IDs. Do not select by title, newest timestamp, or project name; do not edit SQLite, invent a missing old credential, create another Run, or change engineering history. A changed snapshot fails closed and requires a freshly reviewed request.

If the surviving Run began on 4.1.1, 4.2.0, or 4.2.1 and needs the 4.2.2 contract, take a new exact snapshot after reconciliation and execute `slk-state adopt-method-contract --request <json>`. A reconciled Run cites its matching reconciliation receipt. Adoption requires no active Overwatcher and preserves the origin version, roles, TOKEN, CELL, D0/D1/D2, evidence and plan history. Verify one `CURRENT` canonical Run and the expected TOKEN before binding the confirmed Overwatcher Session; binding or dispatch remains a separate Supervisor action.

## Migration from 4.2.2 to 4.2.3

Install the complete 4.2.3 package atomically, then run the normal writable `slk-state configure` once so the verified schema-v6 backup and schema-v7 migration precede read-only use. New deliveries use immutable task/start evidence and `commit-delivery-start`; a 4.2.3 Run rejects legacy split `handoff`, terminal-derived start, mixed runtime revisions, silent model changes, and BoM routes.

An open 4.2.2 Run adopts through `adopt-method-contract` with an exact snapshot and explicit Overwatcher assertion: `ABSENT`, hash-verified `PRESERVED_ACTIVE`, or `CONTINUITY_RECOVERY_REQUIRED`. Adoption preserves origin version, plan, roles, TOKEN, CELL/D0/D1/D2 and evidence; it neither silently repairs nor rebinds an Overwatcher. The same optional Session/foreground turn remains bound once for the whole Run—CELL boundaries only change cycle scope—and terminal close requires the exact final cycle and runtime revision. Any exceptional replacement is Supervisor-authorized, non-overlapping, and retains the continuity gap.

## Migration from 4.2.3 to 4.2.4

Install the complete 4.2.4 package, then adopt each still-open 4.2.3 Run explicitly with its exact snapshot and one of `ABSENT`, hash-verified `PRESERVED_ACTIVE`, or `CONTINUITY_RECOVERY_REQUIRED`. The transition preserves topology, role/session identity, plan, engineering history, TOKEN, and an active whole-Run Overwatcher; it does not reinterpret old records or mutate a product candidate.

For a legacy DSH attempt that already has matching `started.json`, `worker-result.json`, and terminal completion but still holds TOKEN without Worker D0/candidate facts or Checker start, first confirm the active Checker endpoint, exact DSH instance/session, Worker DPAPI credential path, and current runtime snapshot. The original Checker may then call `resume-worker-continuation`; the resumed Worker process authenticates its own credential, derives D1 criteria from the immutable original envelope and candidate/evidence from the immutable result, writes exact-replay-safe facts, and hands the candidate to OCRV. Missing/mismatched credentials, Session, endpoint, hashes, native start evidence, or fresh runtime revision fail closed. This is a one-attempt suffix recovery, not permission to rerun the CELL, replace the Worker, or create a scheduler.

The local installer replaces only the declared SLK Skills, five binaries, docs, schemas, VERSION and manifest after staging/hash verification, and restores the previous complete managed set on failure. It does not configure, inspect, migrate, or modify LCaS R3B; that project remains outside this upgrade.

## Migration from 4.2.4 to 4.2.5

Install the complete 4.2.5 SLK package first, then explicitly adopt each still-open 4.2.4 Run with its exact snapshot and `ABSENT`, hash-verified `PRESERVED_ACTIVE`, or `CONTINUITY_RECOVERY_REQUIRED` Overwatcher assertion. Adoption preserves topology, role/session identities, plan, engineering history, TOKEN, and the existing whole-Run Overwatcher binding; it does not start recovery or modify a product candidate.

The OCRV recovery entrance is a separate reversible integration. Against an explicitly selected OCRV root that already contains the accepted `slk_checker_adapter.py` and `slk-checker.cmd`, run packaged `integrations/ocrv/install.ps1 -OcrvRoot <path>`. It backs up the old wrapper under `<path>/.slk-backups`, installs only the wrapper plus `slk_checker_recovery.py`, and verifies hashes. Use the returned backup path with `integrations/ocrv/rollback.ps1 -OcrvRoot <path> -BackupRoot <path>` to restore the exact prior wrapper and prior companion state. Do not run either script against a live project until that project's Supervisor/Owner authorizes adoption and installation.

After adoption, terminal-without-handoff recovery begins with Supervisor sending `WORKER_COMPLETION_RECOVERY` to the exact registered Checker endpoint. The native OCRV invocation authenticates the current Checker before calling the internal continuation entrance; Supervisor, Overwatcher, and a shell cannot use the removed public direct-resume command. Existing 4.2.4 attempts remain blocked until explicit adoption and the reversible OCRV integration are both complete.
