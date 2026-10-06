# Validation Report — SLK 4.4.2 local candidate

Date: 2026-10-06 Asia/Shanghai
Branch: feature/slk-4.4.2-runtime-recovery
Base: 6c12be8bb1f56793e9134a2a05ffa8f79ad006b2
Method/tools: 4.4.2; BI/WebBI: 1.1.0
Status: validated and locally deployed candidate. It is not merged, pushed, tagged, or released; no product Run was initialized, dispatched, resumed, or rewritten by this maintenance task.

## Bounded changes

SLK 4.4.2 is a minimal correction over 4.4.1. It keeps the existing Supervisor, Checker, Worker and Overwatcher topology and the existing D0/D1/D2 authority boundaries.

- The Supervisor must size CELLs for the actual DSH Worker capability after the engineering outcome and acceptance remain fixed. Large work is split before dispatch into dependency-ordered small or medium successor CELLs with independent D0 and D1.
- Most CELLs are expected to pass D1 on the first attempt. The first formal D1 FAIL may use ordinary same-CELL rework. A second-or-later consecutive formal D1 FAIL makes the old RoleHost reject rework; sealed Supervisor authority mutates the real serial plan, retains the split parent, inserts ordered successor CELLs, freezes a new Host and returns through standard `Supervisor → Checker CELL_DISPATCH`. Transport/tool failures, INCOMPLETE and duplicate receipts do not increment this count.
- Temporal owns the canonical Checker attempt root and now provides the built-in standard adapter. Bootstrap creates the deterministic workflow pair before full admission; delivery remains closed in `AWAITING_ADMISSION`.
- The first real normal-chain source has one explicit non-product bootstrap: a `SLK-CONFORMANCE-*` Run stores runtime evidence under `slk-conformance/<run_id>`, binds Worker to one separate clean, fixed-HEAD, no-remote sample Git, preserves every other role's truthful native workspace/cwd, freezes one disposable CELL and selects `ISOLATED_CONFORMANCE_SAMPLE`. Product Runs select `PRODUCT` and still require a distinct sealed source. The adapter never guesses or silently switches modes.
- OCRV's historical fixed line/file/token thresholds are advisory rather than D1 partition gates. The Checker receives the full candidate and performs one formal D1; optional runtime capacity data remains exact and bounded.
- A registered active Supervisor Session may submit its decision while the parent turn remains active. A late Codex Desktop readback consumes the original accepted send without resending it.
- Overwatcher administration preserves exact transport errors, Worker-held inspection remains exact, provider thinking fields are stripped recursively, and Temporal reload tolerates an exited-parent race without weakening identity checks.

## Test evidence

- Isolated first-source admission matrix: 12 passed; standard Temporal adapter contract: 8 passed.
- Full Python regression: 824 passed, 30 skipped.
- Optimized Python critical regression (`python -O`): 670 passed, 11 skipped. The expected pytest warning records that Python assertions are disabled; validators use explicit fail-closed checks.
- Real Temporal SDK workflow-order scenarios: 5 passed (admission/ACK, timeout recovery, member-residency notice, OW audit, OW exit guard).
- Rust workspace: 140 passed with no failures using an isolated Cargo target directory; 4.4.2 state mechanically rejects a second ordinary `REWORK_REQUESTED` and requires the versioned CELL-split route.
- Rust formatting: `cargo fmt --all -- --check` passes after mechanical formatting.
- BI/WebBI regression: 18 files / 84 tests passed; production UI build passed. BI/WebBI remain version 1.1.0 and are not part of this method bump.
- Repository validator, JSON Schema checks, regenerated Manifest, package/install mirrors and local installed identity pass.
- Role Eval and Skill collection tests include the second-D1-failure split route and reject a third ordinary retry.

## Negative evidence

The suite rejects or preserves failure for: product admission through sample mode; non-canonical sample Run/evidence roots; dirty, changed-HEAD or remote-backed sample Git; Worker workspace or evidence escape; a copied/fake root record outside the exact central state export; multiple sample CELLs; missing or unknown admission mode; delivery before admission; a second ordinary rework after two D1 FAILs; a claimed split without real state mutation; transport/tool failure, INCOMPLETE or duplicate receipts counted as D1 FAIL; oversized CELL dispatch; a second Checker attempt root; uncommitted handoff success; late Desktop resend; ambiguous readback; unregistered Supervisor submission; hidden Overwatcher errors; or retained provider thinking controls.

## Admission limits

The hash-bound package is installed to `C:\Users\DWG\.codex`; the managed DSH integration is installed to `D:\DSH`, the managed OCRV integration to `D:\OCRV`, and the Temporal Python package to the already-provisioned R2 environment. Transactional backups/receipts are preserved. Installation does not adopt or dispatch the active product Run; its Supervisor must execute the prepared isolated sample through the standard two-stage path, seal the real seven-leg source, then perform explicit 4.4.2 product admission. Existing Run evidence and version identity remain immutable; migration uses `docs/runtime/SLK-4.4.2-MIGRATION.md`.
