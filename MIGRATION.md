# Migration to SLK 2.5.0

## From 2.4.0

- Preserve the same two visible conversations, one persistent Worker, and D0-D3
  authority. Worker signal continuity adds no role or conversation.
- Give every formal CELL dispatch one durable `dispatch_id` and record one ordered
  `ACK → PROGRESS* → (BLOCKED | FINAL)` stream.
- Treat unread terminal signals as `BLOCKED_UNREAD` or `COMPLETED_UNREAD`; do not
  redispatch, advance progress, or provision another Worker.
- Ingest a terminal signal once with `CONTROL_SIGNAL_INGESTION`, atomically syncing
  route, Run state, visible progress, and Owner-visible status.
- Allow redispatch only after `TASK_NOT_DELIVERED_PROVEN`, always to the same
  persistent Worker with explicit authority.
- Map thread registry, unknown-conversation, IPC, and app-server continuity failures
  to `CONTROL_DISCONNECTED`; recover original bindings before resuming.

## From 2.3.1

- Preserve the same two visible conversations, responsibility modes, and D0-D3
  authority. Do not create a repair role, D4 receipt, or another verification
  conversation.
- On a D1 defect failure, create one candidate-bound `DEFECT_LINEAGE` with a stable
  failure fingerprint, reproduction evidence, and repair-round count.
- Before product repair, record evidence-backed reproduction or documented
  non-reproduction, one scalar active root-cause hypothesis, and one minimal
  experiment in D0.
- For stably reproducible and reasonably automatable defects, bind fail-before,
  pass-after, and risk-scaled regression evidence. Otherwise record the exemption
  reason and alternative evidence for Checker approval.
- Count only Checker-rejected immutable repair Candidates. A failed hypothesis is
  investigation evidence, not a repair Candidate. At three rejected repairs, stop
  ordinary CELL rework and route architecture review, method-boundary exit, or a
  versioned Contract revision.

## Identity and topology

SLK remains **Small Loop Skill**. `Serial Loop Kit` is not a canonical rename.

Every Run continues to use exactly two visible conversations: one Control and one
persistent Worker. Control now declares exactly one active responsibility mode for
each formal decision:

```text
SUPERVISOR_RESPONSIBILITY
CHECKER_RESPONSIBILITY
VERIFIER_RESPONSIBILITY
```

Checker signs D1. Verifier signs D2 and D3 from clean validation environments. The
Verifier mode is not a third visible conversation and SLK does not claim blind
conversation-memory isolation.

## From 1.9.1

- Replace SLK-owned Calabash gates with a frozen LCCoding `RUN_CONTRACT` input.
- Replace Checker GO acceptance with Verifier D2 GO verification.
- Replace Supervisor final technical audit with Verifier D3, followed by bounded
  Run Owner Acceptance.
- Convert legacy accepted states into explicit D0-D3 receipts only after validating
  the exact current candidate; do not inherit green status by name.
- Preserve accepted historical evidence append-only and record its legacy version.

## From the withdrawn 2.3.0 draft

- Change every blank success value to `PENDING`.
- A Required GO must receive D2 PASS. Formal resolution may only cancel, remove, or
  supersede a GO through a versioned Baseline Amendment before it leaves the current
  Required set.
- Use the strict Serial Plan validator, Receipt Envelope, state pointers, Manifest
  verification, complete MIT License, and cross-platform CI supplied by 2.3.1.

Active Runs never reinterpret historical receipts silently. Freeze a new baseline,
identify invalidated evidence, and resume from the earliest affected GO.
