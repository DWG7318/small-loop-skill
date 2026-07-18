# SLK Control Operations

This reference belongs only to SLK. It never authorizes MSLK topology, commands,
states, pairing, or parallel execution.

## Command Surface

Accept only these literal forms:

```text
SLK START
SLK STATUS
SLK PAUSE NOW
SLK PAUSE AFTER <accepted-cell-count>
SLK PAUSE AT <RFC3339-time>
SLK RESUME NOW
SLK RESUME AT <RFC3339-time>
SLK CANCEL SCHEDULE
```

`SLK START` is manual only. It requires current `SLK_READINESS_EVAL_PASS`
receipts for the exact combined Supervisor/Checker and sole Worker, an approved
plan, `SIMULATION_PASS`, approved GO detection profiles, and passing continuation
conditions. It authorizes the first formal CELL for the same prepared Worker.
It never creates a second Worker.

## Dispatch Boundary

Complete every controller-side check, record, and message field before dispatch.
Sending the formal assignment is the combined Supervisor/Checker's final action
and enters `OFFLINE_WAITING_WORKER_SIGNAL`. The role then ends its turn and does
not poll, inspect, run status, or perform periodic oversight of the active Worker.
It wakes only for `WORKER_COMPLETION_RECEIPT`, `WORKER_BLOCKER_RECEIPT`, or
`WORKER_EXECUTION_FAILURE`. A next assignment repeats this final-action rule.

`SLK STATUS` is read-only and may run only while the combined role is already
legitimately awake. It must not create, wake, archive, schedule, or dispatch a role.

## Safe Pause

`SLK PAUSE AFTER N` uses the absolute project-wide accepted CELL count. It does
not mean N additional CELLs. Check the threshold after every CELL acceptance and
before every new assignment.

A time or count trigger may mature during an active CELL. Change the state to
`PAUSE_PENDING`, let the Worker finish normally, validate the delivery, perform
any Supervisor-owned repair, record acceptance evidence, and only then enter
`PAUSED`. Archive the Worker when no next authorized work is ready. Never
interrupt an active CELL.

## Same-Worker Resume

Resume only an existing paused SLK. `SLK RESUME NOW` and `SLK RESUME AT ...`
reuse the same visible Worker conversation. Revalidate the plan, readiness
receipts, simulation currency, detection profile, and continuation conditions
before dispatch. A replacement Worker, a second Worker, or a resume before the
first manual start is `INVALID_STATE` or `PRECONDITION_FAILED`.

`SLK CANCEL SCHEDULE` cancels a pending pause or resume. It never interrupts an
active CELL, reopens `COMPLETE`, or dispatches work.

## Rejection

Reject MSLK-prefixed commands, generic `LOOP` commands, timed initial start,
pair-targeted forms, unknown forms, invalid states, and unmet prerequisites.
Rejection changes no state, schedule, role visibility, progress, or dispatch.

The canonical results are `INVALID_COMMAND`, `INVALID_STATE`,
`PRECONDITION_FAILED`, `SCHEDULE_CONFLICT`, and `ALREADY_APPLIED`.

## Receipt

Every command emits one `SLK_CONTROL_RECEIPT` with:

```text
command_id
normalized_command
actor
pre_state
trigger
target
prerequisite_evidence
action
result
post_state
schedule_version
progress_snapshot
```

The command ID is idempotent. Repeating it returns `ALREADY_APPLIED` and cannot
repeat a transition or assignment. A receipt never treats a paused loop as
complete and never reopens `COMPLETE`.
