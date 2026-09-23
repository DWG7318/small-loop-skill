# Validation Report — SLK 4.2.6 Candidate

Date: 2026-09-23

Branch: `feature/slk-4.2.6-mechanical-worker-handoff`

Base candidate: `3012759c037de1029e76ef46b5835ea4be8605d6`

## Scope

SLK 4.2.6 is a narrow recovery correction derived from the accepted LCaS CELL03 postmortem. It preserves the Codex Supervisor ↔ OCRV Checker ↔ DSH Worker topology, CELL, D0/D1/D2, TOKEN, BI authority, model policy and optional whole-Run Overwatcher.

The patch binds Worker completion to the exact run/CELL/attempt/candidate/message, maps rework acceptance criteria into Checker D1, changes active-writer recovery to read+steer without a conflicting resume, gives detached headless Checker transport an independent Windows job lifetime, and allows only Supervisor to resume the same Overwatcher Session on a new foreground turn after the last recorded anomaly cycle. Code/test completion alone does not complete the Worker role; D0, candidate submission and exactly one Checker handoff remain required. Tool failure stays in the same D1 attempt as `TRANSPORT_FAILED` or INCOMPLETE.

The BI release correction keeps the read-only UI and method semantics unchanged. It enables Tauri production/custom-protocol by default, introduces one headless release artifact entrypoint, and rejects Vite development entrypoints before package installation. Runtime acceptance is a cold start with no localhost:1430 listener rather than a development server workaround. Visible typography is uniformly 120% of its original size, while icons, window controls and progress segments remain unchanged; only active Run lists with six or more entries receive a five-row internal scrolling viewport, and the document itself cannot scroll.

## Evidence

- RED first: four Python failures and the missing Rust resume contract reproduced the frozen gaps before implementation.
- Focused Rust Overwatcher tests: 26 passed.
- Focused Python transport/completion tests: 28 passed.
- Rust workspace: 97 executed tests passed; doc tests passed.
- Python full suite: 270 passed.
- Python optimized-mode suite: 270 passed; the expected pytest warning notes that Python `assert` statements are disabled under `-O`, while validator paths remained green.
- Role Eval case pack: 62 cases, PASS; SHA-256 `365573b3390d9a49d03e66afc85dd431b7ef9d512b0c86e7d7e40f1b05cc7c2a`.
- Repository validator and Cargo workspace check: PASS.
- Skill collection remains 15 Skills; the main and Overwatcher instructions remain below repository size limits after replacing redundant text.
- Windows launch paths remain headless; detached transport adds `CREATE_BREAKAWAY_FROM_JOB` without adding a daemon, heartbeat, scheduled task or workflow engine.
- BI release-focused Python tests cover feature binding, the Tauri-only build entrance, fingerprint validation, rejection of Vite development artifacts, the 120% typography tokens, and the exclusive six-plus internal scroll surface.
- Frontend tests: 7 files / 19 tests passed; strict TypeScript passed; the production Vite/Tauri build passed from a fresh external target.
- Fresh BI artifact SHA-256: `87ead858dcf0134e224593d9f4d4b017bf0e068bc88528976a4f564bd2765862`; production fingerprint contains `custom-protocol`, and the executable contains no `@vite/client` or `/src/main.tsx` marker.
- Staging cold start with no port 1430 listener: responsive `LE BI` window, zero network connections, unchanged database/WAL hashes, no new WebView2 `ERR_CONNECTION_REFUSED`, no document scrollbar for the single active Run, and the current LCaS R3B row displayed. Owner visually accepted the corrected window.

## Boundaries

No LCaS product file, candidate, CELL04, D2, Docker, model policy, remote branch, tag or Release was changed. The local package installer performs a hash-verified atomic replacement and retains the prior installation as the rollback point; the actual machine-install receipt is produced only after this candidate is committed and packaged.
