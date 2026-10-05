# Validation Report — SLK 4.4.2 local candidate

Date: 2026-10-06 Asia/Shanghai
Branch: feature/slk-4.4.2-runtime-recovery
Base: 6c12be8bb1f56793e9134a2a05ffa8f79ad006b2
Method/tools: 4.4.2; BI/WebBI: 1.1.0
Status: validated local candidate. It is not installed, deployed, merged, pushed, tagged, or released.

## Bounded changes

SLK 4.4.2 is a minimal correction over 4.4.1. It keeps the existing Supervisor, Checker, Worker and Overwatcher topology and the existing D0/D1/D2 authority boundaries.

- The Supervisor must size CELLs for the actual DSH Worker capability after the engineering outcome and acceptance remain fixed. Large work is split before dispatch into dependency-ordered small or medium successor CELLs with independent D0 and D1.
- Most CELLs are expected to pass D1 on the first attempt. The first formal D1 FAIL may use ordinary same-CELL rework. A second consecutive formal D1 FAIL for the same CELL stops ordinary retry: the Supervisor reviews both failures and splits the remaining unaccepted work before redispatch. There is no third ordinary retry. Transport/tool failures, INCOMPLETE and duplicate receipts do not increment this count.
- Temporal owns the canonical Checker attempt root. A handoff that cannot be committed is an explicit failure, not a silent success.
- OCRV's historical fixed line/file/token thresholds are advisory rather than D1 partition gates. The Checker receives the full candidate and performs one formal D1; optional runtime capacity data remains exact and bounded.
- A registered active Supervisor Session may submit its decision while the parent turn remains active. A late Codex Desktop readback consumes the original accepted send without resending it.
- Overwatcher administration preserves exact transport errors, Worker-held inspection remains exact, provider thinking fields are stripped recursively, and Temporal reload tolerates an exited-parent race without weakening identity checks.

## Test evidence

- Focused modified regression: 447 passed, 3 skipped.
- Full Python regression: 801 passed, 29 skipped.
- Optimized Python critical regression (`python -O`): 734 passed, 10 skipped. The expected pytest warning records that Python assertions are disabled; validators use explicit fail-closed checks.
- Rust workspace tests: passed with no failures using an isolated Cargo target directory; 4.4.2 state now mechanically rejects a second ordinary `REWORK_REQUESTED` and requires the versioned CELL-split route.
- Rust formatting: `cargo fmt --all -- --check` passes after mechanical formatting.
- BI/WebBI regression: 18 files / 84 tests passed; production UI build passed. BI/WebBI remain version 1.1.0 and are not part of this method bump.
- Repository validator and regenerated Manifest/package checks pass.
- Role Eval and Skill collection tests include the second-D1-failure split route and reject a third ordinary retry.

## Negative evidence

The suite rejects or preserves failure for: a second ordinary rework request after two consecutive D1 FAILs; treating transport/tool failure, INCOMPLETE or duplicate receipts as D1 FAILs; dispatching an oversized CELL without further decomposition; treating legacy OCRV thresholds as formal partitions; creating a second Checker attempt root; claiming an uncommitted handoff succeeded; resending a late Desktop delivery; accepting ambiguous or drifted readback; submitting from an unregistered Supervisor identity; hiding Overwatcher administrative errors; or retaining provider thinking controls.

## Admission limits

This local candidate does not mutate any active product Run, active Supervisor Session, installed global Skill, BI/WebBI deployment, Temporal service, OCRV/DSH installation, or remote Git state. Deployment and adoption wait for the Owner's later instruction after the current product Supervisor completes. Existing Run evidence and version identity remain immutable; migration uses `docs/runtime/SLK-4.4.2-MIGRATION.md`.
