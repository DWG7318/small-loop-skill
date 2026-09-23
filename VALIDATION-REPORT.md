# Validation Report — SLK 4.2.6 Candidate

Date: 2026-09-23

Branch: `feature/slk-4.2.6-mechanical-worker-handoff`

Base candidate: `3012759c037de1029e76ef46b5835ea4be8605d6`

## Scope

SLK 4.2.6 is a narrow recovery correction derived from the accepted LCaS CELL03 postmortem. It preserves the Codex Supervisor ↔ OCRV Checker ↔ DSH Worker topology, CELL, D0/D1/D2, TOKEN, BI authority, model policy and optional whole-Run Overwatcher.

The patch binds Worker completion to the exact run/CELL/attempt/candidate/message, maps rework acceptance criteria into Checker D1, changes active-writer recovery to read+steer without a conflicting resume, gives detached headless Checker transport an independent Windows job lifetime, and allows only Supervisor to resume the same Overwatcher Session on a new foreground turn after the last recorded anomaly cycle. Code/test completion alone does not complete the Worker role; D0, candidate submission and exactly one Checker handoff remain required. Tool failure stays in the same D1 attempt as `TRANSPORT_FAILED` or INCOMPLETE.

## Evidence

- RED first: four Python failures and the missing Rust resume contract reproduced the frozen gaps before implementation.
- Focused Rust Overwatcher tests: 26 passed.
- Focused Python transport/completion tests: 28 passed.
- Rust workspace: 97 executed tests passed; doc tests passed.
- Python full suite: 263 passed.
- Python optimized-mode suite: 263 passed; the expected pytest warning notes that Python `assert` statements are disabled under `-O`, while validator paths remained green.
- Role Eval case pack: 62 cases, PASS; SHA-256 `365573b3390d9a49d03e66afc85dd431b7ef9d512b0c86e7d7e40f1b05cc7c2a`.
- Repository validator and Cargo workspace check: PASS.
- Skill collection remains 15 Skills; the main and Overwatcher instructions remain below repository size limits after replacing redundant text.
- Windows launch paths remain headless; detached transport adds `CREATE_BREAKAWAY_FROM_JOB` without adding a daemon, heartbeat, scheduled task or workflow engine.

## Boundaries

No LCaS product file, candidate, CELL04, D2, Docker, model policy, remote branch, tag or Release was changed. The local package installer performs a hash-verified atomic replacement and retains the prior installation as the rollback point; the actual machine-install receipt is produced only after this candidate is committed and packaged.
