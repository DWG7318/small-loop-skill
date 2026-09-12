# Validation Report — SLK 3.0.5 Candidate

Date: 2026-09-13

Branch: `feature/slk-3.0.5-minimal-construction`

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
- one Checker dispatch carries the complete CELL rather than a command queue;
- Worker commands, tool results, and intermediate progress remain inside that CELL until complete candidate delivery, a real blocker, or necessary clarification.
- later CELLs, especially those that join or fuse earlier work, retain more planning headroom and are split smaller when practical.
- D0, D1, and D2 remain inspection layers and are not planned again as inspection-only construction CELLs;
- midstream adoption preserves and reuses completed work before selecting the reasonable minimum construction needed to reach the current target reliably.

## Verification status

Fresh local verification:

- `python scripts/validate_repository.py`: PASS;
- repository `scripts/quick_validate.py`: 13/13 Skill directories PASS;
- official Skill Creator `quick_validate.py`: 13/13 PASS under UTF-8 mode;
- focused planning semantics: 2/2 tests failed against the 3.0.4 planning text, then 3/3 plan-run tests PASS after the patch;
- `python -m pytest -q`: 45/45 PASS;
- active legacy-topology scan: 0 Control/Verifier/Patrol/D3/Owner-acceptance matches;
- active advisory-language review: 0 legacy absolute or direct-stop expressions; the Owner-approved SLK-only boundary appears in 12/12 children;
- Skill size review: no diagnostics; main and child `SKILL.md` files are 26–64 lines;
- repository inventory: 43 tracked files and 42 manifest-protected payload files;
- `git diff --check`: PASS.

The 3.0.5 candidate preserves the same 13-Skill collection and Run-record template; its release Manifest is regenerated from the exact repository bytes after the planning clarification.

The 2.x active root, mirrors, contracts, templates, runtime validators and old tests were removed from the 3.0 branch after replacement coverage passed. Git history and the `v2.6.0` tag preserve the previous files.

## Historical boundary

The `v2.6.0` tag resolves to `fa75bcf1c0819c8499d3b6c4ee9ec251dae62ae5` and remains the recovery source for the previous topology and contracts. This candidate has not changed remote branches, tags, Releases, or global installation.
