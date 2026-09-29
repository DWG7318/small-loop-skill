# Validation Report — SLK 4.3.2 Candidate

Date: 2026-09-29

Branch: `feature/slk-4.3.2-desktop-current-turn`

Base: `d95a081`

## Scope

SLK 4.3.2 is a schema-v8-compatible transport patch over 4.3.1. It preserves the Codex Supervisor, OCRV Checker, DSH Worker, optional whole-Run Overwatcher, serial CELL/D0/D1/D2, one TOKEN, direct communication, read-only BI and optional Temporal continuity. It adds no role, scheduler, daemon, heartbeat, state machine, Docker dependency, BoM path or product mutation.

The patch handles one exact failure class: a preserved Checker→registered Supervisor delivery and its one exact retry both fail `CODEX_ACTIVE_WRITER_UNRESOLVED` because Codex Desktop owns the writer. A two-phase Desktop-host bridge freezes a new message, requires same-active-turn platform readback of the exact `codex_app.send_message_to_thread` function output, then writes separate recovery/start evidence. It never rewrites the original attempt or moves TOKEN. Native diagnostic capture is bounded while retaining byte counts and SHA-256.

## Verification evidence

- Full Python suite: 357 passed; two optional Temporal SDK modules skipped when `temporalio` is absent. Python `-O` focused transport/Skill negatives: 108 passed.
- Rust workspace: 116 integration tests passed; unit and documentation targets passed. `cargo check --workspace` and `cargo fmt --all -- --check` pass. Explicit `4.3.1 → 4.3.2` adoption preserves the schema-v8 Run.
- LE BI: 24 tests passed; TypeScript typecheck and production UI build passed. Role Eval: 70 cases, PASS; case-pack SHA-256 `4d472d89dab7be1db328c34cbc0d77595858740c9e7a244d63fa1b74867bc4cc`.
- Repository/Manifest validation passed. All 11 JSON contracts parse, the new Desktop bridge schema is closed, and the deterministic local package verifies as 4.3.2 with 75 managed files.
- Real Codex Desktop integration used a disposable `RUN-A` outside every product Run. The original and exact retry both produced `CODEX_ACTIVE_WRITER_UNRESOLVED`; target thread `019fac68-139f-74f3-aa3d-87d1eb7bf516` remained on active turn `01a0eae6-feee-7622-b21a-a0932ae19b6a`; readback found platform item `fco_01a0eaf7-f3d1-7670-8527-51fc1d13cd86`; completion wrote the four separate recovery evidence files and preserved original `failed.json` SHA-256 `20486d84711e07d0e13551a87750559da919ac09fdd7da16a6bd7b68bc89688e`.
- Clean release artifacts were built headlessly in an isolated Cargo target:
  - `slk-bi-desktop.exe`: `f308afb0e2d3cb66f2d69ff54e8b4a30416989821146c78dd2a63f6d0b50ec92`
  - `slk-bi-query.exe`: `fcee19d6657262842f14eac82c0c58cfcf3ef4873b49deb18acc70739f7c44ec`
  - `slk-cargo.exe`: `74c63a55a45bcfde71b0faf6f295de5b41cec368a1c914e9c4cddbef64d60d8d`
  - `slk-state.exe`: `267684ec49dcac8f079fd07b9990dd1ae2187bfc1aa5526b586bba092276d07f`
  - `slk-transport.pyz`: `44a786ee4659450b0c35e37325be2eebabd8f92d163a947c6db79b305afd8c3c`

## Migration and deployment boundary

Explicit 4.3.1-to-4.3.2 adoption preserves Run ID, plan revision, TOKEN holder/sequence, roles/endpoints, candidate, D0/D1/D2 history, Overwatcher binding/incidents, attempt evidence and uncommitted product changes. The narrow Owner-authorized bridge may recover an exact preserved 4.3.1 unresolved attempt without first rewriting Run history. Installation alone does not adopt, resume or mutate a Run. Schema stays v8 with migrations `0001.sql` through `0008.sql`.

Final completion gates are the committed-tree full-range diff check, remote fast-forward/tag/Release identity checks, transactional deployment, installed manifest/byte verification and exact installed CLI version. Old tags and Releases are immutable.
