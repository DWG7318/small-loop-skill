# Validation Report — SLK 3.0.7 Candidate

Date: 2026-09-14

Branch: `feature/slk-3.0.7-loop-token`

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
- one current visible `SLK TOKEN` that follows the existing handoff route, while other member recovery stays with the upper-level member;
- Owner-specified role models preserved across rework unless Owner changes the choice;
- D2 readiness based on D1 PASS or separately recorded Supervisor exemption, never a bare D1 FAIL;
- Checker capacity calibration reuses execution and D1 facts instead of adding a separate capacity gate;
- guidance oriented toward recovery and continued construction.
- one Checker dispatch carries the complete CELL rather than a command queue;
- Worker commands, tool results, and intermediate progress remain inside that CELL until complete candidate delivery, a real blocker, or necessary clarification.
- later CELLs, especially those that join or fuse earlier work, retain more planning headroom and are split smaller when practical.
- D0, D1, and D2 remain inspection layers and are not planned again as inspection-only construction CELLs;
- midstream adoption preserves and reuses completed work before selecting the reasonable minimum construction needed to reach the current target reliably.
- checks prefer existing product entrances, use extra tools for concrete evidence gaps, and avoid recursive checker-proof engineering;
- checking-tool/environment failures are distinct from product defects; insufficient evidence remains unproved rather than PASS;
- rework and D2 reuse objective evidence only while applicable to the candidate, environment and risks, without inheriting lower-level PASS conclusions;
- root history preserves failures, rework and exemptions as concise facts and evidence references; the duplicate D2 checklist is removed.
- nine affected Skills pair corrected primary guidance with one compact, independent negative-prompt section, without another workflow or universal stop gate;
- important Supervisor activation failures, decisions and unexecuted operations are recorded before further adjustment can overwrite necessary evidence; this is not daily progress monitoring;
- local D0 draft attempts remain distinct from Worker rework after Checker D1 FAIL;
- complete CELL dispatch transfers the token and ends its activation; the recipient acts in that activation without an extra token-specific receipt, while candidate delivery separately activates isolated D1;
- unaffected, still-valid completed work is retained during rework, without obstructing necessary repairs to affected work.
- the latest successful token transfer identifies the current responsibility and last confirmed boundary without claiming live execution;
- monotonically increasing token identity prevents stale or duplicate deliveries from reopening a CELL, while recovery retries retain the original identity;
- the root Run record stores the current token pointer, last real transfer and full engineering history without a second state system.

## Verification status

Fresh local verification:

- `python scripts/validate_repository.py`: PASS;
- repository `scripts/quick_validate.py`: 13/13 Skill directories PASS;
- official Skill Creator `quick_validate.py`: 13/13 PASS under UTF-8 mode;
- current-version and four token/record regressions: expected failures before the 3.0.7 changes, then PASS; these check repository guidance, not runtime compliance;
- one isolated before/after decision scenario: published 3.0.6 correctly refused to infer live work from a stale running indicator, but lacked an authoritative transfer identity and duplicate handling. Revised guidance identifies the exact current responsibility, reports unconfirmed execution honestly and prevents stale/duplicate delivery from reopening the CELL. This bounded sample does not guarantee future agent compliance;
- independent review found and closed token-record timing, initial-token ownership, stale-ordering, transfer-failure and recovery-envelope ambiguities. Prompt-contract tests cannot simulate the platform transport runtime; the bounded behavioral pressure test therefore remains supporting evidence rather than a runtime guarantee;
- `python -m pytest -q`: 57/57 PASS;
- active legacy-topology scan: 0 Control/Verifier/Patrol/D3/Owner-acceptance matches;
- active language review: the independent negative sections deliberately use direct “不要…” reminders requested by Owner; they clarify known misuse, not a second workflow, new approval or stop policy. The SLK-only boundary remains in 12/12 children;
- Skill size review: main and child `SKILL.md` files remain 30–64 lines and 558 lines combined, unchanged from published 3.0.6;
- repository inventory: 43 tracked files and 42 manifest-protected payload files;
- `git diff --check`: PASS.

The 3.0.7 candidate preserves the same 13-Skill collection and extends the existing Run-record template only with the current-token pointer and last-real-transfer fields; its Manifest is regenerated from the exact final repository bytes. The 3.0.5 inspection-load reduction and 3.0.6 prompt repairs remain intact. No workflow engine, runtime, eval framework, Temporal dependency, project checking system, additional role/inspection layer or product change is included.

The 2.x active root, mirrors, contracts, templates, runtime validators and old tests were removed from the 3.0 branch after replacement coverage passed. Git history and the `v2.6.0` tag preserve the previous files.

## Historical boundary

The previously recorded `v2.6.0` recovery commit is `fa75bcf1c0819c8499d3b6c4ee9ec251dae62ae5`; this Cell does not change that historical release. The baseline is published 3.0.6 at `2560b7a1d5577be4893deded8e7169028e7c1eb2`. Before formal release, this candidate has not changed main, remote tags/Releases or global installation. Local validation is not a release claim.
