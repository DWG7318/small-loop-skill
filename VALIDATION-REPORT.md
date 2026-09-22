# Validation Report — SLK 4.2.1 Candidate

Date: 2026-09-22

Branch: `feature/slk-4.2.1-active-overwatcher`

## Accepted scope

SLK 4.2.1 preserves the bounded serial Run, normal Supervisor↔Checker↔Worker communication, `SLK TOKEN`, D0/D1/D2, rework, and acceptance authority. It withdraws the unreleased 4.2.0 event-woken observer semantics and replaces them with one optional, Supervisor-and-Owner-confirmed Overwatcher Agent Session that remains in the same foreground active turn and completes a fixed eight-part cycle every 180–300 seconds.

The candidate adds append-only cycle evidence bound to Session, foreground turn, cadence, plan, CELL, TOKEN, latest event/message, checklist, and native activity evidence. BI reads the cycle projection but cannot mutate it. The implementation does not add a heartbeat, automation, cron, Windows Scheduled Task, Temporal, daemon, service, detached helper, background Agent, second observer, broker, MCP server, or new engineering approval layer.

## Fresh verification

Repository and Python:

- `python -m pytest -q`: **203 passed**, 0 failed, 0 skipped after final Manifest generation;
- `python -O -m pytest tests/eval/test_role_eval.py -q`: **21 passed**;
- `python scripts/validate_role_eval.py --pack skills/small-loop-skill/assets/SLK-ROLE-EVAL.v1.json --check-pack`: **40 cases PASS**;
- `python scripts/quick_validate.py`: **15/15 Skill directories PASS**;
- `python scripts/validate_repository.py`: PASS after final Manifest generation;
- `git diff --check`: PASS.

Rust workspace:

- `cargo fmt --all -- --check`: PASS;
- `cargo clippy --workspace --all-targets -- -D warnings`: PASS;
- `cargo test --workspace --all-targets`: **70 passed**, 0 failed.

SLK BI frontend:

- `pnpm test`: **7 files / 17 tests passed**;
- `pnpm run typecheck`: PASS;
- `pnpm run build:ui`: PASS.

## Critical negative evidence

- zero Overwatcher remains valid; a second binding, cross-Run Session reuse, incomplete identity, wrong authority, or engineering-fact write fails closed;
- a passive/end-turn binding, heartbeat/scheduled-task substitute, cadence outside 180–300 seconds, incomplete checklist, free-text anomaly, wrong Session/turn, stale TOKEN/event/message, overlapping/reused cycle, or legacy 4.2.0 binding fails closed;
- a bound Overwatcher requires one complete initial cycle before a new handoff; two missed intervals reject new dispatch/handoff while work already in flight is not rewritten;
- transport recovery rejects changed message, endpoint, scope, token sequence, or payload, stops after one exact retry, and cannot claim success without native start evidence;
- stale activity cannot display as current work, while legal pause/block/external wait is preserved;
- an actual Run continuation cannot silently invent a successor identity, and explicit lineage conflicts remain visible instead of being title-merged;
- role-Eval omissions, extras, duplicates, stale plan identity, casing/whitespace variants, and wrong answers fail closed, including under Python optimization mode;
- Codex Checker/Worker substitution and wrong runtime/model/session/adapter bindings fail closed; D1 INCOMPLETE retains Checker TOKEN, while ordinary, stale, wrong-scope, malformed, or wrong-payload Supervisor→Worker handoffs are rejected;
- Windows helper call sites remain hidden/no-window by default. The Overwatcher stays active in its own foreground Agent turn; it is not implemented as an external heartbeat or scheduled/background process.

## Release boundary

This report establishes a locally verified 4.2.1 candidate and records 4.2.0 as `WITHDRAWN / DO NOT ENABLE`; 4.2.0 was never tagged or released. It does not claim a merge, push, tag, GitHub Release, LCaS integration, or modification of the protected source checkout. Publication remains a separate Owner-authorized action.
