# Validation Report — SLK 3.0.0 Candidate

Date: 2026-08-22

Branch: `feature/slk-3.0.0-lightweight`

## Design baseline

- one bounded Run with linear GO and CELL work;
- visible Supervisor, Checker, and Worker conversations;
- minimum Worker D0, isolated Checker D1, combined-result Supervisor D2;
- one root `SLK-RUN-<RUN-ID>.md` with per-role records;
- one main router and 12 situational sibling Skills;
- initial CELL planning before Supervisor creation, followed by dispatch-time reality checks rather than a second planning flow;
- guidance oriented toward recovery and continued construction.

## Verification status

Fresh local verification:

- `python scripts/validate_repository.py`: PASS;
- repository `scripts/quick_validate.py`: 13/13 Skill directories PASS;
- official Skill Creator `quick_validate.py`: 13/13 PASS under UTF-8 mode;
- `python -m pytest -q`: 30/30 PASS;
- `python -O -m pytest -q`: 30/30 PASS with the expected pytest assertion-optimization warning;
- active legacy-topology scan: 0 Control/Verifier/Patrol/D3/Owner-acceptance matches;
- active advisory-language review: 0 flagged absolute or direct-stop expressions;
- Skill size review: no diagnostics; main and child `SKILL.md` files are 23–41 lines;
- repository inventory: 40 tracked files and 39 manifest-protected payload files;
- `git diff --check`: PASS.

Temporary installation verification copied the corrected 13 sibling Skill directories to `D:\LCcoding\.codex\.tmp\slk-3.0.0-install-simple-cell-split`. All copied files matched source bytes, the main router referenced each of the 12 child Skills once, and every copied Skill passed the official validator. The installed Run-record template matched source bytes with SHA-256 `2327ae67f0c89cd31eb12f6ae90a64ae6044c59df400fcd29d609e67c648c6cd`.

The 2.x active root, mirrors, contracts, templates, runtime validators and old tests were removed from the 3.0 branch after replacement coverage passed. Git history and the `v2.6.0` tag preserve the previous files.

## Historical boundary

The `v2.6.0` tag resolves to `fa75bcf1c0819c8499d3b6c4ee9ec251dae62ae5` and remains the recovery source for the previous topology and contracts. This candidate has not changed remote branches, tags, Releases, or global installation.
