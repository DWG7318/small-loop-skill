# Changelog

## 4.3.5

- Replaced legacy presence-based `started.json` acceptance with the closed `slk.native-start/v2` receipt. It separately binds envelope payload and native input hashes, exact process identity and exact native task identity; state rejects legacy, mismatched or stale receipts before TOKEN movement.
- Added one read-only `inspect-native-activity` entrance and installed DSH/OCRV capability declarations. Missing, stale, mismatched or permission-blocked evidence returns `UNKNOWN`; Desktop platform turn evidence is authoritative over a short-lived bridge CLI PID.
- Stopped hosting OCRV D1 inside the one-shot DSH Worker process. DSH stages one immutable candidate package; the authenticated OCRV recovery host starts the real review, records Checker-owned `D1_STARTED` and the actual native PASS/FAIL/INCOMPLETE result, and never asks Supervisor to forge a Checker event.
- Added exact same-candidate recovery when a legacy false start already moved TOKEN to Checker. The old attempt stays immutable, Worker is not resumed, TOKEN is not moved again, and new native v2 evidence is written under a deterministic recovery path.
- Added atomic `init-run --credential-out`, a packaged Role Eval validator, headless integration launchers, real DSH event-signature checks, and an adapter-receipt-to-state integration test. No role, daemon, heartbeat, MCP, scheduler, Docker dependency, BI write authority or product method was added.

## 4.3.4

- Removed BoM from the Run-readiness option set and every Owner option surface. A readiness request that declares BoM as either `ON` or `OFF` now returns `REPAIR_NEEDED` with `OPTION_FORBIDDEN` and omits it from the normalized option result.
- Preserved the existing method-level prohibition: no BoM trigger, route, role or runtime exists. Ponytail, Temporal, Overwatcher, RTK and Probe CLI remain the five explicit per-Run decisions.
- Kept schema v8, the three engineering roles, direct communication, TOKEN, CELL/D0/D1/D2 authority, OCRV preflight, optional Temporal/Overwatcher behavior and product repositories unchanged.

## 4.3.3

- Added one closed `preflight-run` gate for the exact Codex Supervisor, DSH Worker and OCRV Checker bindings, context/task capacity, writable workspace, required capabilities and explicit Owner ON/OFF decisions for every option.
- Replaced descriptive OCRV segments with executable background/capacity measurement and native `review --preview` scope proof. Every segment excludes the rest of the candidate, runs sequentially and stops after a blocking finding.
- Removed full segment-result reinjection. One compact aggregate retains verdict/reason/hash provenance while excluding complete result bodies and paths; oversize, preview mismatch and incomplete coverage fail closed before further model work.
- Added a small optional RTK/Probe capability profile, transactionally installed OCRV adapter/wrapper/recovery/capabilities with hash receipts, and explicit `4.3.2 → 4.3.3` schema-v8 adoption. No role, authority, daemon, MCP, heartbeat, Docker dependency or product mutation was added.

## 4.3.2

- Added one narrow two-phase Codex Desktop current-turn bridge for an exact Checker→registered Supervisor delivery whose external App Server attempt and one exact retry are preserved but remain blocked by the Desktop active writer.
- Bound the new logical recovery message to Run/GO/CELL/TOKEN, both role identities, endpoint version, payload, endpoint/envelope file hashes, target thread, challenge, Desktop host/session, exact active turn, platform item and injected-message hash. Missing or mismatched platform readback fails closed and never writes start evidence.
- Kept the original failed attempt immutable and wrote request, host receipt, recovery and start evidence only under a separate deterministic recovery directory. Transport does not move TOKEN; the original sender still commits delivery start after inspecting the matching evidence.
- Mapped the real App Server initialization conflict to `CODEX_ACTIVE_WRITER_UNRESOLVED`, bounded oversized native stdout/stderr while retaining byte count and SHA-256, and documented correct PowerShell zipapp invocation plus attempts-root semantics.
- Added explicit `4.3.1 → 4.3.2` schema-v8 adoption. Roles, CELL/D0/D1/D2, direct routes, optional Overwatcher/Temporal behavior, model bindings, BI authority and product state are unchanged; no scheduler, daemon, heartbeat, new role, Docker or product mutation was added.

## 4.3.1

- Rejected DSH construction before native start when the actual Git common store is outside the supported Worker root or its index/object/ref locations are not writable; supported standalone clones still pass.
- Closed Worker terminal outcomes as `completed`, `incomplete`, `blocked`, `execution_failure` or `timed_out`, forbade candidates on non-completed results, and installed one immutable exact-attempt completion inspector.
- Kept `D1_FAILED` Checker-owned while making the exact successor `REWORK_REQUESTED` Supervisor-owned and mechanically bound to the current failure event, candidate, scope, attempt and round.
- Made Codex active-writer recovery follow bounded turn pagination and require exactly one current turn before one payload-hash-bound recovery message.
- Gave each Overwatcher pause/resume occurrence a distinct append-only incident identity and required normal cycles to continue their bounded central-state wait in the same foreground turn.
- Replaced monolithic OCRV review cliffs with ordered durable capacity-sized segments and one aggregate D1; timeout now preserves completed evidence and returns a truthful incomplete result.
- Added context-restoration revalidation against central Run/plan/TOKEN facts plus a mechanically checked 15-Skill producer/consumer, authority, outcome, writability, timeout, continuity, migration, package, BI and Temporal-off audit.
- Preserved schema v8, the existing topology and direct fallback. Explicit `4.3.0 → 4.3.1` adoption does not resume or mutate a product Run; no Docker, BoM, heartbeat, scheduler, new role or product change was introduced.

## 4.3.0

- Added two optional reusable Temporal templates, `SLK.Start` and `SLK.Run`, for deterministic Run startup and exact delivery/native-start-ACK continuity. They preserve existing Supervisor/Checker/Worker/Overwatcher authority and do not decide D0/D1/D2, move TOKEN, write BI, switch models, install a server or require Docker.
- Added closed dependency-light startup/delivery/ACK contracts, one-attempt adapter activities, bounded timeout recovery through the bound Overwatcher or original sender, local real-service workflow tests, and an explicitly optional Windows setup/fallback guide. Core SLK remains fully usable without the SDK or service.
- Closed the RC08 field gaps: explicit invalid `evidence_id` diagnostics, substantive `revise-plan` validation, unambiguous `REWORK_REQUESTED` state versus `D1_REWORK_DIRECTIVE` transport vocabulary, and direct recovery for the native `already has an active writer` response.
- Packaged and hash-bound the complete Temporal template tree while keeping the five core artifacts, 15 Skills, schema v8, role topology, direct routes, DeepSeek V4 Flash Worker and disabled BoM unchanged.

## 4.2.11

- Added one Supervisor-authenticated, idempotent `slk-state close-role` action for the exact terminal Checker or Worker. It appends `ROLE_CLOSED`, retires the endpoint, revokes the credential, and sets the role lifecycle to `exited` in one transaction without a successor or TOKEN movement.
- Made LE BI and `slk-bi-query roles` derive `archived` from the central exited lifecycle, so a closed Run cannot leave its Checker/Worker visibly ready; planned archival or native-session absence is not presented as completed archival.
- Added fail-closed coverage for open Runs, wrong authority, wrong role/credential, TOKEN holders, nonterminal projections, and conflicting replay. Existing D1/D2/RUN_CLOSED evidence, Supervisor identity, Overwatcher close path, schema v8, and method topology remain unchanged.

## 4.2.10

- Replaced post-turn delayed self-wake and fixed-time promises with one auditable message to the exact active canonical Codex task/turn; preserved the failed attempt and kept Owner/Main activation as the truthful fallback.
- Closed the Worker suffix gaps: strict UTF-8/UTF-16LE DPAPI decoding rejects embedded NULs, resumed DSH identity is re-injected, OCRV starts headless outside the resumed Worker job, command exit/JSON/business outcomes stay distinct, and the committed runtime revision is returned.
- Slimmed Checker handoff evidence to essential receipts plus a hash/size/path index for retained raw logs; Checker keeps one formal D1, serial internal inspection segments, and does not mechanically fail low-only observations.
- Kept Overwatcher to three explicit exits and exposed binding, native liveness, cycle/incident pause, and terminal closure as separate read-only LE BI facts without changing engineering progress.
- Kept Cargo filter reuse inside one safe command session where sandbox identity would otherwise relink; added no scheduler, heartbeat, daemon, background Agent, BoM route, role, database migration, or product mutation.

## 4.2.9

- Added a second, mutually exclusive `resume-overwatcher-turn` basis for the latest exact non-`IN_PROGRESS` native status receipt. It restores the same role/Session/binding after a recorded continuity violation, resolves that incident and advances runtime once without creating a replacement.
- Kept the existing latest-anomalous-cycle resume path and ordinary `ACTIVE`/`IN_PROGRESS` cycle gate unchanged. Both/neither basis, stale runtime, older status, wrong identity/turn, replacement, new Session and non-Supervisor requests fail closed.
- Clarified that `OVERWATCHER_CONTINUITY_VIOLATION` belongs to native status/incident records, while `OVERWATCHER_ACTIVE_DEGRADED` is the `ACTIVE` + `IN_PROGRESS` cycle anomaly; documented the exact absolute-path/SHA-256 terminal evidence reference without adding a role, scheduler, heartbeat, daemon, workflow engine, BoM route or BI mutation.

## 4.2.8

- Added one Supervisor-authorized, exact-binding `rotate-overwatcher-credential` recovery for a lost or mis-saved one-time Overwatcher write secret. It changes only the current credential ID/hash and one runtime revision; role, Session, foreground turn, binding revision, TOKEN, engineering history, continuity and BI remain unchanged.
- Renamed bind/replace/rotate output fields to `overwatcher_credential_id` and one-time `overwatcher_write_credential`, with `ONE_TIME_NON_REPLAYABLE` delivery semantics. Credential IDs cannot authenticate, replay fails closed, and immediate exact-role authentication is required.
- Added the closed rotation schema, append-only schema-v8 audit receipt, 4.2.7 bridge recovery/adoption guidance and focused failure coverage without adding a role, scheduler, heartbeat, daemon, workflow engine, BoM route or product mutation.

## 4.2.7

- Added compact Worker and Checker role-local preflight. Either role may sequence its own work into internal segments, while the formal CELL, D1 attempt, TOKEN, role topology, and single final D1 verdict remain unchanged.
- Rebound stale Codex Desktop executable paths to the current installed `codex.exe` with immutable evidence, and read active writer state before any `thread/resume` call.
- Aligned `slk.ocrv-d1-request/v1` with the installed OCRV 1.12.7 closed request contract; the OCRV-generated review invocation remains in the result rather than being injected as an unknown request field, and Windows timeout cleanup terminates the wrapper process tree without opening a console.
- Allowed a missing Worker result repository only to fall back to the authenticated immutable Worker endpoint `cwd`, while future result contracts include that repository explicitly.
- Made exact continuation retries reuse the first immutable event bytes and original `occurred_at`, and clarified the 240-second Overwatcher report/pause/recover-existing-members boundary.
- Preserved the 4.2.6 LE BI behavior and stable project colors without adding a scheduler, heartbeat, daemon, BoM route, role, D2 action, or product mutation.

## 4.2.6

- Enlarged all visible LE BI typography to 120% through shared text tokens without scaling icons, window controls, or progress segments; active Run lists remain unscrolled through five entries and use a five-row vertical viewport from the sixth entry onward; independent projects now receive stable immutable-ID-derived tints from an eight-tone quiet palette.
- Repaired the LE BI release chain: `custom-protocol` is explicit and default, the artifact builder uses `tauri build --no-bundle`, release/package validation rejects Vite development entrypoints, and a deployed BI no longer depends on localhost:1430.
- Corrected the LCaS CELL03 recovery gaps without changing SLK topology, CELL/D0/D1/D2 semantics, model policy, BI authority, or the accepted product candidate.
- Added Supervisor-authorized same-Session Overwatcher foreground-turn resume after an anomalous cycle; prior cycles remain immutable and new/unauthorized Sessions fail closed.
- Bound Worker completion inspection to exact run/CELL/attempt/candidate/message identity and normalized rework `acceptance_criteria` into Checker D1 criteria.
- Active-writer recovery now reads and steers the existing turn without `thread/resume`; detached Windows transport is headless and breaks away from a one-shot Worker job so the Checker host owns long OCRV review lifetime.
- Clarified that code/test completion is not Worker role completion, transport failure is INCOMPLETE/`TRANSPORT_FAILED` in the same D1 attempt, and Overwatcher reports then pauses without implementing, judging, or idle-looping.

## 4.2.5

- Prompt correction deployment: made the Overwatcher use LLM judgment to distinguish normal progress, reasonable waiting, and anomalous stalls; detailed member inactivity, timeout, missing handoff, skipped D1, premature D2, duplicate work, identity drift, and terminal-state anomalies without turning them into a state machine.
- An anomalous Overwatcher cycle must now send one complete actionable report to Supervisor, then stop inspecting and end the active turn until Supervisor explicitly wakes the same Session after recovery; unchanged anomalies no longer justify repeated deep cycles or token burn.
- Added the repository-wide Agent-first/Skill-first correction rule: role-semantic failures are corrected through the relevant sub-Skill plus concise main-Skill guidance, while cross-Agent communication, identity, TOKEN, durable evidence, central state, and BI remain lightweight standardized Tools exposed through documented CLI/MCP/API contracts. Heavy orchestration must be compared with mature engines instead of being rebuilt inside SLK.
- Closed the 4.2.4 authority gap: Supervisor can only send a closed `WORKER_COMPLETION_RECOVERY` to the original registered OCRV Checker; deterministic native Checker start remains pending/unauthorized until the Checker credential proves the exact role and runtime revision, after which the same DSH Session may run the bounded Worker-owned suffix.
- Removed the public direct `resume-worker-continuation` command, added closed Checker recovery request/result contracts, and packaged a reversible two-file OCRV wrapper integration without changing the accepted D1 adapter or installing dependencies.
- Added read-only Overwatcher cadence inspection so a projected active role cannot stand in for continuing 180–300 second cycles. One missed interval wakes the same binding; more than two intervals requires Supervisor recovery review, with no heartbeat, daemon, timer, automatic replacement, or state mutation.
- Added explicit `4.2.4 → 4.2.5` adoption that preserves roles, plan, TOKEN, engineering history, and a proven active Overwatcher. No model, topology, CELL, D0/D1/D2, BI authority, product, or live R3B/OCRV state is changed.

## 4.2.4

- Closed the DSH terminal-without-handoff gap with a bounded same-Session Worker continuation: the original Checker resumes the exact recorded DSH instance/session, while the Worker process alone decrypts its DPAPI credential, writes idempotent `WORK_STARTED`/`D0_COMPLETED`/`CANDIDATE_SUBMITTED`, activates OCRV, verifies exact start evidence, reads a fresh runtime revision, and commits TOKEN atomically.
- Added `inspect-worker-completion` and a hash-bound Overwatcher cycle invariant. A running Worker and one cadence measured from trustworthy terminal evidence remain clear; a terminal Worker still holding TOKEN without the current CELL/attempt handoff after that cadence must report `WORKER_COMPLETION_HANDOFF_MISSING` and `COMMUNICATION_RECOVERY_REQUIRED` on every unresolved cycle. Old-CELL D1 evidence cannot mask it, and a prior notification suppresses only another notification.
- Added read-only exact role authentication, 4.2.4 idempotent event replay with conflict rejection, explicit `4.2.3 → 4.2.4` adoption that preserves an active Overwatcher, closed continuation/inspection schemas, and negative role Evals. No scheduler, heartbeat, daemon, new role, BoM path, product mutation, or automatic model change was introduced.
- The Worker DPAPI broker now strictly accepts both existing UTF-8 credentials and PowerShell-provisioned UTF-16LE credentials with one terminal NUL, while malformed encodings and non-`slk_` credential shapes remain rejected.

## 4.2.3

- Added immutable hash-bound DSH/OCRV task files, early native `started.json`, bounded Git workspace preflight, and atomic `commit-delivery-start` so start receipt, TOKEN, event, and one runtime revision cannot drift apart.
- Added active-Supervisor recovery by a new message bound to the exact active turn; inactive-target exact retry remains one replay of the original identity, while terminal output can never backfill missing start evidence.
- Mechanically preserved the 4.2.2 Overwatcher design—one optional Session/foreground turn for the whole Run, not per CELL—while separating cadence lateness from native liveness and adding hashed cycle evidence, continuity incidents, authorized non-overlapping replacement, and terminal final-cycle closure.
- Added explicit `4.2.2 → 4.2.3` adoption that preserves TOKEN and engineering history, plus closed JSON contracts and revision-bound read projections. Model selection is unchanged, automatic upgrades are rejected, and BoM remains disabled.
- Added a complete locally verifiable package and transactional Windows installer with rollback; no LCaS/R3B data, service, scheduler, heartbeat, broker, or remote publication is introduced.

## 4.2.2

- Added Owner-evidenced, exact-snapshot `reconcile-run-identities` for explicitly named independent historical roots, with atomic archive metadata and immutable receipts.
- Added explicit `adopt-method-contract` for `4.1.1|4.2.0|4.2.1 → 4.2.2`, preserving origin version, TOKEN, roles, evidence, CELL and D0/D1/D2 history.
- Made identity projections accept cross-root canonical/history relationships only while the stored reconciliation receipt still matches current metadata.
- Gated active Overwatcher binding to open Runs on effective 4.2.1 or 4.2.2 and required historical Runs to adopt the supported contract before binding.
- Kept both administration operations narrow: no title inference, direct SQLite editing, old-credential invention, replacement Run, orchestration layer, BI mutation, or LCaS state change.

## 4.2.1

- Replaced the withdrawn 4.2.0 event-woken Overwatcher semantics with one dedicated Agent Session that keeps a foreground active turn and completes the fixed eight-part observation cycle every frozen 180–300 seconds.
- Added append-only cycle evidence, strict Session/turn/cadence/checklist/TOKEN/event binding, read-only BI projection, and fail-closed blocking of new dispatch or handoff after two missed cycles.
- Kept normal cycles quiet and preserved the original Supervisor↔Checker↔Worker routes, engineering ownership, optional zero-Overwatcher path, exact retry, and terminal Session archive.
- Explicitly rejected heartbeat, Codex automation, cron, Windows Scheduled Task, daemon, service, detached helper, hidden/background Agent, or second observer as substitutes for the active Session.

## 4.2.0 — WITHDRAWN / DO NOT ENABLE

This local-only candidate was never tagged or released. Its event-woken, end-turn Overwatcher wording could not guarantee the Owner-required continuously active Agent Session and is superseded by 4.2.1.

- Fixed the native engineering topology to Codex Supervisor, OCRV Checker, and DSH Worker with fail-closed runtime/model/session/adapter validation; prompt role-play and Codex substitutions are rejected.
- Distinguished D1 INCOMPLETE from formal FAIL and added one closed rework exception: OCRV escalates a bound failure to Supervisor, Supervisor issues a structured directive to the same Worker without taking over D1, and ordinary Supervisor→Worker dispatch remains rejected.
- Added one optional, Supervisor-selected Overwatcher Agent Session per Run for sparse operational observation, exact-message recovery, and semantic escalation; it is dedicated to that Run, archived at closure, and has no engineering, TOKEN, or BI authority.
- Preserved the original Supervisor ↔ Checker ↔ Worker direct communication and event-driven TOKEN path; absence of Overwatcher does not block dispatch, inspection, recovery, or closure.
- Added immutable inspect/one-shot exact-retry recovery, explicit Run predecessor lineage and conservative duplicate/orphan identity projection, without a daemon, broker, message bus, or workflow engine.
- Added a closed 40-case role Eval with 8 runtime-critical cases per role and fail-closed normal/optimized validation for missing, extra, stale, mutated, or falsely claimed answers.
- Applied hidden/no-window Windows process launch to transport, Codex App Server, DSH, OCRV, and drill helpers; retained bounded fake-clock activation instead of long sleeps or positive-duration `wait_threads`.
- Corrected LE BI so delivery never increases D1 acceptance, D1 PASS waits for the next CELL until the required set is complete, and operational observations can invalidate stale activity without changing engineering progress.

## 4.1.1

- Made existing v1/v2 state-store upgrades create and validate a database backup before migration.
- Made every required schema step run in one immediate transaction so a failed upgrade leaves the original database version and contents intact.
- Documented the explicit writable migration step that precedes read-only Agent queries and LE BI after a machine-level upgrade.

## 4.1.0

- Simplified the public SLK hierarchy to `Run → CELL`; retained the original state grouping fields only as a backward-compatible storage detail.
- Rebuilt the desktop surface as compact read-only **LE BI** with one row per SLK, expandable roles/models and CELL facts, active-work durations, stable CLK/GLK source grouping, and an immediate archive for closed, abandoned, or superseded Runs.
- Added Run name, description, source identity, explicit supersession, and coexistence of multiple open SLKs within one project without automatic replacement.
- Aligned CLK composition and GLK Node groups with the same SLK identity while keeping all upper-level Chain/Node logic outside BI.

## 4.0.0

- Preserved the SLK 3.x Supervisor, Checker, Worker, Run, GO, CELL, D0, D1, D2, rework, exemption, communication, and model-selection method while adding durable cross-Agent execution state.
- Added the authenticated `slk-state` CLI, one configurable machine-wide SQLite authority, append-only authored history, SLK TOKEN transitions, role replacement and session rebound history, plan revisions, resource contention/recovery facts, durable evidence, and deterministic Markdown export.
- Added the read-only `slk-bi-query` Agent API and a standalone Tauri/React desktop BI over the same eight versioned projections, with no credential, mutation, dispatch, acknowledgement, repair, exemption, shell, network-service, updater, or telemetry surface.
- Accepted two concurrent Runs with six distinct role instances, full TOKEN paths, D0/D1/D2 closure, replacement, rebound, correction, evidence, and resource recovery without state crossover or repository writes.
- Accepted light, dark, and compact BI views with conservative status language: stored facts never claim current process liveness or native delivery by themselves.
- Added one compact resource-continuity Skill and the `slk-cargo` route for per-Run Cargo isolation, bounded explicit-lock recovery, and exact Run-runtime cleanup without changing the three-role Loop.

## 3.0.8

- Clarified model selection as an ordered decision across Owner choices, role baselines, each current CELL's concrete difficulty, and observed rework signals; defined when a CELL is clearly small and retained the normal Worker baseline whenever that judgment is uncertain.
- Scoped Worker model escalation to the current CELL, aligned repeated D1 and D2 repair thresholds with CELL replanning, and kept Checker and Supervisor capability stable unless the Owner chooses otherwise.
- Added focused negative guidance against binding an SLK Run to one-conversation Goal continuation or imposing one-size-fits-all numeric CELL quotas.
- Added optional RTK, Probe CLI, and Ponytail guidance for both Worker and Checker: install once in the Codex-wide environment, obtain an Owner decision per Run, use explicit non-hook/non-MCP operation, preserve raw evidence, and fall back to native tools without stopping SLK.
- Retained all 13 Skills and the existing Supervisor, Checker, Worker, CELL, D0, D1, D2, rework, token, communication, and record structure.

## 3.0.7

- Defined the existing visible cross-thread handoff message as the Run's one current `SLK TOKEN`, with a compact monotonically increasing identity and the state needed by the next existing Loop node.
- Clarified that a real token transfer activates the recipient directly without a token-specific acknowledgement round; backend text, old running indicators, token ownership and stale progress do not prove live execution.
- Made stale or duplicate token identities non-operative, kept communication recovery on the original token identity, and retained the single root Run record as the full engineering history.
- Preserved all 13 Skills and their existing line counts. No role, approval layer, database, service, state file, dashboard, runtime monitor or external workflow engine is added.

## 3.0.6

- Added one compact, independent negative-prompt section to each of nine Skills with demonstrated misreadings, using direct “Do not…” reminders rather than inline explanatory notes or a second workflow.
- Paired prompt maintenance corrections with corresponding negative reminders, while preserving the complete-CELL Loop, role ownership, isolation, proportionate inspection and minimum-construction guidance from 3.0.5.
- Corrected Supervisor recording timing: preserve important activation facts and volatile failure evidence before further adjustment, then finish the record before handoff; no daily member monitoring or per-command audit is added.
- Distinguished local D0 draft attempts from Worker D1 rework, and real creation/archive results from declarations or submitted operations; unexecuted work remains unexecuted, not failed or proved absent.
- Retained all 13 Skills and the existing root-record template. The recording Skill remains 36 lines, unchanged from released 3.0.5; no eval platform, Temporal runtime, extra role, inspection layer or authorization gate is introduced.

## 3.0.5

- Focused D0, D1 and D2 on proportionate product evidence through existing entrances or direct operation rather than building a checking system before work; genuine uncovered risks still require checks and insufficient evidence is not PASS.
- Distinguished checking-tool/environment failures from product defects, removed the duplicate D2 checklist, and scoped rework checks to the fix and affected regressions while reusing still-valid objective evidence rather than prior PASS conclusions.
- Kept complete failure, rework and exemption history as concise facts and evidence references, without recursive checker-proof materials or bulk log copies; retained all 13 Skills and reduced their combined length from 535 to 526 lines.
- Kept D0, D1, and D2 as layered inspection and excluded inspection-only CELLs from the construction plan; only implementation work required by findings becomes CELL construction.
- Added midstream adoption guidance that preserves and reuses completed work, then plans the reasonable minimum construction needed to reach the current target without duplicate work, premature unrelated work, or unnecessary global refactoring.

## 3.0.4

- Clarified CELL sizing so later CELLs, especially those that join or fuse earlier work, normally retain more headroom and are split smaller when practical.

## 3.0.3

- Clarified that one Checker dispatch carries one complete CELL and is not a command queue.
- Clarified that Worker commands, tool results, and intermediate progress do not end the CELL; the Worker continues until a complete candidate, real blocker, or necessary clarification.

## 3.0.2

- Defined SLK first as the linear form of Loop Engineering, with repeated CELL dispatch, construction/D0, candidate, isolated D1, PASS-or-rework, and final D2 closure.
- Clarified that a receipt confirms delivery but does not finish the recipient's assigned Loop node, without adding roles, controls, or Skill lines.

## 3.0.1

- Clarified that every role ends its current activity after dispatch, delivery, or boundary work and is reactivated only by a real message.
- Removed ambiguous progress-state and bounded-wait wording that could encourage `wait_threads` monitoring and contaminate later D1 or D2 judgment.

## 3.0.0

- Reframed SLK as one lightweight router plus 12 situational sibling Skills.
- Restored three visible conversations: Supervisor, Checker, and Worker.
- Simplified verification to minimum Worker D0, isolated Checker D1, and combined-result Supervisor D2.
- Replaced Control modes, Verifier, Patrol, runtime indexes, fixed model bindings, Pin policy, capacity gates, D3, and Owner acceptance receipts in the active method.
- Added model/device/headroom-aware CELL planning, state-aware communication recovery, upper-level member recovery, and Supervisor Run adjustment.
- Added one readable root Run record with per-role entries for progress, errors, rework, exemptions, evidence, D2, and archive state.
- Kept Supervisor event-activated rather than continuously involved in the Checker/Worker CELL loop.
- Ordered D1 and D2 evidence so Worker conclusions and detailed CELL history do not lead the independent judgment.
- Routed generic root-cause diagnosis to existing Debug Skills instead of duplicating one inside SLK.
- Added a situational role-model selector: stronger professional coding models for Supervisor and Checker, with a reliable Worker model that may be one capability tier lower for a suitable CELL.
- Completed the final consistency audit: role models now precede initial CELL sizing; root-record creation and Checker readiness sit in their real startup positions; visible creation authority, Owner model choice, Worker-to-Checker recovery, and D2 readiness agree across the collection.
- Marked every companion Skill as SLK-only in both discovery metadata and its opening guidance so it is not mistaken for a standalone engineering method.
- Shifted operational language toward situational recommendations and recovery paths so ordinary deviations lead back to construction.

## 2.6.0

- Replaced fixed model assumptions with one versioned, immutable
  `MODEL_BINDING_TRACE` for the existing SLK roles and scopes.
- Made Terra + `xhigh` the default for technical roles and non-authoritative Patrol.
- Allowed Luna only for Worker execution of an explicitly fine-grained/LOW-risk
  CELL, and Sol only for high-difficulty correction, root-cause diagnosis, or
  complex rework.
- Added capability-class/equivalence evidence for non-reference substitutes and
  retained separate role bindings when roles use the same actual model.
- Rejected GPT 5.5/lower, inferred `ultra`, cost/convenience downgrade reasons,
  ordinary-work Sol, unevidenced substitutes, and silent model/effort switches.
- Bound runtime readiness, dispatch index, Patrol receipts, CELL Contracts, and
  technical receipts to current model evidence without adding a router, role,
  conversation, or D4.

## 2.5.1

- Added a machine-validated, zero-business-call causal experiment preflight for
  concrete identifier format, request shape, authority seeds, and one-SQLite/
  one-Repository/no-reset topology.
- Made invalid fixture or newly leased harness assertions zero-credit and
  correctable within the same authorized checkpoint when product meaning,
  authority, and the active hypothesis remain unchanged.
- Added the preflight receipt template and validator, and bound the policy into the
  D0 receipt template and control kernel.

## 2.5.0

- Added the Worker-only four-level wake ladder for the frozen Checker, scoped
  GO/CELL n/N delivery messages, matching `WAKE_ACK`, deterministic temporary
  heartbeat, and Patrol-readable `PENDING_WAKE` fallback.
- Prohibited positive-timeout/looped Supervisor waits and added exactly one visible
  non-authoritative Run Patrol conversation/heartbeat using
  `gpt-5.6-luna` + `xhigh`.
- Bound all positive Supervisor waits (including one-shot/outside-loop), loops, and
  wait-all to fixed Patrol alerts; only timeout-zero snapshots are normal.
- Bound frozen workload `LOW/MEDIUM/HIGH` to 10/15/30-minute Patrol intervals and
  required the complete unique minimum-error checklist in every patrol cycle.
- Defined visible peer tasks and planning “subtasks” separately from prohibited
  spawned, delegated, hidden, or background agents.
- Added receipt-derived layered progress: Worker delivery position, Checker D1
  acceptance, and Supervisor D2 GO/Run milestones with versioned denominators.
- Bound every D2/D3/Owner material verdict to exactly one later Supervisor progress
  event using event/receipt/verdict identity; GO candidate readiness is unique per
  Required-set version and binds the final D1 acceptance event.
- Added versioned device capacity and cumulative engineering load, total-cost
  `CELL_CAPACITY_GATE`, dynamic feedback, `CELL_SCOPE_EXCEEDED`, post-dispatch split
  defects, and severe 3+ successor re-evaluation.
- Added default-deny task Pin capability for the SLK Control responsibilities and
  Worker, with non-technical Patrol denied separately; Owner-only provenance and
  immutable Pin-then-Unpin history remain enforced.
- Added lightweight `RUN_RUNTIME_INDEX` completeness validation for dispatch-bound
  RUN/GO/CELL/ROUND capacity PASS, wake, progress, and current complete Patrol
  evidence.
- Added one closed runtime schema, explicit optimized-safe validator, fail-closed
  templates, simulation gate, tests, mirrors, and migration/reference material.
- Preserved Control + persistent Worker as the formal engineering topology and
  D0-D3/Owner authority. Patrol is a safeguard, not a third technical role.

## 2.4.0

- Added candidate-bound `DEFECT_LINEAGE` and repair-round records to D1 failures
  and D0 repair candidates.
- Required evidence-backed reproduction or documented non-reproduction, one active
  root-cause hypothesis, one minimal experiment, and root cause before product
  change.
- Added defect-only, risk-proportional regression-first evidence: fail-before,
  pass-after, and regression coverage, or a Checker-approved exemption with
  alternative evidence.
- Added a hard gate after three Checker-rejected immutable repair candidates:
  ordinary rework stops and Control routes architecture review, method-boundary
  exit, or a versioned Contract revision.
- Kept the existing two-conversation topology and D0-D3 authority; no D4, role,
  general TDD mandate, Chain/Stage/Barrier, or graph activation was added.

## 2.3.1

- Preserved the canonical `Small Loop Skill` identity and exactly two visible
  conversations: one Control and one persistent Worker.
- Added non-interchangeable Supervisor, Checker, and Verifier responsibility modes
  inside the Control Conversation; Checker owns D1 and Verifier owns D2/D3.
- Made every D0-D3 and Owner receipt template fail closed with canonical `PENDING`.
- Replaced assertion-only plan checks with strict serial-plan validation and stable
  error codes that remain active under `python -O`.
- Required D2 PASS for every current Required GO; formal resolution now changes the
  Required set only through a versioned Baseline Amendment.
- Added minimum auditable Receipt Envelopes, Current/Active pointers, candidate
  invalidation, known-risk security hard brakes, Manifest verification, Windows CI,
  and a complete MIT License.
- Kept Calabash and centralized project security audit under LCCoding ownership.

## 2.3.0 (withdrawn draft)

- This draft was never approved for installation or release because it contained
  success-by-default receipts, weak validation, an undefined D2 bypass, incomplete
  release integrity, and an unresolved identity/topology change.

## 1.9.1

- Replaced brittle exact free-text readiness grading with deterministic public
  multiple-choice packets and stable `choice_id` submissions.
- Preserved the 25/25 threshold, hidden answer-key boundary, seeded question order,
  and fail-closed receipt behavior.

## 1.9.0

- Added mandatory Full/Minimum Calabash for product-affecting runs and a narrow
  technical exemption.
- Defined Supervisor and Checker as non-interchangeable responsibilities inside one
  Control Conversation.
- Required independent Checker worktree/sandbox and runtime-state isolation.
- Restored Worker ownership of product rework; deprecated ambiguous `REDO`.
- Added `PROJECT_AUTONOMY_ENVELOPE` and prohibited routine Owner confirmation.
- Added `GO_CALABASH_TRACE`, `GO_EVIDENCE_CONTRACT`, GO-boundary acceptance, and
  cross-GO CELL dependency prohibition.
- Added tiered detection and clarified final composition audit.
- Updated method boundaries to Chain Loop Skill (CLK) and Graph Loop Skill (GLK).
