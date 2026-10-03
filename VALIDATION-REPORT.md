# Validation Report — SLK 4.3.5 Candidate

Date: 2026-10-01

Branch: `feature/slk-4.3.5-native-activity`

Base: `02910d9` (`v4.3.4`)

## Scope

SLK 4.3.5 is a schema-v8-compatible transport correction. It replaces presence-only start markers with a closed native-start receipt, gives every runtime one read-only native-activity query, separates Worker completion from externally started Checker review, and preserves an exact same-candidate recovery path for a legacy false start. The old attempt, candidate, TOKEN history and product tree remain immutable.

The existing Codex Supervisor, OCRV Checker, DSH Worker, optional whole-Run Overwatcher, serial CELL/D0/D1/D2 topology, direct communication, BI authority and optional Temporal templates are unchanged. No AX, Orca, wmux, BoM, new role, daemon, heartbeat, MCP, scheduler, Docker dependency or product method was introduced.

## Verification evidence

- Python suites: 414 passed and two optional modules skipped in ordinary mode; the same 414 passed under `python -O` with only pytest's expected optimized-assertion warning. Focused native activity/OCRV/D1/Skill/Eval coverage also passed, including wrong-message and conflicting terminal evidence, current multi-segment OCRV activity, false-start recovery, exact Checker D1 authorship, the managed launcher, and installed DSH/OCRV classifications.
- Rust core packages: 116 integration tests passed; unit and documentation targets passed. `cargo fmt --all -- --check` passed.
- LE BI/WebBI 1.1.0: 61 tests passed; TypeScript typecheck and production UI build passed. Real retained Runs proved that current Checker session recovery and Supervisor role closure remain eligible messages, while unsupported historical role/type pairs cannot become notifications or block the desktop surface or upload.
- Role Eval: 75 closed cases, PASS; case-pack SHA-256 `05694fb2508602500f05c8a73f7c3d26eafe327e9533277ae3a81ba97874ce1b`.
- Repository identity, JSON/YAML/schema parsing, root/install package mirrors, deterministic package verification, version/Manifest hashes, `git diff --check`, and sensitive/forbidden-scope scans are release gates. The package has no hard dependency on Temporal, Docker, AX, Orca, wmux, an Overwatcher, or another runtime service.

## Release artifacts

- `slk-bi-desktop.exe`: `5b49130d5456dd546f3471bbac54bfa80311e00391cd2795a36711783742f39e`
- `slk-bi-query.exe`: `78a53719bd450897d8300cb1028c32529696480f163f18038e528d8854d425e2`
- `slk-cargo.exe`: `35c92572de691425294ae9b58465849dcbd4693e2e75b0348e92762519171f71`
- `slk-state.exe`: `edd1f17c3526274c01430288dbbdf017e7bd7df6e908ebca2eec4cd462146e86`
- `slk-transport.pyz`: `9cc177dbca98580f5770ed793892a2bbc0464a3cbf54b8b9e2b863fd7f964cf7`

## Migration and deployment boundary

Explicit `4.3.4 → 4.3.5` adoption preserves Run ID, plan revision, current CELL/attempt, TOKEN holder/sequence, role endpoints, candidate, D0/D1/D2 history, Overwatcher binding/incidents, transport evidence and product changes. Installation alone does not adopt, resume, dispatch, inspect or mutate a Run.

New starts require `slk.native-start/v2`. A preserved legacy receipt is history, not proof. If its TOKEN already reached the exact Checker, recovery reuses the same Run/CELL/candidate/message under `.native-recovery-v2`, does not replay Worker or recommit TOKEN, externally starts OCRV, and lets the authenticated Checker bind and write the actual D1 result. Overwatcher and an enabled Temporal adapter reuse `inspect-native-activity`; missing, stale, mismatched, permission-blocked, wrong-attempt or conflicting terminal evidence remains `UNKNOWN`.

Final completion gates are the refreshed Manifest, deterministic local-package verification, transactional headless integration/global installation with installed hash/version checks, committed-tree review, safe fast-forward/tag identity checks and the formal Release.
