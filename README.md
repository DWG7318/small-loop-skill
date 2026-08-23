# Small Loop Skill (SLK)

Current version: **3.0.0**

SLK guides one bounded small or medium engineering Run, or one relatively independent small/medium scope inside a larger project. GO and CELL work follow one serial path.

## Core

```text
Supervisor ↔ Checker ↔ Worker

Worker D0 → Checker D1 → Supervisor D2
```

```text
Plan Run/GO/checks → select role models → size initial CELLs
→ Original creates Supervisor and hands off → Supervisor Grill → root record
→ Supervisor creates Checker → Checker readiness → Checker creates Worker
→ communication tests → first CELL
```

Supervisor is activated for setup, escalated help, exemptions, member recovery, and D2. Checker and Worker own the daily CELL loop; Supervisor does not wait online for each CELL. Checker dispatches CELLs and reviews them independently at D1. Worker implements one current CELL and performs a minimum D0 before delivery.

SLK guidance helps members decide how to continue. Rework, communication recovery, member recovery, plan adjustment, and exemption remain available as situational options.

## Skill collection

The active collection lives in [`skills/`](skills/):

- [`skills/small-loop-skill/SKILL.md`](skills/small-loop-skill/SKILL.md) — lightweight identity and router;
- 12 sibling Skills for planning, role-based model selection, Supervisor Grill, team lifecycle, CELL work, recording, rework, adjustment, communication recovery, and closure. Rework can call an available project-appropriate Debug Skill when root-cause diagnosis is needed.

The 12 companion Skills are not standalone methods. Each applies only inside a Run that has selected Small Loop Skill (SLK) and has been routed to that situation by the main Skill or the same collection flow.

Ordinary work reads the main Skill and the current situational Skill. Additional guidance is loaded when the situation changes.

## Run record

Supervisor creates `SLK-RUN-<RUN-ID>.md` in the project root. Worker, Checker, and Supervisor add their own engineering facts. The template is at [`skills/slk-record-run/assets/SLK-RUN.template.md`](skills/slk-record-run/assets/SLK-RUN.template.md).

## Install

Place the 13 directories under `skills/` as sibling directories in the Codex Skill root. The main router and 12 focused companion Skills cover planning, model selection, execution, checking, recovery, records, and closure. Invoke `$small-loop-skill`; it recommends the relevant sibling Skill as the Run changes.

## Validation

```text
python scripts/validate_repository.py
python -m pytest -q
```

## Previous method

SLK **v2.6.0** remains available from its Git tag and Release for existing Runs or recovery. Version 3.0.0 starts a new method boundary and does not overwrite that historical release.

## License

MIT.
