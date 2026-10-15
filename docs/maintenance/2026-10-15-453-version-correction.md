# SLK 4.5.3 release correction

Owner decision (2026-10-15): the approved BI 1.1.3 / Run09 maintenance delivery is SLK **4.5.3**, not another 4.5.2 build. Future SLK releases use plain patch increments. BI remains 1.1.3; project 3.1.0 stays deferred.

## Plan

1. Complete: correct current release identity and add 4.5.3 to the existing method contracts, retaining historical 4.5.2 behavior and records.
2. Active: verify the focused version paths and regenerate the required precompiled artifacts and exact source/output provenance.
3. Pending: merge/push main, publish `v4.5.3`, supersede the mistakenly named release, install locally and retire only superseded code while retaining rollback/data/configuration.

Baseline check failed as expected: source `VERSION` was 4.5.2, while Owner requires 4.5.3. Existing source and package delivery evidence remains historical evidence and is not relabeled. No existing Run, live provider session or Temporal workflow is migrated/restarted by this correction.

Execution receipts will be recorded under `D:/LCcoding/.codex/.tmp/453-release/`; this plan is not installation evidence.

Focused verification: 725 Python cases passed (one real isolated-SDK service case deselected), 77 Rust OW/core cases passed, 40 role-eval/build-metadata cases passed, and all 21 Skills validated. New 4.5.3 cases failed before admission changes and passed after; old identities and unknown 4.5.4 rejection remain covered. Root Cargo.lock changes only the four current crate versions, preserving the third-party dependency graph.

The immutable BI 1.1.3 source prefix, tag, executable and original core pin are retained. State/query/cargo/transport are rebuilt; the new assembly records BI hash-verified reuse explicitly, not a new BI compilation. Temporal gets a new template wheel with unchanged native runtime bytes. No release tag or historical proof is rewritten.
