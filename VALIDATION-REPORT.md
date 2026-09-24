# Validation Report — SLK 4.2.7 Candidate

Date: 2026-09-24

Branch: `feature/slk-4.2.7-preflight-transport-compat`

Base candidate: `002aaecc9c500149d702de268b151f6dcc22e254`

## Scope

SLK 4.2.7 is a narrow compatibility and role-local preflight patch over the accepted 4.2.6 method. It preserves the Codex Supervisor ↔ OCRV Checker ↔ DSH Worker topology, one formal CELL/D0/D1/D2 path, TOKEN authority, BI authority, model policy and optional whole-Run Overwatcher. It does not introduce BoM, a scheduler, heartbeat, daemon, workflow engine, extra role, formal sub-CELL, extra D1 attempt or automatic D2.

Worker and Checker now perform bounded local preflight before work: the Worker may sequence implementation, test and evidence steps inside one frozen CELL, while the Checker may sequence criterion-bound D1-A/D1-B/D1-C inspection inside one formal D1. Missing proof, unsupported coverage or tool failure produces INCOMPLETE; a material criterion-bound product defect produces FAIL; zero comments, zero findings or empty evidence never produces an automatic PASS. Supervisor involvement remains exception-driven and restores the same members instead of taking over ordinary execution.

The transport patch resolves a stale absolute Codex executable only to the currently discoverable Codex executable and records immutable rebind evidence. Codex delivery reads thread state before resume, never resumes an active writer, and resumes only a not-loaded thread. OCRV requests now match the installed v1.12.7 closed request contract while retaining OCRV-generated result identity. DSH completion may recover an omitted repository only from the authenticated immutable Worker endpoint; retries reuse the first canonical request bytes when only the proposed timestamp differs. Windows bounded subprocess cleanup terminates the whole process tree headlessly.

The accepted 4.2.6 LE BI behavior is preserved: immutable project identity supplies stable quiet project colors, status color remains separate, only six-or-more active Runs receive a five-row internal scrolling viewport, and the document itself does not scroll. This patch updates the packaged BI version but does not redesign the UI.

## Evidence

- RED first: stale Codex path, active-thread resume conflict, OCRV closed-contract mismatch, missing Worker repository, unstable retry bytes, missing role-local preflight language and Windows child-process timeout were reproduced before their fixes.
- Focused Python transport, completion and Skill checks: 155 passed.
- Windows process-tree timeout check: 1 passed.
- Rust workspace: 97 executed integration tests passed; doc tests passed.
- Cargo workspace check and debug builds for `slk-state`, `slk-bi-query` and `slk-cargo`: PASS.
- Real installed OCRV v1.12.7 contract probe against a tiny isolated repository: PASS in 12.6 seconds; OCRV supplied `review_invocation_id=b43bf42e-8f2d-47e9-a2c7-7d360f6fed82` and `session_id=b5d6fa40-ebdc-4f97-a810-f7af3f6700e0`.
- Python full suite: 280 passed.
- Python optimized-mode suite: 280 passed; the expected pytest warning notes that Python `assert` statements are disabled under `-O`, while validator paths remained green.
- Role Eval case pack: 62 cases, PASS; SHA-256 `4618248ad22e0c5d75eae63abba51c609c384e2063250c22b1d319d3204c5104`.
- Repository validator and `git diff --check`: PASS.
- Release artifacts, package installation and installed-tree hashes are recorded by the final package gate.
- Windows launch and cleanup paths use hidden process creation; no PowerShell, cmd or helper console is introduced.

## Boundaries

No LCaS product file, candidate, CELL, D2, Docker, model policy, remote branch, tag or Release is changed. The package installer performs a hash-verified atomic replacement and retains the previous installation as the rollback point. Any running legacy Run adopts 4.2.7 only at an existing Supervisor-controlled method-contract boundary; history is not rewritten.
