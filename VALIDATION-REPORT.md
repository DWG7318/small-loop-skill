# Validation Report — SLK 4.3.3 Candidate

Date: 2026-09-30

Branch: `feature/slk-4.3.3-ocrv-preflight`

Base: `dd21a4a`

## Scope

SLK 4.3.3 is a schema-v8-compatible readiness and OCRV D1 preflight patch over 4.3.2. It preserves Codex Supervisor, OCRV Checker, DSH Worker, optional whole-Run Overwatcher, serial CELL/D0/D1/D2, one TOKEN, direct communication, read-only BI and optional Temporal continuity. It adds no role, scheduler, daemon, heartbeat, state machine, Docker dependency, BoM route or product mutation.

The patch adds one closed three-role Run readiness gate and an SLK-owned OCRV adapter. Readiness proves exact runtime/model/endpoint/workspace/capacity/Skill/Tool facts and requires Owner evidence for explicit ON/OFF decisions on Ponytail, Temporal, Overwatcher, RTK, Probe CLI, BoM and every declared future option. OCRV now performs a real no-model preview, compacts evidence, dynamically refines ordered path/criterion scopes until every segment fits exact capacity, rejects scope widening, stops after a blocking finding and emits one compact aggregate without full segment-result reinjection.

## Verification evidence

- Full Python suite: 372 passed, two optional modules skipped. The same 372 passed under Python `-O`; pytest emitted only its expected optimized-assertion warning.
- OCRV-focused regression: 23 passed, including real-scope preview, full-over-capacity refinement, complete path/criterion coverage, exit-code-3 INCOMPLETE handling, early blocking stop, timeout preservation and compact aggregation.
- Rust workspace: 116 integration tests passed; unit and documentation targets passed. `cargo check --workspace` and `cargo fmt --all -- --check` pass. Explicit `4.3.2 → 4.3.3` adoption preserves the schema-v8 Run.
- LE BI: 24 tests passed; TypeScript typecheck and production UI build passed. Role Eval: 70 cases, PASS; case-pack SHA-256 `6917cf56650fb6d577a9a5d83cb67cd4c5902c4cb8e1236749af07320b3f4d09`.
- Repository validation passed with 13 JSON contracts and 335 hash-bound repository files before this final report refresh. The Skill collection remains 15 Skills; the main Skill is 5,838 body characters.
- Real OCRV 1.12.7 integration ran against `D:\OCRV\ocr-slk.ps1` in `--preview` mode only: status READY, preview exit 0, 61 inventory entries, 32 real selected paths, 624 background characters, and discovered `ocrv-preview`, Probe CLI and RTK capabilities. No model review was started.
- A reused Cargo target was intentionally rejected because four historical production fingerprints were present. A fresh isolated Cargo target then produced one verified custom-protocol BI fingerprint and the five release assets below.

## Release artifacts

- `slk-bi-desktop.exe`: `700d586e03be7d9c7fd8eb348750308499ef013d6acf4b5ed4cbf47f2578e48d`
- `slk-bi-query.exe`: `819c35a91464cc3f80433acb9e00cf8127b309aeb070781aac016877dec1ea55`
- `slk-cargo.exe`: `d24242c610ff7a3230656a85c55c41ffa7b933721666636ecfa81e863c2e6577`
- `slk-state.exe`: `51720932af65e34e2a4012f86fb381b630270d83324d5d89e6302cc43a5cbbd5`
- `slk-transport.pyz`: `f7b57ce56984b2828b6de230e1f93fe9e7c0fdbdf8c2d07b5be3c73f8726f5f0`

## Migration and deployment boundary

Explicit 4.3.2-to-4.3.3 adoption preserves Run ID, plan revision, TOKEN holder/sequence, roles/endpoints, candidate, D0/D1/D2 history, Overwatcher binding/incidents, attempt evidence and uncommitted product changes. Installation alone does not adopt, resume, dispatch, inspect or mutate a Run. Schema stays v8 with migrations `0001.sql` through `0008.sql`.

Final completion gates are the refreshed Manifest, deterministic local package verification, transactional OCRV/global installation with backups and installed hash/version verification, committed-tree diff review, safe fast-forward/tag identity checks and the formal Release.
