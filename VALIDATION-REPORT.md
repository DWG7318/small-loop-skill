# Validation Report — SLK 4.2.2 Candidate

Date: 2026-09-22

Branch: `feature/slk-4.2.2-run-identity-recovery`

## Accepted scope

SLK 4.2.2 preserves the bounded serial Run, fixed Supervisor↔Checker↔Worker topology, optional foreground-active Overwatcher, `SLK TOKEN`, CELL, D0/D1/D2, rework, direct communication and acceptance authority. It adds only two state-administration operations: explicit historical Run identity reconciliation and explicit method-contract adoption.

The canonical Run's current Supervisor supplies closed Owner evidence and exact optimistic snapshots. Reconciliation atomically archives only the named sources and appends an immutable receipt. Adoption supports only `4.1.1|4.2.0|4.2.1 → 4.2.2`, preserves `origin_slk_version`, requires no active Overwatcher and appends a separate immutable receipt. Neither operation changes plan, role, credential, TOKEN, CELL, D0/D1/D2, evidence or work-event history.

## Verification gates

- Rust workspace: 79 passed (`cargo test --workspace --all-targets`).
- Python suite: 205 passed (`python -m pytest -q`).
- Optimized-mode administration and role-Eval negatives: 26 passed (`python -O -m pytest -q tests/eval/test_role_eval.py tests/state/test_state_cli.py`).
- Skill collection: all 15 directories passed; the role-Eval pack validated all 44 cases.
- LE BI: 17 tests passed; TypeScript typecheck and production UI build passed.
- Workspace format and strict clippy (`-D warnings`) passed.
- Repository/Manifest, full baseline diff, mirror, sensitive-information and scope-boundary checks passed after final Manifest generation.

## Critical negative evidence

- title/project/time similarity never selects or merges Runs;
- direct SQLite editing, invented old credentials, replacement Runs and free-text version claims are not administration paths;
- missing/wrong Owner decisions, malformed hashes, unknown JSON fields, empty/duplicate/self sources, wrong project, stale event/TOKEN/holder/count fields and changed receipt replays fail closed;
- a receipt-backed cross-root projection becomes `ORPHANED_IDENTITY` if the recorded archive metadata or immutable source facts drift;
- adoption rejects unsupported versions, stale snapshots, missing/wrong reconciliation receipts, active Overwatchers and silent version mutation;
- unadopted 4.1.1 Runs cannot bind an active Overwatcher; 4.2.1 compatibility and explicit 4.2.2 adoption remain valid;
- administration does not discover Runs implicitly, expose credentials, add a BI mutation route, create a scheduler/heartbeat/runtime, or touch LCaS state.

## Release boundary

This report establishes a local 4.2.2 candidate. It does not claim a merge, push, tag, GitHub Release, LCaS state mutation, Overwatcher binding, CELL dispatch or product execution. Local machine-wide deployment is performed only after every candidate gate passes; remote publication remains a separate Owner-authorized action.
