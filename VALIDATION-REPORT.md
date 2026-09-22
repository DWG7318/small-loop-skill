# Validation Report — SLK 4.2.3 Candidate

Date: 2026-09-23

Branch: `feature/slk-4.2.2-run-identity-recovery`

## Accepted scope

SLK 4.2.3 hardens runtime consistency without changing the bounded serial Run, fixed Codex Supervisor ↔ OCRV Checker ↔ DSH Worker topology, `SLK TOKEN`, CELL, D0/D1/D2, rework or direct communication. It preserves the 4.2.2 rule that one Run may bind at most one dedicated Overwatcher Session: that one foreground turn stays active for the whole Run, while 180–300 second cycles are append-only observations rather than per-CELL confirmations.

The candidate adds early native-start evidence, immutable transport task files, atomic delivery-start/TOKEN/runtime snapshots, exact active-Supervisor recovery with a new message, Git workspace preflight, revision-bound Overwatcher cycles and terminal closure, deterministic packaging, and transactional local installation with rollback. BoM remains disabled and no automatic model upgrade exists.

## Verification gates

- Independent disposable sandbox: PASS. Disposable fake-runtime and state fixtures proved direct inactive wake, active-writer new-message recovery, start-before-terminal, one atomic delivery-start revision, exactly one Overwatcher binding/session/foreground turn across three cycles, `LATE + IN_PROGRESS` without false inactivity, final-cycle terminal close, zero BoM routes and zero model-change events.
- Python suite: 227 passed (`python -m pytest -q`).
- Optimized-mode runtime suite: 154 passed (`python -O -m pytest -q tests/eval tests/transport tests/state tests/install`).
- Rust workspace: 91 passed (`cargo test --workspace --all-targets`).
- Rust formatting and strict clippy passed (`cargo fmt --all -- --check`; `cargo clippy --workspace --all-targets -- -D warnings`).
- LE BI: 17 tests passed; TypeScript typecheck and production UI build passed.
- Package and rollback tests passed inside the Python suite, including staged corruption with restoration of every managed root.
- Repository/Manifest, full baseline diff, mirror, sensitive-information and scope-boundary checks are rerun after every final report/Manifest update.

## Critical negative evidence

- a terminal process result cannot be reinterpreted as native-start evidence;
- an active Supervisor cannot receive an exact replay of the failed message: recovery uses one new auditable message bound to the exact active turn;
- a 4.2.3 delivery cannot move TOKEN through the legacy handoff path, stale runtime revision or hash-drifted evidence;
- an Overwatcher cycle cannot use another session, foreground turn, binding revision, runtime revision, TOKEN snapshot or unverified evidence file;
- a late cycle with native `IN_PROGRESS` is recorded as late but not misclassified as inactive;
- the whole-Run Overwatcher cannot be closed at a CELL/GO boundary or rebound once per CELL; terminal close requires the exact final cycle and runtime revision;
- a second Overwatcher binding, reused Session, missing active turn, overlapping replacement, silent 4.2.2 reinterpretation, BoM route and model upgrade all fail closed;
- a Worker task cannot start against a non-Git, missing or unwritable workspace identity;
- installation cannot accept a missing/extra/hash-drifted package member and restores the prior complete installation on staged failure.

## Sandbox evidence

The repository-local execution report is generated at `.codex/.tmp/slk-4.2.3-sandbox-compact-final/report.json` and is intentionally excluded from the shipped Manifest. It names only disposable roots under that sandbox output and does not read or modify LCaS/R3B state.

## Release boundary

This report establishes a local 4.2.3 candidate. It does not claim a merge, push, tag or GitHub Release. Machine-wide replacement of the installed 4.2.2 copy occurs only after candidate gates pass, through the verified transactional installer and an independent post-install smoke against disposable state. No LCaS R3B/CELL03 action is part of this work.
