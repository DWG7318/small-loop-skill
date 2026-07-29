# Migration to SLK 2.3.1

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
