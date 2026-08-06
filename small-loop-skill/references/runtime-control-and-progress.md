# SLK 2.6.0 Runtime Control and Progress

This is the canonical operational reference for SLK 2.6.0 runtime safeguards.
`SKILL.md` and `SPEC.md` define authority; this reference defines the machine-
checkable records, sequences, messages, and fail-closed behavior. It never creates a
new Runtime method or changes D0-D3.

## 1. Topology

Formal execution remains exactly:

```text
CONTROL ⇄ WORKER
```

Each Run also has exactly one visible `RUN_PATROL` conversation and one heartbeat.
Patrol is a non-authoritative safeguard, not a third technical role. Control still
activates one of `SUPERVISOR_RESPONSIBILITY`, `CHECKER_RESPONSIBILITY`, or
`VERIFIER_RESPONSIBILITY`; the Checker receiver is that same Control task while in
Checker mode.

Patrol uses the default Terra capability class with `xhigh`. It has no implicit
Luna exception. Frozen workload class maps mechanically: `LOW→10`, `MEDIUM→15`, and
`HIGH→30` minutes. This is capacity/difficulty binding, not a risk-frequency
reinterpretation. Duplicate Patrol tasks or heartbeats fail closed.

## 2. Readiness

Before Worker dispatch, `RUN_RUNTIME_CONTRACT` must be `READY` and bind:

- Run/baseline/Required-set identities and hashes;
- Control, persistent Worker, original Checker thread/host, Patrol, and heartbeat;
- Worker send/read/list/unarchive, bounded ACK wait, temporary heartbeat
  upsert/delete, and `PENDING_WAKE` write capabilities as `AVAILABLE`;
- Supervisor wait prohibition;
- current device profile, cumulative load, and CELL capacity policy;
- default-deny Pin policy for the four SLK technical roles and, separately, Patrol;
- current versioned/hash-bound model trace and Patrol binding;
- frozen workload class and its exact Patrol interval.

Missing, `PENDING`, unavailable, unknown, or contradictory readiness evidence blocks
dispatch. `python scripts/validate_runtime_control.py <record.yaml>` validates one
record and returns a stable `SLK_RUNTIME_*` error on failure.

## 2A. Controllable model binding

`MODEL_BINDING_TRACE` is immutable, versioned readiness evidence. Every entry binds
one role instance and RUN/GO/CELL/ROUND scope to an actual model, GPT reference
model, capability class/equivalence proof, reasoning effort, selection level and
reason, and readiness/isolation/verification results.

The reference policy is:

| Selection | Allowed scope | Required evidence | GPT reference |
|---|---|---|---|
| `DEFAULT` | technical roles and non-technical Patrol | ordinary technical or Patrol work | `gpt-5.6-terra` + `xhigh` |
| `CELL_LOW_RISK_EXCEPTION` | Worker on exact CELL/Round | frozen fine-grained, LOW-risk CELL Contract | `gpt-5.6-luna` + `xhigh` |
| `HIGH_DIFFICULTY_ESCALATION` | technical role on bounded GO/CELL/Round | high-difficulty correction, root-cause diagnosis, or complex rework | `gpt-5.6-sol` + `xhigh` |

Cost, convenience, role importance, ordinary implementation, and ordinary checking
are not exception reasons. GPT 5.5 and lower are always forbidden. `ultra` requires
an exact item-specific Owner authorization reference; it cannot be inferred.

Another provider/model may replace the named GPT reference only with the matching
capability class, `PROVEN_EQUIVALENT`, and immutable equivalence evidence. The
validator never infers equivalence from free text. Run Patrol may use an explicit
Terra-class equivalent, but cannot use Worker Luna or technical Sol exceptions.

The same actual model may appear in multiple role bindings; binding IDs, authority,
candidate, environment, and receipt identity remain separate. A model or effort
change for one role/scope requires a contiguous new binding version that immediately
supersedes the prior binding, records reason/evidence, and reruns readiness,
isolation, and verification. Missing predecessor or revalidation evidence is a
silent switch and fails closed.

Every runtime-index dispatch names its current Worker binding. The index embeds the
current trace and verifies trace ID/version/hash, dispatch scope, and Patrol
model/effort identity. D0-D3 and Supervisor templates cite `model_binding_ref`; this
adds evidence binding, not another decision layer.

## 3. Worker-to-Checker wake ladder

Only Worker may initiate the ladder, and only for its frozen original Checker after
CELL delivery, `BLOCKED`, or `EXECUTION_FAILURE`.

The message is:

```text
<GO_ID> CELL <ordinal>/<Required-CELL-total> <state>，请检查
```

For normal delivery, `<state>` is `已交付`. The ordinal is the delivery position,
not D1 accepted count. Rework keeps the same CELL ordinal.

| Level | Offset | Required action | Maximum ACK wait |
|---|---:|---|---:|
| 1 | T+0 | send to frozen Checker thread+host | 120 s |
| 2 | T+120 | read/list, repair archive/host only from frozen registry, resend | 120 s |
| 3 | T+240 | create/update one deterministic temporary Checker heartbeat | 120 s |
| 4 | T+360 | write deterministic `PENDING_WAKE` | 0 s |

Level 2 never guesses an ID and never creates a replacement Checker. Level 3 never
creates a conversation. Tests use an injected clock; production records may cite
host timestamps but must preserve these bounds.

Checker's first action is:

```text
WAKE_ACK <RUN_ID> <GO_ID> <CELL_ID> <ROUND_ID>
```

A matching ACK or mechanical evidence that the original Checker started processing
stops all later levels. Temporary heartbeat is deleted and any `PENDING_WAKE` is
consumed. No second Worker/Checker, duplicate implementation, or duplicate
acceptance is allowed.

If levels 1-3 fail, level 4 records Worker/Checker/Run/GO/CELL/Round, the three
attempt errors and timestamps, and evidence. The unique Patrol discovers it from
its own heartbeat even if every best-effort message fails.

The repository-owner task completion receipt remains the separate plain text
`完成，请检验`; it is not a method runtime delivery message.

## 4. Supervisor wait

Supervisor never performs positive-timeout `wait_threads`, even once or outside a
loop; never loops it; and never waits for all members. A `timeoutMs: 0` snapshot or
`read_thread` is not a wait.
After dispatch/control, Supervisor ends its turn. Only Worker may perform the finite
ACK waits above.

## 5. Run Patrol

Every `patrol_cycle_id` contains every fixed check exactly once:

| Check | Normal evidence | Fixed alert when present |
|---|---|---|
| `FORWARD_MOTION` | legal movement or evidenced pause/block/external wait | `UNEXPLAINED_STALL` |
| `PENDING_WAKE` | no pending wake | `PENDING_WAKE_UNCONSUMED` |
| `SUBAGENT_EVIDENCE` | no prohibited Agent evidence | `SUBAGENT_MISUSE` |
| `SUPERVISOR_WAIT` | no wait or `timeoutMs:0` snapshot | `SUPERVISOR_WAIT_FORBIDDEN` |
| `PATROL_UNIQUENESS` | one Patrol and heartbeat | `DUPLICATE_PATROL` |
| `THREAD_PIN` | unpinned or proven Owner provenance | Pin fixed alert |
| `TERMINAL_CLOSURE` | Run non-terminal or Patrol closed in order | `PATROL_NOT_CLOSED` |

Each check has an enumerated finding/result, immutable evidence references, and its
fixed alert when required. Missing, duplicate, free-text substitute, or missed alert
fails closed.

Formal pause, legal `BLOCKED`, waiting for external conditions, and visible peer
tasks are normal when evidence binds the reason.

Patrol emits fixed status, evidence, and alert codes. It does not inspect code
quality, plan quality, D0-D3 sufficiency, or progress. It does not repair, take over,
route, dispatch, verify, accept, Pin, Unpin, create/fork tasks, or create/delegate
agents.

Terminal order is:

```text
LOOP_TERMINAL
→ delete Patrol heartbeat
→ PATROL_CLOSED
→ archive Patrol conversation
```

## 6. Task and subagent definition

`GO`, `CELL`, `Round`, plan step, “subtask”, and “子任务” are planning units.
A visible same-project peer task with stable `threadId` is not a subagent.

Only these are prohibited subagent evidence:

```text
spawn_agent
delegate_task
HIDDEN_AGENT
BACKGROUND_AGENT
```

`create_thread` and `fork_thread` remain forbidden to Patrol but are not
misclassified as subagent evidence.

## 7. Layered progress

### Worker layer

Worker reports only scoped delivery position to Checker. Delivery, green tests,
checking, rework, or a wake retry never increments acceptance.

### Checker layer

After ACK, Checker displays:

```text
收到 <GO_ID> CELL <n>/<N>，开始检查
```

After each D1 decision:

```text
PASS:        <GO_ID> CELL验收 <a>/<N>；下一状态=<...>
FAIL/REWORK: <GO_ID> CELL验收仍为 <a>/<N>；当前CELL进入<Rxx>返工
BLOCKED:     <GO_ID> CELL验收仍为 <a>/<N>；阻断=<...>
```

Only one current, non-invalidated D1 PASS for a Required CELL contributes to `a`.
Repeated receipts for the same CELL do not increment it.

When all current Required CELLs of one GO have D1 PASS, Checker may send one GO
boundary milestone to Supervisor:

```text
GO <ordinal>/<Required-GO-total>；
本GO CELL <N>/<N>已验收；
当前状态=GO_CANDIDATE_READY
```

`GO_CANDIDATE_READY`, `D2_VERIFYING`, and `D2_VERIFIED` are distinct.

### Supervisor layer

Supervisor reports Owner-visible progress only after material GO/Run state change:

```text
RequiredSet v<version>；
当前GO D1 CELL <accepted>/<required>；
Required GO D2 <verified>/<required>；
D3=<state>；
Owner=<state>
```

CELL numerator comes from current D1 PASS receipts. GO numerator comes from current
D2 PASS receipts. D3 and Owner Acceptance are separate. Verifier emits formal
verdicts only; Patrol reports no engineering progress.

Every event has a unique `event_id` plus an earlier `trigger_event_id`, formal
receipt/verdict binding where applicable, and immutable evidence. Each
`D2_VERIFIED`, `RUN_VERIFIED`, and `OWNER_ACCEPTED` event requires exactly one later
Supervisor-to-Owner `GLOBAL_PROGRESS` bound to that exact event and receipt.
Verifier verdicts do not substitute for Supervisor progress. Missing, duplicate,
wrong-order, or wrong-trigger progress fails closed. `GO_CANDIDATE_READY` remains the
single Checker-to-Supervisor GO-boundary milestone.

Each Required-set version after the initial set begins with exactly one ordered
Supervisor-to-Owner `AMENDMENT` progress event bound to its versioned receipt; it
recomputes denominators/numerators from current receipts. History is immutable. A
CELL split does not itself add accepted progress. Generic cross-layer “已完成” is
forbidden; use:

```text
DELIVERED
D1_ACCEPTED
GO_CANDIDATE_READY
D2_VERIFYING
D2_VERIFIED
RUN_VERIFIED
OWNER_ACCEPTED
BLOCKED
REWORK
```

## 8. Device and cumulative load capacity

Supervisor freezes a versioned `DEVICE_CAPACITY_PROFILE` before plan dispatch. It
uses measurable CPU/logical-core, available RAM, GPU/VRAM or explicit N/A,
free-disk/IO, network/external limits, process/port, device-safe concurrency,
command/test/build duration, context, and evidence budgets. “High performance” or
unknown capability is not evidence and fails closed.

Supervisor versions `CUMULATIVE_ENGINEERING_LOAD` at Run freeze, every important
SLK GO boundary, Required-set amendment, and material measured deviation. It binds
accepted-baseline file/dependency scale, build/full-regression duration, peak
memory/disk, evidence/hash volume, context restore, external tools, rollback/retry,
and coupling. SLK has no Level/Graph boundary.

Every CELL estimates total engineering cost:

- implementation, inputs/dependencies, and outputs;
- build/test matrix and Checker independent validation;
- affected regression;
- evidence/hash/cleanup and context loading;
- external tools/services and rollback/retry;
- cumulative baseline coupling and peak resources.

Diff or file count alone never determines CELL size.

Before dispatch, Checker reviews the Supervisor-frozen `CELL_CAPACITY_GATE`:

| Result | Dispatch | Meaning |
|---|---|---|
| `PASS` | yes | measured/conservative cost fits current capacity |
| `SPLIT_REQUIRED` | no | pre-split into independent D1-checkable CELLs |
| `CAPACITY_BLOCKED` | no | route through existing authority |

A pre-split preserves the original GO outcome/acceptance hashes, dependencies, and
verification quality. It creates no new GO, Worker, or subagent. Logical work
parallelism never overrides device-safe concurrency or SLK serial execution.

If actual scope exceeds the frozen budget, Worker stops, preserves an immutable
checkpoint/evidence package, emits `CELL_SCOPE_EXCEEDED`, and returns to original
Checker/Supervisor authority. Worker never self-splits.

A split discovered after dispatch records `POST_DISPATCH_CELL_SPLIT`. Three or more
successors records `CELL_OVERSIZE_SEVERE` and forces remaining-plan plus
device-budget re-evaluation; 6, 7, and 8 successors are always severe. Capacity
splits version the Required set and recompute progress without adding acceptance.

## 9. Owner-only task Pin authority

The SLK technical roles default to denied for `set_thread_pinned(true)` and
equivalent Pin capability:

```text
SUPERVISOR_RESPONSIBILITY
CHECKER_RESPONSIBILITY
VERIFIER_RESPONSIBILITY
WORKER
```

`RUN_PATROL` is not a technical role; its Pin and Unpin capability is denied and
validated separately.

Task creation, dispatch, ACTIVE, wait, `BLOCKED`, rework, verification, milestone,
importance, longevity, or frequent Owner viewing never grants authority. Pin is
independent of archive/unarchive and every lifecycle state. It cannot replace a
status board, progress report, role registry, or recovery index.

Legal provenance is one of:

- `OWNER_MANUAL_UI`: Owner directly chose Pin in Codex UI;
- `OWNER_EXPLICIT_ITEM_AUTHORIZATION`: current-Run evidence names the exact task.

An Agent/method Pin without the exact authorization records
`UNAUTHORIZED_THREAD_PIN`. The violation remains after a later Unpin. A pinned task
whose provenance cannot be proven records `PIN_PROVENANCE_UNKNOWN` and prompts
Owner. Patrol never automatically Unpins because the Pin may be Owner-authored.

`THREAD_PIN_AUDIT` binds current state and ordered operation history. Its Patrol
result is `NORMAL` for proven Owner provenance, otherwise one fixed alert:

```text
UNAUTHORIZED_THREAD_PIN
PIN_PROVENANCE_UNKNOWN
```

## 10. Run runtime completeness index

`RUN_RUNTIME_INDEX` is a versioned, lightweight completeness package, not a session
Runtime. It embeds the current `RUN_RUNTIME_CONTRACT`, `MODEL_BINDING_TRACE`, formal dispatch scopes,
capacity gates, wake traces, one progress trace, and the current complete Patrol
cycle. Every RUN/GO/CELL/ROUND dispatch scope must have exactly one current capacity
`PASS` bound to that ROUND, matching wake trace, matching Worker delivery progress,
and the unique current Patrol cycle. Each dispatch names its current Worker model
binding; the Patrol cycle names its current Patrol binding.
Missing, unindexed extra, duplicate, stale-version, or wrong-scope records fail
closed.

## 11. Simulation and records

`RUNTIME_SIMULATION` must contain every version-required scenario exactly once with
`PASS` and evidence. It includes all four wake outcomes, readiness failures,
Supervisor wait, Patrol/subagent/terminal cases, layered counts/amendments, capacity
growth/resource/split/deviation cases, and Pin authority/provenance/history cases.
It also covers complete Patrol cycles, workload/interval mapping, event-triggered
progress, extra-role rejection, complete Run index packages, Terra/Luna/Sol model
selection, equivalent substitutes, model floor/ultra rejection, role isolation,
and evidenced switch history.

Blank templates remain `PENDING`. The validator uses explicit conditionals, not
Python `assert`, so negative gates remain active under `python -O`.

The published assets are:

```text
contracts/slk-runtime-control.schema.json
scripts/validate_runtime_control.py
templates/run-runtime-contract.yaml
templates/device-capacity-profile.yaml
templates/cumulative-engineering-load.yaml
templates/cell-capacity-gate.yaml
templates/cell-capacity-event.yaml
templates/worker-wake-trace.yaml
templates/pending-wake.yaml
templates/run-patrol-receipt.yaml
templates/progress-trace.yaml
templates/runtime-simulation.yaml
templates/thread-pin-audit.yaml
templates/run-runtime-index.yaml
templates/model-binding-trace.yaml
```

These records augment D0/D1 and existing Run control. They create no D4, new
technical role, general message bus, model router, cost optimizer, device monitor,
scheduler, or Runtime method.
