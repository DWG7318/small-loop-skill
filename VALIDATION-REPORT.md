# Validation Report — SLK 4.2.11 Candidate

Date: 2026-09-25

Branch: `feature/slk-4.2.11-engineering-role-close`

Base candidate: `205ac3926171cfb43b1d15cc9360a82a58639d4a`

## Scope

SLK 4.2.11 is a schema-v8-compatible terminal role-lifecycle correction over 4.2.10. It keeps the three technical roles, CELL/D0/D1/D2, TOKEN, model bindings, direct communication, one optional Run-level Overwatcher, DeepSeek V4 Flash Worker, and disabled BoM unchanged.

The patch adds one explicit Supervisor-authenticated `close-role` action for terminal Checker/Worker retirement and makes the role projection derive `archived` from the resulting central lifecycle fact. The transaction appends one audit event, retires the exact endpoint, revokes the exact role credential, and exits the role without creating a successor, moving TOKEN, or rewriting D1/D2/RUN_CLOSED.

## Evidence

- Field RED was the closed LCaS Run `SLK-RUN-LCAS-RC08-JSONL-COMMIT-AWARE-ACK`: Checker `SLK-RC08-JSONL-CHECKER-01` and Worker `SLK-RC08-JSONL-WORKER-01` still projected `active/ready` with active endpoints after valid D2/RUN_CLOSED and Overwatcher closure. The immutable report is `post-close-role-reconciliation-20260925.json`, SHA-256 `c4ad59d1159f7a6681f8173ee5f7096bab2fd71c27ef9c93bd97389109cb6703`.
- TDD RED proved the core and CLI lacked terminal role closure, the Skills could claim archive without a central receipt, the 4.2.10→4.2.11 adoption path was absent, and malformed closure timestamps were accepted. Focused GREEN covers atomic Checker/Worker retirement, idempotent exact replay, role projection, credential revocation, and fail-closed open-Run/wrong-authority/wrong-role/wrong-run/TOKEN-holder/nonterminal/conflicting-replay cases.
- Rust workspace: 109 integration tests passed; unit and documentation targets passed. The explicit `4.2.10 → 4.2.11` adoption test preserves engineering events, TOKEN, and CELL graph; the installed-core compatibility test retires a terminal 4.2.9 Worker without reopening or re-versioning that Run.
- Python full suite: 299 passed. LE BI: 24 tests passed; TypeScript typecheck and production UI build passed. Role Eval: 66 cases, PASS; case-pack SHA-256 `76731ef1ef85f0d2eb30a37502e4b7291a5f5a50fe9d000a3e608b897aeebec2`. Repository validation, `python -O` repository/Eval checks, `cargo check --workspace`, `cargo fmt --check`, and `git diff --check` passed.
- A fresh isolated Cargo target produced the five headless release artifacts and the Tauri production fingerprint passed:
  - `slk-bi-desktop.exe`: `52265717340fff865bbf71b3f296397768bb424996dd6be15fabb19c50b38aaa`
  - `slk-bi-query.exe`: `5ec1281885dc2ff8f7f4a9225eb8d1b32fdb59891ab3138c88d976daf94bf370`
  - `slk-cargo.exe`: `4e3161a36a8830f675680b9e098d1a70d475741c07410e4238c6686e98bb9f92`
  - `slk-state.exe`: `83264b64f48d1fbc721ec1473138574eb63402ed4b95035c07eabc8858753f98`
  - `slk-transport.pyz`: `5f61a1e5bdf97c820cc967a52d41836e840bdf56b5f6096ed8efe01ed5570589`
- Real post-close reconciliation passed on legacy Run `SLK-RUN-LCAS-RC08-JSONL-COMMIT-AWARE-ACK` without product-repository changes: Worker and Checker now project `exited/archived` with zero active endpoints, exact Worker replay returned `already_closed`, Supervisor remains active, Run remains closed at method 4.2.9, and TOKEN remains sequence 15 with the Supervisor. Evidence: `role-close-reconciliation-20260925.json`, SHA-256 `06f730de9944bff82ec44ac4a8f39fe6694d182583a65828ad33366205162617`.

## Boundaries and limitations

No LCaS product file, product candidate, remote branch, tag, or Release is changed. The patch adds no role, heartbeat, scheduler, timer task, daemon, workflow engine, BoM route, automatic replacement, model upgrade, database migration, or BI write path.

`close-role` is deliberately narrower than native task/session archival: it records the authoritative SLK role, endpoint, and credential lifecycle. Overwatcher still uses `close-overwatcher`, and the Supervisor remains the closed Run's retained authority record. An open compatible Run uses the normal versioned adoption boundary; an already terminal legacy Run is not reopened or silently re-versioned and may receive only this narrow installed-core lifecycle reconciliation.
