# Validation Report — SLK 4.2.4 Candidate

Date: 2026-09-23

Branch: `feature/slk-4.2.4-worker-completion-guard`

## Accepted scope

SLK 4.2.4 closes one bounded runtime gap without changing the serial Run, Codex Supervisor ↔ OCRV Checker ↔ DSH Worker topology, `SLK TOKEN`, CELL, D0/D1/D2, direct communication, model policy, or optional whole-Run Overwatcher role. When an exact DSH Worker Session has terminal evidence but omitted its Worker-owned events and Worker→Checker start, the original Checker can resume that same Session for one idempotent completion suffix. The Worker credential is decrypted only inside that resumed Worker process; Supervisor, Checker, and Overwatcher cannot author Worker facts.

Each Worker-held TOKEN Overwatcher cycle binds one read-only completion inspection. Its repair attempt is derived from the source message's unique `TRANSPORT_STARTED` evidence, never assumed. A trustworthy terminal evidence time prevents historical completion from receiving a fresh grace interval. An unresolved gap remains anomalous on every later cycle; an existing recovery observation suppresses only duplicate notification. Explicit `4.2.3 → 4.2.4` adoption preserves an active Overwatcher.

## Verification gates

- Real R3B CELL03 read-only fixture: PASS. The exact attempt `e180fe95-4913-4eb6-90b6-29ee7261d7c2` produced `WORKER_COMPLETION_HANDOFF_MISSING`, the three missing Worker events, the recorded DSH Session, Worker-02 and Checker-01 identities, and a valid `CANDIDATE_READY` shape for candidate `a28380441913c409a972d2dd7842fab8e1c8d9f8`. Stubbed callbacks wrote only to a disposable system temporary directory; source file hashes were unchanged and no continuation, OCRV start, credential decryption, TOKEN commit, or R3B mutation occurred.
- Python suite: 243 passed (`python -m pytest -q`).
- Optimized-mode runtime suite: 170 passed (`python -O -m pytest -q tests/eval tests/transport tests/state tests/install`).
- Rust workspace: PASS (`cargo test --workspace --all-targets`).
- Rust formatting and strict clippy: PASS (`cargo fmt --all -- --check`; `cargo clippy --workspace --all-targets -- -D warnings`).
- LE BI: 17 tests passed; TypeScript typecheck and production UI build passed.
- Focused 4.2.4 sandbox: PASS. It covers exact same-Session continuation, credential non-inheritance, idempotent Worker event replay after TOKEN movement, active Overwatcher adoption, persistent handoff anomaly, atomic start, final closure, no BoM route, and no model change.
- Repository, role Eval, closed schema, deterministic package, package hash, baseline diff, sensitive-information, and scope-boundary gates are rerun after the final Manifest update.

## Critical negative evidence

- a first-activation endpoint with `session_id: null` cannot block recovery when immutable `started.json` and terminal evidence bind one exact DSH Session;
- changed endpoint/envelope bytes, a different Session/instance/role, wrong Worker credential, or conflicting idempotent event replay fails before TOKEN commit;
- Supervisor, Checker, Overwatcher, OCRV, and ordinary DSH child processes do not inherit a parent SLK role or Overwatcher credential;
- terminal text or `completed.json` cannot substitute for exact Checker endpoint/envelope/`started.json` evidence;
- D1 evidence from an older attempt of the same CELL cannot hide the current attempt's stall;
- missing or ambiguous source-attempt evidence is rejected instead of defaulting to attempt 1;
- a historical completed Worker does not receive another cadence of grace;
- prior notification does not clear an unresolved anomaly on later Overwatcher cycles;
- 4.2.4 retains all revisioned 4.2.3 atomic-start, runtime-revision, active-Overwatcher, TOKEN, and terminal-closure protections.

## Release boundary

This report establishes a repository-local 4.2.4 candidate only. It does not claim a global installation, deployment, merge, push, tag, GitHub Release, or product Run recovery. LCaS/R3B was read only and remains under its existing Supervisor authority.
