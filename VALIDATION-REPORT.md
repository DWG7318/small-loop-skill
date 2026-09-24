# Validation Report — SLK 4.2.10 Candidate

Date: 2026-09-25

Branch: `feature/slk-4.2.10-field-corrections`

Base candidate: `79ece6376bfe8ee33ffd03c34966a3930db8cc62`

## Scope

SLK 4.2.10 is a schema-v8-compatible field correction over 4.2.9. It keeps the three technical roles, CELL/D0/D1/D2, TOKEN, model bindings, direct communication, one optional Run-level Overwatcher, DeepSeek V4 Flash Worker, and disabled BoM unchanged.

The patch removes post-turn delayed self-wake promises; generalizes the existing exact Checker-to-Supervisor active-writer recovery without replaying the failed message; closes Worker continuation encoding, identity, headless OCRV, evidence-volume and runtime-revision gaps; keeps Checker subdivision inside one D1; limits Overwatcher to normal cycle, anomaly-pause and terminal-close exits; and projects Overwatcher binding, native liveness and cycle/incident state separately in read-only LE BI.

## Evidence

- Field input was read from `SLK-4.2.9-RC08-JSONL-FIELD-REPORT.md`, SHA-256 `02f33e53134e886f6e9f355b2a0ad975d6e115daf537214b1c6a3d9689b5eec0`; no LCaS product file was modified.
- TDD RED reproduced the active-writer D2 handoff gap, UTF-16LE/BOM and embedded-NUL gap, valid nonzero JSON loss, missing committed revision, bulk Checker evidence, resumed-DSH OCRV nesting, and absent BI binding/native/cycle distinction before implementation.
- Focused Python/Skill/transport suite: 141 passed in normal mode and 141 passed under `python -O` with the expected pytest assertion warning.
- Rust workspace: 104 integration tests passed; unit and documentation targets passed. `cargo check --workspace` and `cargo fmt --check` passed. The explicit `4.2.9 → 4.2.10` adoption test preserves engineering events, TOKEN and CELL graph.
- LE BI: 24 tests passed; TypeScript typecheck and production UI build passed. The expanded card keeps three technical role columns and one separate read-only Overwatcher operational strip.
- Role Eval: 66 cases, PASS; case-pack SHA-256 `62c760c499b425c805f3e75d136703fe80cc1067014b7b600af5f049a74d9e3a`.
- Python full suite: 297 passed. Repository/Skill validators, tracked JSON parsing, Manifest identity, `git diff --check`, sensitive-value and cross-project boundary scans passed.
- A fresh isolated Cargo target produced the five release artifacts; Tauri used `build --no-bundle`, the production fingerprint passed, and every process helper remains headless:
  - `slk-bi-desktop.exe`: `6cfcfceb8587a934244e53c263f9c03950930d6a856db2bc3edf3fac79db6e7f`
  - `slk-bi-query.exe`: `e2aef90506f4e35c874b1e959e0d0d3d7e996b2eb81d4a2a19d965abfd6dccfd`
  - `slk-cargo.exe`: `30be98d2f05f33e692990b3b377d6422b92eb0aa55a81cc20c70ab213999c6ef`
  - `slk-state.exe`: `08c4791d8ff3629b6747834ff1029da2a2a2a68eaa030553c1c4f95a165c3a28`
  - `slk-transport.pyz`: `1c27c5fe38fe7fbd37fa085691fcf4a974799fd5fd67c89ee02412d110b1a2bc`
- The hash-closed local package, package verification, atomic installation over 4.2.9, installed-tree verification, source/install Skill mirror checks, and installed `slk-state`/`slk-transport` version checks passed at 4.2.10.

## Boundaries and limitations

No LCaS product file, live Run history, product candidate, remote branch, tag or Release is changed. The patch adds no role, heartbeat, scheduler, timer task, daemon, workflow engine, BoM route, automatic replacement, model upgrade, database migration or BI write path.

Transport can send one new auditable message to an exact already-active canonical Codex turn, but it cannot guarantee platform scheduling after that turn ends. Without a verified direct entrance, the truthful fallback remains Owner/Main activation. A live Run adopts 4.2.10 only through its existing Supervisor-controlled versioned boundary.
