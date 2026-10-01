# Validation Report — SLK 4.3.6 Candidate

Date: 2026-10-01

Branch: `feature/slk-4.3.6-legacy-worker-recovery`

Base: `25f6d57` (`v4.3.5`)

## Scope

SLK 4.3.6 is a schema-v8-compatible recovery correction. It accepts one historical SLK 4.3.4 flat DSH start only after the same completed Worker attempt, immutable transport task, endpoint, envelope, original Session, terminal result, Worker result, candidate, central handoff events and Checker-owned TOKEN all match. It then reuses the already-staged candidate for real OCRV D1 without replaying Worker, moving TOKEN or changing old evidence.

Normal delivery and native-activity inspection still require `slk.native-start/v2`; the flat marker never becomes current activity proof. Supervisor, Checker, Worker, optional whole-Run Overwatcher, serial CELL/D0/D1/D2 topology, direct communication, BI authority and optional Temporal templates are unchanged. No AX, Orca, wmux, BoM, new role, workflow, daemon, heartbeat, MCP, scheduler, Docker dependency or product method was added.

## Verification evidence

- The real 4.3.4 six-field start shape first reproduced `WORKER_CONTINUATION_NOT_READY`; the focused fix and its ordinary plus optimized-mode checks now pass. A read-only check against the preserved production attempt also returned its exact original Session and `checker_token_already_committed=true` without authenticating, decrypting or activating a role.
- Positive coverage proves the exact Checker-TOKEN recovery does not call Worker continuation. Negative variants reject a changed task hash, wrong Session, an extra start field, missing candidate event and Worker-owned TOKEN.
- State regression coverage proves a real schema-v8 4.3.5 Run adopts to 4.3.6 without rewriting engineering history, while 4.3.4 must still adopt to 4.3.5 first. Both 4.3.5 and 4.3.6 reject a legacy start marker and accept only an exact `slk.native-start/v2` receipt for ordinary delivery.
- The captured nested-launch failure is a Windows Job access denial on `CREATE_BREAKAWAY_FROM_JOB`; its local-code-page rejection JSON previously triggered an outer UTF-8 reader failure and `stdout=None`. Injected regressions prove the exact WinError 5 retries once without breakaway, unrelated launch failures do not retry, UTF-8 non-ASCII JSON remains parseable, and non-UTF-8 or empty streams fail once with closed error codes.
- The captured OCRV FAIL proves the nested review process may exit 0 while the outer transport correctly exits 2 for the business verdict. Parametric regressions accept PASS/0, FAIL/2 with nested 0, and INCOMPLETE/3 with a nonzero nested exit, while rejecting a forged Session identity and a wrong outer verdict exit without rerunning OCRV or rewriting original evidence.
- Existing v2 continuation, missing-result recovery, independent OCRV start and Checker-authored D1 tests remain green.
- Python suites: 429 passed and two optional modules skipped in ordinary mode; the same 429 passed under `python -O` with only pytest's expected optimized-assertion warning.
- Rust core packages: 116 integration tests passed; unit and documentation targets passed. `cargo fmt --all -- --check` passed.
- LE BI: 24 tests passed; TypeScript typecheck, production UI build and isolated headless Tauri release build passed.
- Role Eval: 75 closed cases, PASS; case-pack SHA-256 `d0625e7561992424e328b4679d39ab481ef4d7feffb84430b4dbe0046ad869b8`.
- Repository identity, JSON/YAML/schema parsing, deterministic package verification, version/Manifest hashes, root/install mirrors, `git diff --check`, and sensitive/forbidden-scope scans remain completion gates.

## Candidate artifacts

- `slk-bi-desktop.exe`: `7e19cc7951205d48bc41df5ecf97f43ff11ed4b3dbbce106ce99deb228cc5260`
- `slk-bi-query.exe`: `f3bcf81165661948595449a8ba4f54e5b103d0fa926335e19b523a338144e8df`
- `slk-cargo.exe`: `3de29dd7ca97e7768403a4d6bff7b09823cdc626cf81d865f28fb262a01b3dae`
- `slk-state.exe`: `c10675cc63785752f5dae8709813c79299a0944ec4db2d5572763c1dbe325fb1`
- `slk-transport.pyz`: `bfe8e82e7d02f986cb5f5c5fd307f09c695906f8a5799a2cfbf634a6b4656250`

## Migration and deployment boundary

Explicit `4.3.5 → 4.3.6` adoption preserves Run ID, plan revision, current CELL/attempt, TOKEN holder/sequence, role endpoints, candidate, D0/D1/D2 history, Overwatcher state, transport evidence and product changes. Installation alone does not adopt, resume, dispatch, inspect or mutate a Run.

For the narrow legacy recovery, retain the original Worker attempt and every failed recovery unchanged. Generate one fresh complete engineering projection and one new outer recovery message after adoption. The installed 4.3.6 transport may read the old flat identity only through the closed completed-Worker/Checker-TOKEN branch, writes new OCRV evidence below `.native-recovery-v2`, and leaves ordinary v2/current-activity validation unchanged.

An in-flight 4.3.4 Temporal Workflow keeps its frozen 4.3.4 Workflow package and Start input. Only its Run-local adapter is reloaded in a controlled Worker restart and calls the installed 4.3.6 transport; the old Workflow history is not reinterpreted.
