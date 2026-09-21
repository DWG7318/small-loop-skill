# Validation Report — SLK 4.2.0 Candidate

Date: 2026-09-22

Branch: `feature/slk-4.2.0-overwatcher`

## Accepted scope

SLK 4.2.0 preserves the bounded serial Run, direct Supervisor↔Checker↔Worker communication, `SLK TOKEN`, D0/D1/D2, rework, and acceptance authority. It adds one optional, Supervisor-selected Overwatcher Agent Session per Run. The Overwatcher can append operational observations, inspect immutable transport evidence, request one exact replay, and escalate semantic decisions; it cannot relay normal work, hold TOKEN, write engineering facts, alter BI, or become required for progress.

The candidate also adds explicit Run lineage, truthful stale-activity and duplicate-identity projections, a closed 40-case role Eval, and shared Windows headless process flags for OCRV and related helpers. It does not add Temporal, a daemon, broker, MCP server, background Agent, or new engineering approval layer.

## Fresh verification

Repository and Python:

- `python -m pytest -q`: **175 passed**, 0 failed, 0 skipped after final Manifest generation;
- `python -O -m pytest` on role-Eval mutations and exact-recovery negatives: **25 passed**;
- `python scripts/validate_role_eval.py --check-pack`: **40 cases PASS**, SHA-256 `349ed0359750be64b809525bf75d13fc6a5b014dab690a3194a524353041aa6a`;
- `python scripts/quick_validate.py`: **15/15 Skill directories PASS**;
- `python scripts/validate_repository.py`: PASS after final Manifest generation;
- `git diff --check`: PASS.

Rust workspace:

- `cargo fmt --all -- --check`: PASS;
- `cargo clippy --workspace --all-targets -- -D warnings`: PASS;
- `cargo test --workspace --all-targets`: **62 passed**, 0 failed.

SLK BI frontend:

- `pnpm test`: **7 files / 17 tests passed**;
- `pnpm run typecheck`: PASS;
- `pnpm run build:ui`: PASS.

## Critical negative evidence

- zero Overwatcher remains valid; a second binding, cross-Run Session reuse, incomplete identity, wrong authority, or engineering-fact write fails closed;
- transport recovery rejects changed message, endpoint, scope, token sequence, or payload, stops after one exact retry, and cannot claim success without native start evidence;
- stale activity cannot display as current work, while legal pause/block/external wait is preserved;
- an actual Run continuation cannot silently invent a successor identity, and explicit lineage conflicts remain visible instead of being title-merged;
- role-Eval omissions, extras, duplicates, stale plan identity, casing/whitespace variants, and wrong answers fail closed, including under Python optimization mode;
- Windows helper call sites use hidden/no-window process policy by default, with bounded activation and no positive-duration `wait_threads` loop.

## Release boundary

This report establishes a locally verified 4.2.0 candidate. It does not claim a merge, push, tag, GitHub Release, global Skill deployment, LCaS integration, or modification of the protected source checkout. Publication remains a separate Owner-authorized action.
