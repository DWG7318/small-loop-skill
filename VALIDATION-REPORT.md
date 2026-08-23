# Validation Report — SLK 3.0.2 Candidate

Date: 2026-08-23

Branch: `design/slk-3.0.2-loop-engineering`

## Design baseline

- the linear Loop Engineering form: one bounded Run with linear GO and CELL work;
- visible Supervisor, Checker, and Worker conversations;
- minimum Worker D0, isolated Checker D1, combined-result Supervisor D2;
- event-activated Supervisor boundaries with Checker/Worker ownership of the daily CELL loop;
- D1 and D2 evidence ordering that delays lower-level conclusions until an independent judgment exists;
- one root `SLK-RUN-<RUN-ID>.md` with per-role records;
- one main router and 12 situational sibling Skills;
- every companion Skill identifies itself as Small Loop Skill (SLK)-only in both discovery metadata and its opening guidance;
- role-based model selection with stronger professional coding capability for Supervisor and Checker and a reliable, optionally one-tier-lower Worker;
- role-model selection before initial CELL sizing, followed by dispatch-time reality checks rather than a second planning flow;
- exact startup authority: Original creates Supervisor, Supervisor creates Checker, Checker passes role readiness and creates Worker;
- root-record initialization after Supervisor Grill and before Checker/Worker creation;
- visible conversations rather than subagents as formal members, with recorded communication tests reused when unchanged;
- a narrow Worker-to-Checker receipt recovery route, while other member recovery stays with the upper-level member;
- Owner-specified role models preserved across rework unless Owner changes the choice;
- D2 readiness based on D1 PASS or separately recorded Supervisor exemption, never a bare D1 FAIL;
- Checker capacity calibration reuses execution and D1 facts instead of adding a separate capacity gate;
- guidance oriented toward recovery and continued construction.

## Verification status

Fresh local verification:

- `python scripts/validate_repository.py`: PASS;
- repository `scripts/quick_validate.py`: 13/13 Skill directories PASS;
- official Skill Creator `quick_validate.py`: 13/13 PASS under UTF-8 mode;
- `python -m pytest -q`: 43/43 PASS;
- `python -O -m pytest -q`: 43/43 PASS with the expected pytest assertion-optimization warning;
- active legacy-topology scan: 0 Control/Verifier/Patrol/D3/Owner-acceptance matches;
- active advisory-language review: 0 legacy absolute or direct-stop expressions; the Owner-approved SLK-only boundary appears in 12/12 children;
- Skill size review: no diagnostics; main and child `SKILL.md` files are 26–64 lines;
- repository inventory: 42 tracked files and 41 manifest-protected payload files;
- `git diff --check`: PASS.

Temporary installation verification copied the 13 sibling Skill directories and 15 files to `D:\LCcoding\.codex\.tmp\slk-3.0.2-loop-engineering-install-20260823-a`. All copied files matched source bytes, the main router referenced each of the 12 child Skills once, and every copied Skill passed the official validator. The Run-record template retained SHA-256 `8d709c470e8c23c468e0637f277f9caa31e82b465d4c1d37dfc48bb57e345cea`.

The 2.x active root, mirrors, contracts, templates, runtime validators and old tests were removed from the 3.0 branch after replacement coverage passed. Git history and the `v2.6.0` tag preserve the previous files.

## Historical boundary

The `v2.6.0` tag resolves to `fa75bcf1c0819c8499d3b6c4ee9ec251dae62ae5` and remains the recovery source for the previous topology and contracts. This candidate has not changed remote branches, tags, Releases, or global installation.
