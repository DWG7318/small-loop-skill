# SLK Control Kernel And Hardening Design

## Objective

Make SLK easier to execute without weakening its single-loop topology. Add one
SLK-only CLI-like control contract, remove initial timed start, replace ambiguous
free-form control with explicit transitions, and close the release, reference,
and context-index gaps found in the 1.7.0 audit.

This design belongs only to SLK. It does not import MSLK files, schemas, states,
tests, role ownership, or commands.

## Non-Goals

- No executable terminal binary.
- No shared control kernel or third repository.
- No subagents, hidden roles, second Worker, or separate Checker.
- No dynamic switch to another loop method.
- No initial timed start.

## Files And Boundaries

- `contracts/slk-control-kernel.json`: canonical machine-readable states,
  commands, transitions, errors, and required audit fields.
- `references/slk-control-operations.md`: human execution instructions for the
  combined Supervisor/Checker.
- `SKILL.md`: concise mandatory summary and conditional reference link.
- `tests/test_control_kernel.py`: model-based positive and negative scenarios
  loaded from the SLK JSON contract.
- `tests/test_contract.py`: role, documentation, link, version, and line-budget
  contracts.

No file in this list is shared with MSLK. Similar behavior is intentionally
defined and tested again under SLK ownership.

## Public Command Contract

SLK accepts only:

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

`SLK START` is the only initial-start command and is never scheduled. It is valid
only after method selection, plan approval, `SIMULATION_PASS`, detection-profile
approval, and continuation checks. It creates exactly one fresh visible Worker
and dispatches the prepared first CELL.

Timed commands apply only after the loop has started:

- `PAUSE ...` stops new dispatch at a safe CELL boundary.
- `PAUSE AFTER <accepted-cell-count>` uses the absolute project-wide accepted
  CELL count, not a relative increment.
- A time or count trigger may mature during an active CELL, but it only changes
  the state to `PAUSE_PENDING`; the active CELL still finishes normally.
- `RESUME AT ...` is valid only for an existing paused Worker.
- `RESUME NOW` unarchives that same Worker after revalidation.
- `CANCEL SCHEDULE` cancels a pending pause or resume, never active work.
- `STATUS` is read-only and never creates, wakes, archives, or dispatches a role.

Any MSLK-prefixed, generic `LOOP`, timed `START`, pair-targeted, or unknown command
is rejected.

## State Model

Canonical states are `NOT_STARTED`, `RUNNING`, `PAUSE_SCHEDULED`,
`PAUSE_PENDING`, `PAUSED`, `RESUME_SCHEDULED`, `BLOCKED`, `COMPLETE`, and
no others. No implicit state is permitted.

Key invariants:

- `NOT_STARTED -> RUNNING` requires `SLK START` and creates the sole Worker.
- Active CELL work is never interrupted.
- Pause becomes effective only after validation and any required repair by the
  combined Supervisor/Checker.
- Resume uses the same archived Worker and never creates another Worker.
- `COMPLETE` requires final acceptance and optional Goal satisfaction.
- Invalid transitions change no state and dispatch no work.

## Execution Receipt

Every command produces one `SLK_CONTROL_RECEIPT` containing command ID, normalized
command, actor, pre-state, trigger, target, prerequisite evidence, action, result,
post-state, schedule version, and progress snapshot. Repeating the same command
ID is idempotent and cannot duplicate a transition or assignment.

Rejected commands return a receipt with one canonical outcome:
`INVALID_COMMAND`, `INVALID_STATE`, `PRECONDITION_FAILED`, `SCHEDULE_CONFLICT`, or
`ALREADY_APPLIED`. Rejection preserves state, schedule, progress, and role
visibility.

## Scenario Verification

Tests load the JSON contract and verify at least:

- valid initial manual start;
- rejection of timed initial start;
- safe pause during an active CELL;
- pause at accepted-CELL threshold without overshoot;
- resume of the same Worker;
- rejection of resume before first start;
- cancellation and duplicate-command idempotency;
- rejection of MSLK, generic, and pair-targeted commands;
- blocked prerequisites produce no dispatch;
- completion cannot be reopened by a control command.

The tests must validate state transitions, not only string presence.

## Context And Release Hardening

`WORK_CONTINUATION_INDEX` becomes a bounded mutable current-state pointer, not an
append-only history. Keep it below 200 lines with current plan/version, active
semantic shard, predecessor, current GO/CELL, invariants, unresolved decisions,
latest accepted evidence, and next action. Historical detail remains in linked
semantic shards.

Generic relative-Markdown-link tests start from `SKILL.md` and the contract
manifest and ensure every reachable reference exists, remains inside the
repository, is at most 1000 lines, and is mode-correct. Every governed reference
must be reachable; orphan contract references fail validation.

README must not hardcode a rule count. SLK gains canonical owner/repository ID,
default branch, mode identity, and release-version metadata. Publication requires
matching `VERSION`, README version, canonical metadata, pushed HEAD, and annotated
`v1.8.0` tag.

## Acceptance

- All SLK Markdown files are at most 1000 lines; target `SKILL.md` below 900.
- No initial timed start remains.
- Exactly one Worker can ever exist in one SLK run.
- Command and scenario tests pass independently of MSLK.
- Global install equals the repository by tracked-file hash.
- Remote `main` and annotated `v1.8.0` identify the same release commit.
