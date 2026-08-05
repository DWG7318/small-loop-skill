# Migration to SLK 2.5.0

## From 2.4.0

Active Runs never silently adopt 2.5.0. At a versioned boundary, preserve existing
D0-D3/Owner receipts, then freeze:

- one `RUN_RUNTIME_CONTRACT` binding the original Control/Worker, Checker thread and
  host, Required sets, one Patrol conversation/heartbeat, and available wake
  capabilities;
- one `gpt-5.6-luna` + `xhigh` Patrol with frozen
  `LOW→10`/`MEDIUM→15`/`HIGH→30` interval and a complete per-cycle checklist;
  Patrol is a safeguard and receives no D0-D3, product, routing, progress, or
  Pin/Unpin authority;
- Supervisor's no-positive-wait policy and Worker-only scoped wake ladder;
- current receipt-derived progress snapshot and Required-set version;
- versioned `DEVICE_CAPACITY_PROFILE`, `CUMULATIVE_ENGINEERING_LOAD`, and a
  pre-dispatch capacity gate for every undispatched CELL;
- default-deny Pin policy for the three Control responsibilities and Worker, plus a
  separately denied Patrol and current related-task Pin audits;
- one `RUN_RUNTIME_INDEX` covering every formal RUN/GO/CELL/ROUND dispatch with a
  capacity PASS bound to that Round, wake, delivery progress, and complete
  Patrol-cycle evidence;
- a complete `RUNTIME_SIMULATION` PASS with immutable evidence.

If a pre-dispatch CELL splits, version and recompute the Required denominator without
adding D1 acceptance. If execution already exceeded budget, record
`CELL_SCOPE_EXCEEDED`/`POST_DISPATCH_CELL_SPLIT`; 3+ successors require
`CELL_OVERSIZE_SEVERE` and remaining-plan/device-budget re-evaluation.

Existing Owner-manual Pins remain legal when provenance is proven. Unknown Pins are
reported to Owner and are not automatically changed. An unauthorized historical Pin
remains recorded even if the task is now unpinned.

## From 2.3.1

- Preserve the same two formal engineering conversations, responsibility modes, and
  D0-D3 authority. Add only the 2.5.0 non-authoritative Run Patrol safeguard; do not
  create a repair role, D4 receipt, or another verification conversation.
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

Every Run continues to use exactly two formal execution conversations: one Control
and one persistent Worker. In 2.5.0 it also uses one visible non-authoritative Run
Patrol safeguard. Control declares exactly one active responsibility mode for each
formal decision:

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
