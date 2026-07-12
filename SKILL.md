---
name: small-loop-skill
description: Run one bounded project Block through exactly one supervised Checker-Worker loop. The official abbreviation is SLK; use this skill when the user says SLK or small-loop-skill, or when one coupled workstream should progress through multiple GO phases and sequential CELLs with periodic Supervisor oversight, direct Checker repair, append-only evidence, and final acceptance. Do not use for multiple independent parallel Blocks; use MSLK instead.
---

# Small Loop Skill (SLK)

Use `SLK` as the official abbreviation. Keep `$small-loop-skill` as the Codex
invocation name.

Run exactly one stable small loop:

```text
Owner -> Supervisor -> Checker <-> Worker
```

The loop owns one Block. The Block may contain several GO phases, and each GO
may contain several CELLs, but only one CELL is executable at a time.

## Single-Loop Boundary

SLK always uses:

- one Supervisor;
- one Block / workstream;
- one Checker;
- one Worker;
- one fixed solution and GO/CELL plan;
- one append-only method-log chain;
- one final result queue.

Do not create a second Checker or Worker pair. Do not run multiple Blocks in
parallel. If the work genuinely requires independent parallel Blocks, stop
before launch and use MSLK.

## Role Contract

### Supervisor

The Supervisor owns the overall result and stays outside ordinary CELL traffic.

- Translate Owner intent into the Block objective and acceptance target.
- Produce or approve the solution, GO map, CELL index, and detailed CELL files.
- Create exactly one Checker/Worker pair.
- Maintain the supervisor board and the same-thread Overseer heartbeat.
- Resolve plan defects, Owner decisions, shared-resource issues, and genuine
  blockers the Checker cannot resolve inside the fixed plan.
- Perform final local acceptance after the Checker writes a passed queue.

The Supervisor must not become the normal relay for Checker/Worker messages and
must not silently take over ordinary Worker execution.

### Checker

The Checker controls the one loop.

- Read the complete fixed solution and GO/CELL plan.
- Package and send exactly one CELL at a time.
- Inspect files, diffs, tests, scans, method logs, and boundaries locally.
- Route `NEXT`, `REDO`, `COMPLETE`, `BLOCKED`, or `PLAN_DEFECT`.
- Move to the next GO only after every CELL in the current GO is accepted.
- Write the final passed or blocked queue record.

The Checker must not add a new GO, renumber work, weaken acceptance, or change
the Block scope after launch. Route plan defects to the Supervisor.

### Worker

The Worker executes only the current formal CELL.

- Work only from a formal task or formal rework sent by the Checker.
- Stay inside the allowed and forbidden scopes defined by the CELL.
- Preserve unrelated Owner or existing project changes.
- Maintain append-only method evidence.
- Run required checks and return evidence to the Checker.
- Never self-select the next CELL and never accept its own delivery.

## Checker Direct Repair

The Checker may directly repair a Worker-caused defect only when the correction
is bounded, unambiguous, fully inspectable, and inside the current CELL.

The repair must not change the GO/CELL objective, architecture ownership,
acceptance standard, Owner decision, credentials, or external side effects.

For a direct repair, the Checker must:

1. Preserve the Worker delivery and record the defect.
2. Make the minimum correction.
3. Run the same required checks.
4. Append repair evidence without rewriting Worker history.
5. Accept the CELL only after local verification passes.
6. Send the next formal CELL with a concise repair update in the same message.

If the repair is broad or ambiguous, issue formal rework or escalate a plan
defect. If it is the final CELL, write the final queue after verification.

## GO And CELL

Use GO for a phase and CELL for the smallest inspectable work package.

- GO: `GO-01`, `GO-02`.
- CELL: `CELL-01.01`, `CELL-01.02`, `CELL-02.01`.
- Round: `GO-01/CELL-01.01/R01`.
- Never renumber after launch.

The structure is:

```text
Block
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
outputs, checks, evidence, dependencies, and completion criteria.

## Loop Protocol

The normal path is direct:

```text
Checker -> Worker -> Checker -> Worker -> ... -> final queue
```

Worker tasks must start with one of:

```text
Formal task: GO-01/CELL-01.01/R01
Formal rework: GO-01/CELL-01.01/R02
```

Messages without one of these headings are discussion, not executable work.

After finishing a CELL, the Worker sends the Checker:

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
- Choose 30 minutes for medium or mixed CELLs.
- Choose 60 minutes only for long/heavy CELLs.
- Record the heartbeat id and interval on the supervisor board.
- Never create a detached conversation or replacement loop from the heartbeat.
- Remove or disable the heartbeat after final Supervisor acceptance.

At each heartbeat, inspect once:

1. Supervisor board and current GO/CELL.
2. Checker and Worker thread state and latest turn.
3. Latest formal task, rework, receipt, or queue record.
4. Method-log/artifact timestamp when state is ambiguous.

Classify the loop as `active_worker`, `active_checker`,
`waiting_for_worker_delivery`, `waiting_for_checker_validation`, `blocked`,
`stalled`, or `complete`.

If neither role is genuinely active and the loop is unfinished, wake the
Checker with exactly one required next action. Never tell the Worker to select
new work. If the environment cannot create a same-thread heartbeat, report the
missing capability and do not substitute detached automation.

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

Only the Checker writes the final record:

```text
SLK_YYYYMMDD-HHMMSS_<block>_<plan-version>_<result>.md
```

Valid results are `passed`, `blocked`, `plan-defect`, `owner-decision`, and
`stopped`. The Block is complete only after a passed record exists and the
Supervisor's final audit accepts it.

No generated coordination Markdown file may exceed 999 lines.

## Recovery Rules

- Delayed thread registration: confirm a returned thread ID before replacement.
- Duplicate role: keep one Checker and one Worker, stop/archive duplicates, and
  ensure each CELL executes once.
- Worker `systemError`: inspect partial output and issue bounded rework for the
  same CELL; preserve valid work.
- Damaged log: seal it, start a new shard, preserve the incident, and revalidate
  current artifacts.
- Repeated defect: follow the fixed retry policy, then escalate a real blocker
  or plan defect.
- Dynamic shared data: distinguish external drift from current-CELL writes;
  do not chase perpetual fixed hashes.

## Launch Checklist

Before launch, confirm:

- One complete solution/GO/CELL plan exists.
- Exactly one Checker and one Worker are assigned.
- The receipt target, method-log path, and final queue are unique.
- Tests, scans, safety boundaries, and external-action gates are explicit.
- The supervisor board identifies the Block and current CELL.
- A 15/30/60-minute same-thread heartbeat is active and recorded.
- The heartbeat will be removed after final acceptance.
- No second Block or parallel pair is hidden in the plan.

Then send the complete plan to the Checker. The Checker sends the first formal
CELL to the Worker. The Supervisor begins periodic oversight and stays outside
ordinary Checker/Worker traffic.
