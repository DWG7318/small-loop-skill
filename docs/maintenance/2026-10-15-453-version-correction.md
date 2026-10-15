# SLK 4.5.3 release correction

Owner decision (2026-10-15): the approved BI 1.1.3 / Run09 maintenance delivery is SLK **4.5.3**, not another 4.5.2 build. Future SLK releases use plain patch increments. BI remains 1.1.3; project 3.1.0 stays deferred.

## Plan

1. Complete: correct current release identity and add 4.5.3 to the existing method contracts, retaining historical 4.5.2 behavior and records.
2. Complete: verify the focused version paths and regenerate the required precompiled artifacts and exact source/output provenance.
3. Active: merge/push main, publish `v4.5.3`, supersede the mistakenly named release, install locally and retire only superseded code while retaining rollback/data/configuration.

Baseline check failed as expected: source `VERSION` was 4.5.2, while Owner requires 4.5.3. Existing source and package delivery evidence remains historical evidence and is not relabeled. No existing Run, live provider session or Temporal workflow is migrated/restarted by this correction.

Execution receipts will be recorded under `D:/LCcoding/.codex/.tmp/453-release/`; this plan is not installation evidence.

Focused verification: 725 Python cases passed (one real isolated-SDK service case deselected), 77 Rust OW/core cases passed, 40 role-eval/build-metadata cases passed, and all 21 Skills validated. New 4.5.3 cases failed before admission changes and passed after; old identities and unknown 4.5.4 rejection remain covered. Root Cargo.lock changes only the four current crate versions, preserving the third-party dependency graph.

The immutable BI 1.1.3 source prefix, tag, executable and original core pin are retained. State/query/cargo/transport are rebuilt; the new assembly records BI hash-verified reuse explicitly, not a new BI compilation. Temporal gets a new template wheel with unchanged native runtime bytes. No release tag or historical proof is rewritten.

Final source checks: 199 Rust workspace tests and 97 state/query/recovery/closure tests against the newly compiled production executables passed. All six changed module archives restore with exact payload/source hashes; their published histories are rejoined without changing the parent tree. Independent BI compatibility uses the original 1.1.3 source and old Git core pin with a fixture created by the new 4.5.3 writer: all eight projections and three frontend contract tests pass. Its first read creates SQLite WAL coordination files (32 KiB SHM and empty WAL); the database, config and durable records stay byte-identical, and three subsequent full read cycles preserve every file. This is code-path and identity verification, not GUI or live-Run acceptance.

Sealed assembly proof: `2baa46ce75d24123ab465c960eff97b2f04258cf5ae319aad23746488e098499`. BI executable reuse: `2cdf857338dddc37a0d3edef2a1e4b45fbc06fac6a35dfc5a749a2b536e5ce0b`. Packaging, remote CI, installation and cleanup outcomes belong in the subsequent external delivery receipt; the source record does not claim those operations have already finished.
