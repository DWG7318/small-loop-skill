# Small Loop Skill (SLK)

Current version: **3.1.1** (independent `maintenance/3.1.1` branch, based on `v3.1.0` / `e200966`; its 3.x lineage includes `v3.0.9` and `v3.0.8`)

SLK is the linear form of Loop Engineering for one bounded small or medium Run, or one relatively independent small/medium scope inside a larger project. GO and CELL work follow one serial path.

## Core

```text
Supervisor ↔ Checker ↔ Worker

CELL dispatch → Worker construction + D0 → candidate → isolated Checker D1 → PASS/rework → Supervisor D2 → finalize
```

```text
Plan Run/GO/checks → select role models → size initial CELLs
→ Original creates Supervisor and hands off → Supervisor Grill → root record
→ Supervisor creates Checker → Checker readiness → Checker creates Worker
→ communication tests → first CELL
```

Supervisor stays active during construction, using native waits and compact evidence to observe Worker/Checker with low token use, resolve onsite problems within existing authority, and record actions and results. Checker and Worker still own the daily CELL loop; Supervisor does not take over dispatch or independent D1. One current `SLK TOKEN` is carried by the existing visible handoff message: it identifies the last confirmed responsibility boundary but never proves live execution, and it adds no role, service, state file, or acknowledgement round. Checker dispatches CELLs and reviews them independently at D1. Worker implements one current CELL and performs a minimum D0 before delivery; both hand off as their final action, while Supervisor continues observing until Run closure or an explicit Owner stop.

Run planning keeps D0, D1, and D2 as the existing inspection layers instead of creating inspection-only CELLs. Checks prefer existing entrances and direct product evidence, distinguish checking-tool/environment failures from product defects, and reuse still-valid objective evidence without repeating whole lower-level reviews or building a checking system first; insufficient evidence stays unproved, not PASS. When SLK joins an already completed or partly completed project, the plan preserves and reuses completed work, then chooses the reasonable minimum construction route, scope, and engineering activity needed to reach the current target reliably—not merely the smallest code diff.

SLK guidance helps members decide how to continue. Rework, communication recovery, member recovery, plan adjustment, and exemption remain available as situational options.

Supervisor, Checker, and Worker are responsibilities, not product brands. The Owner confirms the actual Supervisor, Agent platforms and models; model names are capability recommendations, not an allowlist. `gpt-6.1-sol/high` is the Supervisor competence reference, not a reason to override the Owner or downgrade for low-token observation. Current-CELL D1 escalation and cause-based D2 decisions remain unchanged.

RTK, Probe CLI, and Ponytail are optional external efficiency aids. They may be installed once in the Codex-wide environment, but installation does not authorize use in a project: the Owner chooses them per Run. SLK uses them explicitly without automatic hooks, MCP, or extra agents; native commands and raw evidence remain the fallback and authority.

## Skill collection

The active collection lives in [`skills/`](skills/):

- [`skills/small-loop-skill/SKILL.md`](skills/small-loop-skill/SKILL.md) — lightweight identity and router;
- 13 sibling Skills for planning, role-based model selection, Supervisor Grill, team lifecycle, CELL work, recording, rework, adjustment, communication recovery, D2, and post-D2 finalization. Rework can call an available project-appropriate Debug Skill when root-cause diagnosis is needed.

The 13 companion Skills are not standalone methods. Each applies only inside a Run that has selected Small Loop Skill (SLK) and has been routed to that situation by the main Skill or the same collection flow. The current total of 14 is an inventory, not a permanent limit.

Ordinary work reads the main Skill and the current situational Skill. Additional guidance is loaded when the situation changes. When maintaining SLK prompts, pair corrections for demonstrated misuse with direct “Do not…” reminders in an independent negative-prompt section; revise existing reminders rather than stacking duplicates. These sections clarify the same method, not another workflow or an approval/stop checklist.

## Run record

Supervisor creates `SLK-RUN-<RUN-ID>.md` in the project root. Worker, Checker, and Supervisor add their own engineering facts, including the current token pointer and last real transfer; the full history stays in this record. The template is at [`skills/slk-record-run/assets/SLK-RUN.template.md`](skills/slk-record-run/assets/SLK-RUN.template.md).

The original workbook now has a formal closeout summary: actual author/timezone, outcomes, important problems and onsite treatment, remaining risks and evidence. The Agent supplies computer name, IP address and OS version; public egress IP is only recommended, unavailable values stay unknown, and BI performs no device probes. Later corrections append provenance without rewriting historical D2.

[`slk-finalize-run`](skills/slk-finalize-run/SKILL.md) handles only unfinished closeout after real D2 PASS or authorized termination: save the summary, reconcile the unique current status and CLOSED token, confirm the exact Worker/Checker activities ended, archive only those members, then let the original creator Supervisor read and archive through BI. Already completed steps are skipped. Method closure, BI local archival and cloud saving are separate facts; offline upload remains pending without repeating preparation, D0/D1/D2 or reopening engineering. Keep Supervisor and original records.

## Install

Use independent, precompiled BI/WebBI 1.1.6 or a compatible newer build with the existing Markdown record; see [BI usage](skills/slk-record-run/references/bi.md). No 4.x method runtime, OW, Temporal, state database or RoleHost is imported. No Rust/Node build tools are needed on the usage side. Ended Agent turns do not prove external Cargo/test jobs have ended.

Place the 14 directories under `skills/` as sibling directories in the Owner-selected project Skill root (for example `.agents/skills`). Verify the pinned commit/version and all 17 Skill payload hashes, then retire only superseded 3.x callable entries inside that authorized project; preserve unrelated Skills and old Run/evidence records. Do not overwrite global 4.x installations or another active Run's bound method. Invoke `$small-loop-skill`; it recommends the relevant sibling Skill as the Run changes.

## Validation

```text
python scripts/validate_repository.py
python scripts/quick_validate.py skills
python -m pytest -q
```

## Previous method

SLK **v2.6.0** remains available from its Git tag and Release for existing Runs or recovery. Version 3.0.0 starts a new method boundary and does not overwrite that historical release.

## License

MIT.
