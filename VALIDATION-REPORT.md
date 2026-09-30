# Validation Report — SLK 4.3.4 Candidate

Date: 2026-09-30

Branch: `feature/slk-4.3.4-remove-bom-option`

Base: `f7e840a` (`v4.3.3`)

## Scope

SLK 4.3.4 is a schema-v8-compatible correction over 4.3.3. It removes BoM from the Run-readiness option set and every Owner option surface. The only remaining current-method treatment is negative: no BoM trigger, route, role or runtime exists, and a legacy readiness request that declares it is rejected with `OPTION_FORBIDDEN` instead of normalizing it as an option.

The explicit Run choices are now Ponytail, Temporal, Overwatcher, RTK and Probe CLI, plus any genuinely new optional feature. Codex Supervisor, OCRV Checker, DSH Worker, serial CELL/D0/D1/D2, one TOKEN, direct communication, read-only BI, OCRV preflight, optional Temporal continuity and optional whole-Run Overwatcher are otherwise unchanged.

## Verification evidence

- Full Python suite: 375 passed and two optional modules skipped. The same 375 passed under Python `-O`; pytest emitted only its expected optimized-assertion warning. This includes both legacy `BoM=ON` and `BoM=OFF` rejection, normalized-result omission and the five-option preparation contract.
- Rust core packages: 115 integration tests passed; unit and documentation targets passed. `cargo fmt --all -- --check` passed. The production release build passed in a fresh isolated Cargo target. A full workspace debug test reached only the Tauri debug target and failed on its environment-generated `core:window:allow-start-dragging` permission; this did not affect the production BI build or the state/cargo core suites and is not claimed as a workspace pass.
- LE BI: 24 tests passed; TypeScript typecheck and production UI build passed. Role Eval: 70 cases, PASS; case-pack SHA-256 `f98f401bb1bb4734415825ba2b119f71cc404b73c1bcd9f257b3d469c90c7e6d`.
- Repository validation passed after regenerating the hash-bound Manifest. The deterministic local package closed over 79 files and passed package-mode verification. Transactional OCRV and global installation completed with backups, installed-tree verification passed, and the installed transport reports 4.3.4.
- An installed-runtime probe with exactly the five supported choices returned `READY`. A matching legacy request containing `BoM=OFF` returned `REPAIR_NEEDED` with only `OPTION_FORBIDDEN`, omitted BoM from the normalized option result and preserved the same five supported choices.

## Release artifacts

- `slk-bi-desktop.exe`: `41fda1007a88bcd36cdb4ed1cbdae67f7f7e9e951a83032aa7f259893c19c84a`
- `slk-bi-query.exe`: `3abd6f4e9d2064dbf476b1a29410d6740f7f03d988163531d56ea7c2821b56af`
- `slk-cargo.exe`: `cd82711ab4a980ab0c7dc16cefa636ec2bba31a8a479d3168e15cf2ded75db0c`
- `slk-state.exe`: `bcb7de79ff5031bcb1b0e53073ad99d105a31771d9768310458fcd13ecf487b1`
- `slk-transport.pyz`: `5cf2f0ff97b5342cfbe986eaf9423d04bcea9d6081e936b7e9e010e3d0dc5d9d`

## Migration and deployment boundary

Explicit `4.3.3 → 4.3.4` adoption preserves Run ID, plan revision, TOKEN holder/sequence, roles/endpoints, candidate, D0/D1/D2 history, Overwatcher binding/incidents, attempt evidence and product changes. Installation alone does not adopt, resume, dispatch, inspect or mutate a Run. Schema stays v8 with migrations `0001.sql` through `0008.sql`.

Final completion gates are the refreshed Manifest, deterministic local package verification, transactional OCRV/global installation with backups and installed hash/version verification, committed-tree diff review, safe fast-forward/tag identity checks and the formal Release.
