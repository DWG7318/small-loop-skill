# BI 1.1.3 and Run09 repairs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement tasks with spec review followed by quality review. Owner authorized parallel subagents. Parallel writers have explicitly disjoint file/function ownership; do not race writers on shared files.

**Goal:** Deliver the approved BI 1.1.3 changes and evidence-based 4.x repairs without touching 3.x or live Runs.

**Architecture:** Reuse the desktop read projection and shared desktop/WebBI presentation. Repair existing OCRV, identity, pause and OW/Temporal seams; no new runtime layer or arbitrary capacity gate. Preserve unknown states and exact identity checks.

**Tech Stack:** React/TypeScript/Vitest, Rust/SQLite/Tauri, Python/pytest/Temporal.

Workspace: `C:/Users/DWG/.config/superpowers/worktrees/SLK/bi-113-run09-repair`, branch `feature/bi-113-run09-repair`, base `7b2bb02`.

Owner approved implementation on 2026-10-15. 3.1.0 stays deferred. No deployment, cloud mutation or live Run tests in this implementation phase. 4.x release number remains separate from BI 1.1.3.

## Work ledger

- [x] Isolate checkout; preserve main planning changes and all 3.x work.
- [x] Python baseline: 227 passed, 5 skipped (native activity, OCRV adapter, role host, run pause).
- [x] T1 `0060497`, `2e8c5e3`: independent spec/quality passed, including short-container-width regression (3 RED -> 23 targeted GREEN). Native visual/interactivity not verified.
- [x] T2 `278f189`: authoritative split-count projection and backwards-compatible WebBI consumption; spec/quality passed; Rust query 8, targeted frontend 66 passed.
- [x] T3 R1 `ee3c12a`: material bootstrap spec/quality passed; 270 + 57 implementation regressions, independent 158 material tests passed. N4 `a3b6121` keeps compact diagnostic UNKNOWN; independent final spec/quality passed.
- [x] T4 R2/N3: `d04dedd`, `a3894ed`, `d8f7966`, `6df4d0f`; exact recovery, historical Host and native-call census passed independent spec then quality review. P1 rejected-link traversal found in review was corrected and independently retested.
- [x] T5 N1/R3: `b8d3592` pause cancellation and `db6e0c6` isolated terminal-audit race; independent spec/quality passed. Historical audit83 remains unproven, not relabelled as repaired.
- [x] T6 N2: `c495715` OW instructions/example and existing lifecycle recovery recipes passed independent application/spec/quality checks. BI version patch `b4bfa35` independently passed; `5b8aeaa` adds six current lightweight admission cases.
- [x] T7 Integrated regression, independent reviews, precompiled artifacts, delivery report.

Parallel source work is complete and frozen. Separate implementation, spec and quality checks were used; reviewers did not author the changes they approved. N1 has independent spec/quality PASS; R3 has separate bounded-race PASS, not an audit83 root-cause claim. The P1 link regression was independently reproduced and closed. All source edits stayed in this isolated worktree.

BI version/readiness preparation: 1.1.3 version surfaces and old upload compatibility updated. Readiness accepts the existing v1 receipt for BI 1.1.x patches (existing minimum preserved), not arbitrary major/minor families. RED 12 readiness cases and one Web upload case; GREEN 134 readiness, 217 full frontend, typecheck, UI production build and five native desktop read-command tests. A mistakenly invoked nonexistent `pnpm build` was corrected to repository `pnpm build:ui`; no dependency/source workaround. Final integration follows all source edits.

N2 documentation behavior test reproduced nonexistent top-level `verdict`, unrecognized raw probe code and ambiguous checklist mapping. First independent application test passed member-UNKNOWN but invented own native_liveness UNKNOWN; corrected wording then passed both scenarios. Reviewer caught that the first Python fixture had a missing own-proof reference and a fixed next timestamp: fixed the fixture, limited its claim to schema/member-evidence validation, and added a Rust test passing the actual central writer with isolated evidence. Fresh reviewer checks: 76 Rust overwatcher tests and 246 Python tests passed. These tests do not authenticate a real host OW activation.

Final UI source validation: 221 tests / 20 files, typecheck and production build passed. Pure Temporal selection: 238 passed, four service-starting cases deselected (four additional service-based files excluded); existing pytest-asyncio collection warning, no service launched. Skills/readiness/N2 selection: 253 passed. Full Rust workspace tests passed. Compiled-release state/query binaries passed 97 isolated Python integrations. Eight unpublished module archives were built, source-hash checked and restored successfully. Full transport: 1760 passed / five OS symlink skips; final standalone Rust workspace: 198 passed. OCRV/material/module/BI-contract selection: 62 passed. Final verification details and exact candidate hashes: [implementation result](../../maintenance/reports/2026-10-15-bi113-run09-implementation-result.md).

## T1 — segments and transparency

Files: `apps/slk-bi/src/components/RunStrip.tsx`, `RunStrip.test.tsx`, `BackgroundTransparency.tsx`, `BackgroundTransparency.test.tsx`, `src/App.tsx`, `src/App.test.tsx`, `src/styles/app.css`, `src/webbi/WebBiApp.tsx`, `WebBiApp.test.tsx`, `webbi.css`.

- [x] Replace old padding test with actual segment counts: `(0,0),(1,1),(4,4),(10,10),(11,11),(20,20),(21,21),(30,30),(31,30),(100,30)`. Assert filled count equals passed for totals <=30, never fills all segments before completion for totals >30, and raw aria total is unchanged. Test no input data mutation.
- [x] Replace select tests with slider tests: role `slider`, min 0/max100/step1, values 0/1/37/99/100, CSS background alpha `100-value`, no root opacity; default20 when key absent/invalid; explicit0 and legacy20/40/60/80 restored. Simulate unavailable storage without blocking UI. App/WebBI gear tests use slider and assert explanatory text removed.
- [x] Run `pnpm test -- src/components/RunStrip.test.tsx src/components/BackgroundTransparency.test.tsx src/App.test.tsx src/webbi/WebBiApp.test.tsx`; confirm feature-specific RED before production changes.
- [x] Replace segment calculation with `const segments = Math.min(total, 30)` and filled calculation `total <= 30 ? passed : passed >= total ? segments : Math.min(segments - 1, Math.floor(passed / total * segments))`; preserve exact numeric/ARIA values. Use ten-column grid that shrinks to actual occupied columns for short rows, and no placeholder cells. Exact totals have exact tooltip; >30 has proportional tooltip.
- [x] Replace fixed LEVELS with integer validation 0..100. Read raw localStorage value first; null/blank is not explicit0. Keep existing key/default and CSS-alpha mechanism. Render standard `<input type="range" min={0} max={100} step={1} aria-label="背景透明度" ... />` with percent output. Change existing CSS selectors from select to range; remove helper text in both apps. Preserve gear, text alpha and local state.
- [x] Repeat targeted tests; run `pnpm typecheck` and full `pnpm test`. Review against approved requirements, then quality review. Commit only task files.

## T2 — count provenance

Files to inspect: `crates/slk-state-core/src/query.rs`, existing query tests, `apps/slk-bi/src/contracts.ts`, `runPresentation.ts`, `runPresentation.test.ts`, `src/webbi/contracts.ts` and contract tests. Existing stored `plan_revisions.snapshot_json` and `CELL_SPLIT.details_json` are authority; frontend plan metadata currently omits snapshot.

- [x] Trace initial snapshot and split-detail shape, including nested split and non-split plan changes. Choose a minimal optional read projection; do not expose entire snapshot or create persistent counters.
- [x] Add fixture-driven RED tests for initial3 -> split1to2 -> splitchild1to3, ordinary addition/deletion and missing snapshot; `initial+net` only if provenance and effective-total reconciliation hold. Current total and completion never depend on optional history.
- [x] Implement the read-only summary and shared presentation; include exact initial/split counts only when derivable. Old uploads missing the field remain valid. No DB migration/write.
- [x] Run query + presentation + WebBI contract regressions. Independently review before integration.

## T3–T6 — diagnosis-driven repair tasks

The approved design lists exact invariants and counterexamples. Each repair receives a concrete source/test patch plan once the current failing seam is reproduced; do not prewrite speculative replacements for unknown MCP/endpoint/audit causes.

- T3: `src/slk_transport/adapters/ocrv.py`, `native_activity.py`, `native_ocrv.py` if present, actual native OCRV source/capability after verification. Tests: `tests/transport/test_ocrv_adapter.py`, `test_native_activity.py`, `test_ocrv_native_session.py`. No silent truncation; exited launcher is not stopped executor.
- T4: `src/slk_transport/role_host.py`, native-activity recovery helpers and their existing tests. Exact original/recovery identities and historical plan remain traceable; deduplicate actual native calls, not messages; cache only within inspection and retain original observed_at.
- T5: `crates/slk-state-core/src/write.rs`, `crates/slk-state-core/tests/write_flow.rs`, `integrations/temporal/src/slk_temporal/workflows.py` and `tests/temporal/test_run_pause.py`. Preserve pause identity, no fabricated PAUSED/time, late signals safe, replay compatibility. R3 changes require actual event-chain evidence; original close-run pair is already complete and must not be reopened.
- T6: original `skills/slk-overwatch-run/` instructions plus consumer fixture test; separate OW self-liveness from observed members. Adjust only actual BI-version compatibility gate after preserving binary/source identity validation.

For each task: document smallest reproduction → run RED → minimal implementation → targeted GREEN → existing adjacent tests → spec review → quality review → focused commit. Tests execute against isolated fixtures, never production database or agent sessions.

## T7 — integration and handoff

- [x] Update BI version references, matching source docs and precompiled artifact metadata coherently; do not bump method version without a selected release number.
- [x] Run full frontend tests/typecheck/build; relevant Python suite; Rust query/write/desktop tests; affected Temporal tests and available replay fixtures. Clearly identify skipped environmental/live tests.
- [x] Build native BI and affected tool archives in this workspace, with exact source/hash records. Do not replace installed binaries, publish tags or mutate cloud deployment in this phase.
- [x] Run repository validator/manifest and whitespace checks. Final independent review checks no 3.x/live-state changes, no new material limits, no false STOPPED/PASS, no shadow BI state. Repository/build/archive tests: 43 passed; README explicitly distinguishes unpublished candidates from the prior deployed baseline.
- [x] Report implementation vs artifact vs native-visual/deployment verification separately. Keep unresolved root causes explicit rather than claiming all seven fixed.
