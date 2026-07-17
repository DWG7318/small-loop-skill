---
name: small-loop-skill
description: Use when the user says SLK or small-loop-skill, or when one bounded project needs exactly one visible Worker conversation controlled by one combined Supervisor/Checker. Never trigger together with MSLK.
---

# Small Loop Skill (SLK)

Use `SLK` as the official abbreviation. Keep `$small-loop-skill` as the Codex
invocation name.

Run exactly one stable small loop:

```text
Owner -> Supervisor/Checker <-> Worker
```

The loop has one Worker. The Worker may own several GO phases, and each GO may
contain several CELLs, but only one CELL is executable at a time.

This Worker must own a result that can be inspected and accepted independently.
SLK deliberately launches no parallel Worker.

## Single-Loop Boundary

SLK always uses:

- one combined Supervisor/Checker;
- one Worker;
- one governed, versioned solution and GO/CELL plan;
- one append-only method-log chain;
- one final result queue.

Do not create a separate Checker or a second Worker. If the work requires
multiple independent Workers, fail the SLK simulation and return the decision
to the Owner. Do not activate MSLK inside the same run.

## Exclusive Mode Lock

Choose exactly one method before role creation: SLK or MSLK. Once SLK is
selected for a project run:

- invoke SLK exactly once;
- do not load, invoke, nest, repeat, alternate with, or switch to MSLK;
- do not borrow MSLK role topology, parallel-Worker behavior, Checker pairing,
  or any other MSLK capability;
- do not present SLK and MSLK as interchangeable or generally combinable.

Shared rules never transfer role ownership, topology, messages, state, or
capabilities between SLK and MSLK. Implement every common requirement entirely
inside the selected SLK role structure. Mentioning MSLK for prohibition does not
load it or authorize any of its behavior.

If SLK is the wrong method, record `METHOD_SELECTION_FAILED`, stop without
formal work, and ask the Owner to start a new, separate run with an explicit
method choice. The current run never converts itself into MSLK.

## Visible Conversation Only

Every Supervisor/Checker and Worker role must be a visible Codex conversation
under the same project. Hidden execution is forbidden.

- Never use a subagent, sub-agent, background agent, hidden worker,
  `delegate_task`, or any subagent-dispatch capability.
- Never represent an internal tool call, background job, or invisible execution
  context as the Worker.
- Confirm the visible Worker conversation belongs to the current project before
  assigning the first CELL.
- Keep formal assignments, receipts, repair records, and completion messages in the
  visible project conversations.

### Visible Conversation Lifecycle

- Create or unarchive a role conversation only when an authorized formal task
  is ready for that role.
- Keep the conversation visible while that task is active.
- Archive it immediately when its authorized work is complete and no formal
  task remains assigned.
- If later work is authorized for the same role in the same project, unarchive
  the existing conversation instead of creating a duplicate.
- Unarchiving a conversation does not repeat the SLK invocation and does not
  permit MSLK activation.
- An archived conversation performs no hidden or background work.

## Mandatory Simulation Gate

Run a no-side-effect simulation before formal work. Planning and simulation may
inspect metadata, but must not edit project files, execute implementation
commands, call external services, create formal Worker assignments, or start a
CELL.

The simulation must:

1. confirm SLK is the sole selected method and has not been invoked already;
2. model one visible same-project Supervisor/Checker and one visible Worker;
3. rehearse the first CELL assignment, Worker delivery, combined-role validation
   decision, and one `NEXT`, `REDO`, or `BLOCKED` route;
4. prove no subagent or MSLK capability is used;
5. validate ownership, write scope, evidence paths, model assignment, tests,
   safety gates, and heartbeat behavior.

Record either `SIMULATION_PASS` with the checked facts or `SIMULATION_FAIL` with
the reason. Formal work may begin only after `SIMULATION_PASS`. A failed or
missing simulation forbids role launch and CELL execution.

## Fresh Worker Requirement

Every new project must create a fresh visible Worker conversation under that
same project. Do not reuse a Worker from another project, even when the scope
looks similar; prior context can contaminate the new project's execution and
evidence.

Treat "new project" narrowly: reuse is allowed only for a continuation of the
same project identity, objective lineage, coordination records, and evidence
chain. A renamed, copied, adjacent, or merely similar project is new and must
receive a fresh Worker.

## Model Policy

The combined Supervisor/Checker must use `gpt-5.6-sol` with `xhigh` reasoning.

Workers may use only:

- `gpt-5.5` with `high` reasoning as the minimum;
- `gpt-5.6-sol` with `high` reasoning as the maximum.

During planning, assign a Worker model and reasoning level to every CELL based
on task type, difficulty, risk, tool burden, and validation burden. Prefer
`gpt-5.5 high` for routine bounded implementation and `gpt-5.6-sol high` for
complex integration, architecture-sensitive work, or difficult diagnosis.
Record the assignment in the CELL plan before launch.

The Supervisor/Checker may change the Worker model as evidence changes the task
classification. Record the change before dispatch. Never assign a Worker below
`gpt-5.5 high`, above `gpt-5.6-sol high`, or at a reasoning level other than
`high`.

## Role Contract

### Role Authority Matrix

| Responsibility | SLK owner |
| --- | --- |
| Method gate, project plan, GO/CELL plan, and GO revision | Supervisor responsibility inside the combined Supervisor/Checker |
| CELL assignment, validation, and routing | Checker responsibility inside the same combined Supervisor/Checker |
| Worker-result repair | Supervisor responsibility inside the combined Supervisor/Checker |
| Project progress and final queue | Combined Supervisor/Checker |
| CELL execution | Worker |

These are responsibilities inside exactly two visible roles: one combined
Supervisor/Checker and one Worker. The functional distinction never creates a
separate Checker, extra Worker, or MSLK-style pair.

### Supervisor/Checker

The controlling thread combines Supervisor and Checker, owns the overall
result, and handles ordinary CELL traffic.

- Translate Owner intent into the Worker objective and acceptance target.
- Produce or approve the solution, GO map, CELL index, and detailed CELL files.
- Own evidence-driven GO review and revision as a Supervisor responsibility.
- Create exactly one Worker and no separate Checker.
- Maintain the supervisor board and the same-thread Overseer heartbeat.
- Resolve plan defects, Owner decisions, shared-resource issues, and genuine
  blockers that cannot be resolved inside the current authorized plan.
- Write the final queue and perform final local acceptance.

The combined Supervisor/Checker controls the one loop but must not silently
take over ordinary Worker execution.

- Read the complete current solution and versioned GO/CELL plan.
- Package and send exactly one CELL at a time.
- Inspect files, diffs, tests, scans, method logs, and boundaries locally.
- Route `NEXT`, `REDO`, `COMPLETE`, `BLOCKED`, or `PLAN_DEFECT`.
- Move to the next GO only after every CELL in the current GO is accepted.
- Write the final passed or blocked queue record.

The combined role must not add or alter a GO ad hoc, renumber historical work,
weaken acceptance, or change Worker scope silently. GO changes are allowed only
through the evidence-driven revision rule below.

### Worker

The Worker executes only the current formal CELL.

- Work only from a formal task sent by the Supervisor/Checker.
- Stay inside the allowed and forbidden scopes defined by the CELL.
- Preserve unrelated Owner or existing project changes.
- Maintain append-only method evidence.
- Run required checks and return evidence to the Supervisor/Checker.
- Never self-select the next CELL and never accept its own delivery.

## Supervisor Repair Duty

The Supervisor/Checker must repair every defect found in a Worker's delivered result.
It must not send a repair task back to the Worker. In SLK this is the Supervisor
responsibility inside the combined Supervisor/Checker role.

The repair must not change the GO/CELL objective, architecture ownership,
acceptance standard, Owner decision, credentials, or external side effects.

For each repair, the Supervisor/Checker must:

1. Preserve the Worker delivery and record the defect.
2. Make the minimum correction.
3. Run the same required checks.
4. Append repair evidence without rewriting Worker history.
5. Accept the CELL only after local verification passes.
6. Send the next formal CELL with a concise repair update in the same message.

If the repair is broad or ambiguous, split it into bounded controller-owned
repair steps. If safe repair exceeds current authority or changes the plan,
record `PLAN_DEFECT`, `BLOCKED`, or an Owner decision; never return the repair to
the Worker. If no usable Worker result exists at all, the original CELL may be
re-dispatched as an original task, not as a repair task. If it is the final CELL,
write the final queue after verification.

## GO And CELL

Use GO for a phase and CELL for the smallest inspectable work package.

- GO: `GO-01`, `GO-02`.
- CELL: `CELL-01.01`, `CELL-01.02`, `CELL-02.01`.
- Round: `GO-01/CELL-01.01/R01`.
- Never renumber after launch.

GO scope follows project need and must not be reduced for device capacity. A GO
represents the required project outcome regardless of the current computer.

CELL size must be kept modest enough for the current computer to execute and
verify reliably. Reduce files touched, command fan-out, runtime, and evidence
volume per CELL when device capacity is limited. Split the same GO into more
CELLs instead of shrinking the GO or weakening acceptance.

The structure is:

```text
Worker
  -> GO-01
      -> CELL-01.01
      -> CELL-01.02
  -> GO-02
      -> CELL-02.01
```

Before launch, provide:

1. One solution file with objective, boundaries, architecture, risks, and
   acceptance.
2. One GO file with every phase and dependency.
3. One CELL index and one detailed file per CELL.

Every CELL must define objective, inputs, allowed scope, forbidden scope,
outputs, checks, evidence, dependencies, Worker model/reasoning assignment,
and completion criteria.

## Evidence-Driven GO Revision

After every GO is completed and checked, the Supervisor responsibility within
the combined Supervisor/Checker must compare the accepted plan with the actual
result, including delivered scope, defects, residual risk, new dependencies,
changed estimates, and incomplete outcomes.

The Supervisor owns the resulting GO revision proposal and may:

- adjust any subsequent GO that has not started;
- add a supplementary GO for a historical GO when the completed result exposes
  missing, corrective, or follow-up work;
- revise the future CELL map and model assignments affected by that change.

The Worker must not revise GO or CELL plans. The combined role approves the
Supervisor's proposal only after confirming that it stays within the Owner
objective, one-Worker boundary, acceptance standard, and safety gates.

GO revision is append-only and versioned:

- never rewrite the historical GO, its evidence, or its acceptance result;
- retain existing identifiers and add a revision or supplement identifier such
  as `GO-03-R1` or `GO-03-S1`;
- record the triggering evidence, reason, old/new scope, dependencies,
  acceptance criteria, affected CELLs, and Owner decision when required;
- keep the revision within the selected SLK method, Owner objective, one-Worker
  boundary, and existing safety gates.

Before dispatching a revised or supplementary GO, run a no-side-effect delta
simulation and record `GO_REVISION_SIMULATION_PASS`. Without that record, the
revision remains proposed and no formal CELL may start.

## Loop Protocol

The normal path is direct:

```text
Supervisor/Checker -> Worker -> Supervisor/Checker -> Worker -> ... -> final queue
```

Worker tasks must start with:

```text
Formal task: GO-01/CELL-01.01/R01
```

Controller-owned repair evidence starts with `Repair record:` and is never a
Worker assignment. `REDO` means the Supervisor/Checker repairs and revalidates
the delivery; it does not send correction work back to the Worker. Messages
without the formal task heading are discussion, not executable Worker work.

## Mandatory Progress Display

Every formal task assignment from the Supervisor/Checker to the Worker must
include exactly one project progress line after the task details:

```text
正在完成 GO-03：35/231
```

The GO identifier is the GO of the newly assigned CELL. The numerator counts
accepted CELLs only, after any required Supervisor repair and local validation.
Assigned, running, delivered-but-unchecked, blocked, revoked, and duplicate CELLs
do not count as complete. Count each accepted CELL identifier exactly once.

The denominator is the total CELL count in the current versioned plan across all
GO, including accepted historical CELLs and every active remaining CELL. After
an approved GO revision or historical-GO supplement, recompute the denominator,
record the old and new totals in the revision ledger, and never reduce it below
the accepted count. The numerator never decreases.

The Supervisor/Checker recomputes this snapshot immediately before every formal
task assignment and continues displaying it until project completion. When all
CELLs are accepted and no next task exists, the final queue must display:

```text
全部完成：231/231
```

After finishing a CELL, the Worker sends the Supervisor/Checker:

```text
完成，请检验
```

The Worker's final visible reply must also be exactly `完成，请检验`. This means
ready for validation, not accepted. Do not actively wait or continuously poll
after sending a task or receipt.

## Mandatory Overseer

Starting SLK requires one recurring Overseer heartbeat attached to the current
Supervisor thread while the loop remains unfinished.

- Choose 15 minutes for short/light CELLs.
- Choose 30 minutes for medium projects or mixed device-safe CELL runtimes.
- Choose 60 minutes only for large projects, many CELLs, or an inherently long
  verification command that cannot be split safely.
- Record the heartbeat id and interval on the supervisor board.
- Never create a detached conversation or replacement loop from the heartbeat.
- Remove or disable the heartbeat after final Supervisor acceptance.

At each heartbeat, inspect once:

1. Supervisor board and current GO/CELL.
2. Supervisor/Checker and Worker state and latest turn.
3. Latest formal task, repair record, receipt, or queue record.
4. Method-log/artifact timestamp when state is ambiguous.

Classify the loop as `active_worker`, `active_checker`,
`waiting_for_worker_delivery`, `waiting_for_checker_validation`, `blocked`,
`stalled`, or `complete`.

If neither execution side is genuinely active and the loop is unfinished, the
heartbeat wakes the combined Supervisor/Checker with exactly one required next
action. Never tell the Worker to select new work. If the environment cannot
create a same-thread heartbeat, report the missing capability and do not
substitute detached automation.

## Evidence And Queue

Use project-local coordination paths unless the project defines others:

```text
coordination/
  plans/
  checker-messages/
  worker-method-logs/
  supervisor-board.md
  final-queue/
```

Method logs are append-only. Rotate before 999 lines or when sealing a damaged
or completed shard. Every new shard cites the previous shard and its hash.

Only the Supervisor/Checker writes the final record:

```text
SLK_YYYYMMDD-HHMMSS_<worker>_<plan-version>_<result>.md
```

Valid results are `passed`, `blocked`, `plan-defect`, `owner-decision`, and
`stopped`. The Worker is complete only after a passed record exists and the
combined Supervisor/Checker's final audit accepts it.

No generated coordination Markdown file may exceed 999 lines.

## Recovery Rules

- Delayed thread registration: confirm a returned thread ID before replacement.
- Duplicate role: keep the current Supervisor/Checker and one Worker, stop or archive any separate Checker or duplicate Worker, and
  ensure each CELL executes once.
- Worker `systemError`: inspect and repair any usable partial result. Only when
  no usable result exists may the original CELL be re-dispatched unchanged.
- Damaged log: seal it, start a new shard, preserve the incident, and revalidate
  current artifacts.
- Repeated defect: continue bounded controller-owned repair, then escalate a
  real blocker or plan defect; never return correction work to the Worker.
- Dynamic shared data: distinguish external drift from current-CELL writes;
  do not chase perpetual fixed hashes.

## Launch Checklist

Before launch, confirm:

- `SIMULATION_PASS` exists for this exact plan and role roster.
- SLK is the sole method, was invoked once, and no MSLK capability is present.
- Every role is a visible conversation under the same project; no subagent,
  hidden worker, or background agent exists.
- Every role conversation has work ready, and every no-work conversation is
  archived with an explicit unarchive path for later same-project work.
- One complete solution/GO/CELL plan exists.
- The GO revision ledger is present; every completed GO has an evidence review,
  and every revised or supplementary GO has `GO_REVISION_SIMULATION_PASS`.
- The current thread is the combined Supervisor/Checker and exactly one Worker is assigned.
- The receipt target, method-log path, and final queue are unique.
- Tests, scans, safety boundaries, and external-action gates are explicit.
- Every CELL declares an allowed Worker model and reasoning level.
- The combined Supervisor/Checker is `gpt-5.6-sol xhigh`; every Worker is from
  `gpt-5.5 high` through `gpt-5.6-sol high` according to task type.
- GO scope follows project need; every CELL is sized for reliable execution on
  the current computer without weakening GO acceptance.
- Every formal task displays `正在完成 GO-NN：accepted/total`, and the final queue
  displays `全部完成：total/total`.
- The supervisor board identifies the Worker and current CELL.
- A 15/30/60-minute same-thread heartbeat is active and recorded.
- The heartbeat will be removed after final acceptance.
- No second Worker or parallel pair is hidden in the plan.
- The role authority matrix is unchanged; no MSLK role, pair, state, or message
  route has been borrowed.

Then the combined Supervisor/Checker sends the first formal CELL to the Worker
and performs periodic oversight, validation, routing, and final acceptance.
