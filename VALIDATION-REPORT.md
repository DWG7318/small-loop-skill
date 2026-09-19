# Validation Report — SLK 4.0.0 Candidate

Date: 2026-09-20

Branch: `feature/slk-4.0-cross-agent-transport`

## Accepted scope

SLK 4.0.0 keeps the 3.0.8 Small Loop Skill method: one bounded Run, one serial GO/CELL path, Supervisor, Checker, Worker, minimum Worker D0, isolated Checker D1, combined-result Supervisor D2, rework, exemption, communication recovery, and the existing 13-Skill collection.

The major-version addition is an executable state and observation layer:

- one configurable machine-wide data root and one versioned SQLite authority;
- one monotonic `SLK TOKEN` per Run, preserving the existing handoff route rather than scheduling work;
- Run, GO, CELL, plan-revision, role/session/endpoint, transport, inspection, correction, exemption, evidence, resource-contention, recovery, and closure facts;
- authenticated, Run-scoped writes limited to Supervisor, Checker, and Worker;
- append-only history, copied and hashed evidence, deterministic Markdown export, and exact correction links;
- explicit resource contention and recovery that retain responsibility and do not misclassify an occupied tool as D1 rework;
- stable read-only Agent projections through `slk-bi-query`;
- a standalone Tauri/React BI that uses the same Rust projections and exposes no write, acknowledgement, scheduling, transport, or control surface.

The state core does not create, wake, watch, replace, or infer live Agents. Native transport remains responsible for real activation and accepted-delivery evidence. BI displays recorded facts only. It does not prove that a process is currently working and does not add Owner or Overwatcher write authority.

## Fresh verification

Repository and Python:

- `python -m pytest -q` with externally built `slk-state` and `slk-bi-query`: **121 passed**, 0 failed, 0 skipped;
- `python scripts/quick_validate.py`: **13/13 Skill directories PASS**;
- `python scripts/validate_repository.py`: PASS;
- manifest discovery regression: tracked and non-ignored new release files are included, while ignored local build output is excluded;
- `git diff --check`: PASS.

Rust workspace, using Rust/Cargo 1.94.0 and an external `CARGO_TARGET_DIR`:

- `cargo fmt --all -- --check`: PASS;
- `cargo clippy --workspace --all-targets --offline -- -D warnings`: PASS;
- `cargo test --workspace --all-targets --offline`: **28 passed**, 0 failed;
- the 28 tests cover configuration, authorization, role replacement and session rebinding, concurrency, schema immutability and migration backup, TOKEN/write flow, transport failure, resource recovery, evidence, deterministic export, eight shared BI projections, and the desktop's read-only command surface.

SLK BI frontend:

- `pnpm --dir apps/slk-bi test`: **7 files / 11 tests passed**;
- `pnpm --dir apps/slk-bi typecheck`: PASS;
- `pnpm --dir apps/slk-bi build:ui`: PASS;
- production build excludes the development-only acceptance fixture;
- visual acceptance in the Codex in-app browser: default light, default dark, 980×700 constrained viewport, and collapsed Inspector all PASS;
- the accepted release-mode desktop executable was 10,627,072 bytes with SHA-256 `a83c56b77ebf01f777c69a8a8b393aca192734780493667ffa566c4b2d8536cb`.

## Cross-Agent and multi-Run acceptance

The state-core acceptance executed two independent Runs concurrently against one configured temporary data root. Each Run registered a distinct Supervisor, Checker, and Worker and completed the four-leg TOKEN route, D0, D1, D2, and `RUN_CLOSED`. The exercise also proved Checker replacement, session rebinding, correction without history rewrite, evidence hash verification, cross-Run credential rejection, deterministic export, and resource contention/recovery without TOKEN movement or false rework.

The BI acceptance queried all eight projections from the accepted two-Run database without changing its SHA-256. A combined 14-query projection set had SHA-256 `a0840473a44aa9ac4c2e5cbd3cc2384d9359eddb513a8da3b8e4e147f47bd115` and contained no credential value.

Human-readable evidence:

- [`docs/state/SLK-STATE-ACCEPTANCE.md`](docs/state/SLK-STATE-ACCEPTANCE.md)
- [`docs/state/SLK-BI-ACCEPTANCE.md`](docs/state/SLK-BI-ACCEPTANCE.md)

Machine-readable evidence remains outside the release payload:

- `D:\SLK\.codex\.tmp\slk-4-state-acceptance\acceptance-result.json`
- `D:\SLK\.codex\.tmp\slk-4-bi-acceptance\acceptance-result.json`

## Release boundary

This report establishes a locally verified 4.0.0 candidate. It does not claim a merge, push, tag, GitHub Release, global Skill deployment, or LCaS integration. The standalone BI is complete and independently usable; possible embedding in LCaS rc.08 or rc.09 remains future work and must preserve the read-only boundary.
