# Validation Report — SLK 4.2.5 Candidate

Date: 2026-09-23

Branch: `feature/slk-4.2.5-checker-recovery`

## Accepted scope

SLK 4.2.5 closes the 4.2.4 Worker-completion recovery authority gap without changing the serial Run, Codex Supervisor ↔ OCRV Checker ↔ DSH Worker topology, `SLK TOKEN`, CELL, D0/D1/D2, model policy, BI authority, or optional whole-Run Overwatcher role. Supervisor may send one closed recovery envelope only to the original registered OCRV Checker. The deterministic native Checker invocation records authentication as pending and recovery as unauthorized until the Checker credential proves its exact role and current runtime revision; only then may the same DSH Session execute its Worker-owned completion suffix.

The public direct `resume-worker-continuation` entrance is removed. The packaged OCRV integration preserves the accepted D1 adapter and installs only a reversible wrapper plus recovery companion. A read-only cadence inspector separately prevents an `active` role projection from proving that Overwatcher cycles continue: one missed interval wakes the same binding, while more than two intervals return to Supervisor review without creating a heartbeat, daemon, timer, replacement, or state mutation. Explicit `4.2.4 → 4.2.5` adoption preserves the existing Run and proven active Overwatcher.

## Verification gates

- Focused Python gate: 165 passed. It covers closed recovery contracts, deterministic invocation identity, early pending/unauthorized start evidence, authenticated Checker-before-Worker ordering, direct Supervisor rejection, credential stripping, Overwatcher cadence classification, role Eval, Skill guardrails, and disposable OCRV install/rollback.
- Full Python suite: 259 passed (`python -m pytest -q`).
- Optimized-mode runtime suite: 186 passed (`python -O -m pytest -q tests/eval tests/transport tests/state tests/install`).
- Rust workspace: PASS (`cargo test --workspace --all-targets`).
- Rust formatting and strict Clippy: PASS (`cargo fmt --all -- --check`; `cargo clippy --workspace --all-targets -- -D warnings`).
- LE BI: 17 tests passed; TypeScript typecheck and production UI build passed.
- Focused 4.2.5 sandbox: PASS. It covers authenticated Checker recovery, removed public direct resume, deterministic invocation identity, exact same-Session continuation, projected-active cadence detection, idempotent Worker event replay, 4.2.4→4.2.5 active-Overwatcher adoption, atomic start, final closure, no BoM route, and no model change.
- Repository, role Eval, JSON schema, deterministic package, package hash, mirror/version, baseline diff, sensitive-information, and scope-boundary gates are rerun after the final Manifest update.

## Critical negative evidence

- the former public direct continuation command is absent, and a recovery call outside the exact native OCRV invocation fails before Checker authentication or Worker resume;
- wrong Checker role, role instance, endpoint version, Run, runtime revision, or credential authentication fails closed;
- early OCRV `started.json` cannot claim authentication or authorization; only the final closed result may carry both true values;
- the recovery invocation ID is deterministic for the immutable envelope, so exact retry cannot create a second logical recovery;
- parent role and Overwatcher credentials do not enter OCRV or Worker child processes, request/result evidence, stdout, stderr, or package files;
- changed request/result fields, request hash, source attempt, DSH instance/session, Worker credential, Checker endpoint, or continuation result is rejected before TOKEN commit;
- projected `active`, old running state, TOKEN, visible task, or heartbeat cannot prove a current Overwatcher cycle; lateness cannot silently create a replacement;
- 4.2.4 Runs remain on 4.2.4 until explicit adoption, and the OCRV wrapper change remains a separately authorized reversible installation;
- Windows helper processes remain hidden/no-window by default; the candidate adds no scheduler, resident service, product edit, live recovery, model change, or BoM route.

## Release boundary

This report establishes a repository-local 4.2.5 candidate only. It does not claim a global installation, OCRV integration installation, deployment, merge, push, tag, GitHub Release, product Run recovery, or active Overwatcher repair. LCaS/R3B and live `D:\OCRV` were not modified.
