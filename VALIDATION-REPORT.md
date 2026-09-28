# Validation Report — SLK 4.3.1 Candidate

Date: 2026-09-28

Branch: `feature/slk-4.3.1-field-corrections`

Base: `bdb0e27607da928a20f351ed94494544bef8502c`

## Scope

SLK 4.3.1 is a schema-v8-compatible patch over 4.3.0. It preserves Codex Supervisor, OCRV Checker, DSH Worker, the optional whole-Run Overwatcher, serial CELL/D0/D1/D2, one TOKEN, direct communication, read-only BI and optional Temporal continuity. It adds no role, scheduler, heartbeat, daemon, BoM path or product mutation.

The patch closes the observed same-class gaps: unsupported linked-worktree Git writes, truthless Worker terminal outcomes, mismatched D1/rework authority, incomplete Codex active-turn reads, missing immutable Worker inspection, repeated Overwatcher incident collisions and turn endings, monolithic OCRV timeout evidence loss, and context-restoration drift. The repository-wide audit is recorded in `docs/maintenance/2026-09-28-slk-4.3.1-consistency-audit.md`.

## Verification evidence

- Full Python suite: 340 passed and two optional Temporal SDK modules skipped when `temporalio` is absent. The same full suite is run under `python -O`; focused transport, state, Skill, role and package RED/GREEN cases also pass independently.
- Rust workspace: 115 integration tests passed; unit and documentation targets passed. State tests cover exact Supervisor rework authority, stale/cross-scope rejection, two independent Overwatcher pause/resume occurrences, and preserving `4.3.0 → 4.3.1` adoption. `cargo check --workspace` and `cargo fmt --check` pass.
- LE BI: 24 tests passed; TypeScript typecheck and production UI build passed. Role Eval: 70 cases, PASS; case-pack SHA-256 `ee7ff5f8a0207141b8b7dd21f9faba1a703e42ecba87b79550ae86d34cbbda5b`.
- Repository/schema/manifest validation, Temporal-off direct import, package mode and transactional install/rollback tests pass. The package contains 74 hash-bound managed files.
- Clean release artifacts were built headlessly in an isolated Cargo target:
  - `slk-bi-desktop.exe`: `cc9f177a5eeea0f8f840c29f4889f1fbc5323565809b864c4cf8febf09ebab15`
  - `slk-bi-query.exe`: `a2c46012817512bf86155d7a9826fd95adf38fb03f4ff3615597f3d91d19ae7e`
  - `slk-cargo.exe`: `7efae278ac6adcf4cd4f8c7872f20b5c2838596fa215d5cc60e6af1b4666e078`
  - `slk-state.exe`: `40fe1129e28ad5a17f96d64f1679747e5f8fdd6e049271f5a2140f01103db9a9`
  - `slk-transport.pyz`: `32e47238d33ea2ee667b8448263af8f4ee7ef24e88f3ff801ef221cc526363d2`
- `git diff --check bdb0e27607da928a20f351ed94494544bef8502c..HEAD`, JSON/schema parsing, source/package/install mirrors, scope and sensitive-value scans are final completion gates.

## Migration and deployment boundary

Explicit 4.3.0-to-4.3.1 adoption preserves Run ID, plan revision, TOKEN holder/sequence, roles/endpoints, candidate, D0/D1/D2 history, Overwatcher binding/incidents, attempt evidence and uncommitted product changes. Installation alone does not adopt or resume a Run. Schema stays v8 with migrations `0001.sql` through `0008.sql`.

The candidate is locally committed and transactionally deployed only after every gate is green. Source, local package and `C:\Users\DWG\.codex` installed bytes are verified against their closed manifests. No main merge, push, tag, Release, Docker installation or LCaS product action is authorized.
