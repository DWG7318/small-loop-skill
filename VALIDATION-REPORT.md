# Validation Report — SLK 4.3.0 Candidate

Date: 2026-09-28

Branch: `feature/slk-4.3.0-temporal-continuity`

Base candidate: `99fab0929e08672757ba960482c88352eabea77f`

## Scope

SLK 4.3.0 is a schema-v8-compatible continuity enhancement over 4.2.11. It keeps Codex Supervisor, OCRV Checker, DSH DeepSeek V4 Flash Worker, the optional whole-Run Overwatcher, serial CELL/D0/D1/D2, TOKEN, direct communication, model bindings, read-only BI and disabled BoM unchanged.

The release adds two optional reusable Temporal templates. `SLK.Start` freezes one startup identity and owns one deterministic `SLK.Run` child; `SLK.Run` persists only exact delivery, matching native-start ACK, bounded timeout, recovery request and terminal closure. Temporal is not a core dependency and has no engineering authority.

The same candidate closes four narrow RC08 field defects: invalid `evidence_id` diagnostics, substantive plan-revision validation, state/transport rework vocabulary, and native `already has an active writer` recovery.

## Evidence

- Field method findings: `D:\LCaS\.codex\.tmp\SLK-RUN-LCAS-RC08-OUTPUT-LIMIT-SAFE-RECOVERY\method-findings.md`, SHA-256 `5b97f8b22e62f9720b446fd31514f0a286b11eca78358eccb0908eec313b36c0`.
- Field D2 evidence: `D:\LCaS\.codex\.tmp\SLK-RUN-LCAS-RC08-OUTPUT-LIMIT-SAFE-RECOVERY\evidence-d2-run-level-20260928.json`, SHA-256 `a6c5a0a27c9424044214da5bc263ae5c92508de73ff1854b45348516cfe9df37`.
- TDD RED/GREEN covers explicit identifier error text, empty/blank/unchanged plan revisions, exact rework vocabulary, the native active-writer response, closed Temporal identities, changed duplicates, mismatched ACKs, terminal-result-not-ACK, optional Overwatcher recovery, sender fallback, ACK stopping recovery, blocked state, adapter-loader signatures and deterministic workflow ownership.
- Python core suite: 321 passed, 2 optional-SDK modules skipped when `temporalio` is absent. Key optimized-mode suite: 133 passed. In the isolated optional SDK environment, all Temporal tests passed in normal and optimized modes: 24 + 24.
- Real local Temporal service E2E used official Python SDK 1.33.0 and standalone CLI 1.9.1 / Server 1.32.0 with a local persistent development DB and no Docker. Startup, child ownership, delivery/ACK, Overwatcher recovery and sender fallback passed. The test service is not claimed as a production deployment.
- Rust workspace: 111 integration tests passed; unit and documentation targets passed. `4.2.11 → 4.3.0` adoption preserves engineering events, TOKEN and CELL graph. `cargo check --workspace` and `cargo fmt --check` passed.
- LE BI: 24 tests passed; TypeScript typecheck and production UI build passed. Role Eval: 70 cases, PASS; case-pack SHA-256 `8fbb0cdc7c779e42d31a41ff1b927ed7a66c072b2c9e09394d20c59f5731bb49`.
- A fresh isolated Cargo target produced the five headless release artifacts and one Tauri production fingerprint:
  - `slk-bi-desktop.exe`: `117165afcd12b2338cd12730a4873e3f96f210196971ad94a0f8dd4a033fa51c`
  - `slk-bi-query.exe`: `d8fc447c629024aa937cfdc31412692df6fa282faee915008b5157163626b29a`
  - `slk-cargo.exe`: `be7452df0ecff69a9b1d97484fec1956f9256c7d900efd34f2c750d3b5592220`
  - `slk-state.exe`: `17f60a8097645830400fed8c4f541c809aaecb90b66f62c8f61e507954bb9de0`
  - `slk-transport.pyz`: `50a379fb2df49cb6ab72eb7e05ca15de43b137126f6da3cd3f425257393fc2ea`
- Transactional local package/install verification passed for 71 hash-bound files: five artifacts, all 15 Skills, the Temporal template tree, docs, contracts and schema. Package mode rejected missing/extra/modified bytes, and the installed `C:\Users\DWG\.codex` mirror passed the same closed manifest check.

## Boundaries and limitations

No LCaS product file or Run was modified or dispatched. No main merge, tag or Release is part of this candidate. No Docker runtime, service, daemon, heartbeat, scheduler, Agent, role, model switch, database migration, BI write path or second SLK state machine was added.

Core SLK remains fully usable without the Temporal SDK or service. The repository ships importable templates and documentation; an operator separately supplies an existing endpoint and adapter. A matching native-start ACK is the only activation fact. Delivery/activity success and terminal output remain insufficient, and Temporal cannot decide D0/D1/D2, move TOKEN, write BI or alter role/model bindings.

The verified local development server is evidence that the templates execute against a real Temporal service; it is not evidence of production durability, HA, backup or access-control configuration. Those remain deployment decisions outside SLK.
