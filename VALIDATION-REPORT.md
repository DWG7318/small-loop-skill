# Validation Report — SLK 4.2.0 Candidate

Date: 2026-09-22

Branch: `feature/slk-4.2.0-overwatcher`

## Accepted scope

SLK 4.2.0 preserves the bounded serial Run, normal Supervisor↔Checker↔Worker communication, `SLK TOKEN`, D0/D1/D2, rework, and acceptance authority. It fixes the native roles as Codex Supervisor, OCRV Checker, and DSH Worker; distinguishes D1 INCOMPLETE from formal FAIL; and permits Supervisor→same-Worker only for a closed rework directive after the current OCRV failure escalation. It also adds one optional, Supervisor-selected Overwatcher Agent Session per Run, without TOKEN, engineering, BI, or relay authority.

The candidate also adds explicit Run lineage, truthful stale-activity and duplicate-identity projections, a closed 40-case role Eval, and shared Windows headless process flags for OCRV and related helpers. It does not add Temporal, a daemon, broker, MCP server, background Agent, or new engineering approval layer.

## Fresh verification

Repository and Python:

- `python -m pytest -q`: **200 passed**, 0 failed, 0 skipped after final Manifest generation;
- `python -O -m pytest` on role-Eval and transport-contract negatives: **55 passed**;
- `python scripts/validate_role_eval.py --pack skills/small-loop-skill/assets/SLK-ROLE-EVAL.v1.json --check-pack`: **40 cases PASS**, SHA-256 `41b88bda4252191687e2a7dffc335f515e2ff070945c48158d35e208255352c0`;
- `python scripts/quick_validate.py`: **15/15 Skill directories PASS**;
- `python scripts/validate_repository.py`: PASS after final Manifest generation;
- `git diff --check`: PASS.

Rust workspace:

- `cargo fmt --all -- --check`: PASS;
- `cargo clippy --workspace --all-targets -- -D warnings`: PASS;
- `cargo test --workspace --all-targets`: **65 passed**, 0 failed.

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
- Codex Checker/Worker substitution and wrong runtime/model/session/adapter bindings fail closed; D1 INCOMPLETE retains Checker TOKEN, while ordinary, stale, wrong-scope, malformed, or wrong-payload Supervisor→Worker handoffs are rejected;
- Windows helper call sites use hidden/no-window process policy by default, with bounded activation and no positive-duration `wait_threads` loop.

## Release boundary

This report establishes a locally verified 4.2.0 candidate. It does not claim a merge, push, tag, GitHub Release, global Skill deployment, LCaS integration, or modification of the protected source checkout. Publication remains a separate Owner-authorized action.
