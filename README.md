# Small Loop Skill (SLK)

Current version: **4.1.0**

SLK is the linear form of Loop Engineering for one bounded small or medium Run, or one relatively independent small/medium scope inside a larger project. One SLK is one Run, and the Run directly contains one serial CELL path.

## Core

```text
Supervisor ↔ Checker ↔ Worker

CELL dispatch → Worker construction + D0 → candidate → isolated Checker D1 → PASS/rework → Supervisor D2
```

```text
Plan Run/checks → select role models → size initial CELLs
→ Original creates Supervisor and hands off → Supervisor Grill → root record
→ Supervisor creates Checker → Checker readiness → Checker creates Worker
→ communication tests → first CELL
```

Supervisor is activated for setup, escalated help, exemptions, member recovery, and D2. Checker and Worker own the daily CELL loop; Supervisor does not wait online for each CELL. One current `SLK TOKEN` records the last confirmed responsibility boundary in the 4.0 state core. A sender advances it only after accepted native delivery, and the receiver records `WORK_STARTED` when real work begins; neither fact alone is used to pretend that a member is still working. Checker dispatches CELLs and reviews them independently at D1. Worker implements one current CELL and performs a minimum D0 before delivery.

Run planning keeps D0, D1, and D2 as the existing inspection layers instead of creating inspection-only CELLs. Checks prefer existing entrances and direct product evidence, distinguish checking-tool/environment failures from product defects, and reuse still-valid objective evidence without repeating whole lower-level reviews or building a checking system first; insufficient evidence stays unproved, not PASS. When SLK joins an already completed or partly completed project, the plan preserves and reuses completed work, then chooses the reasonable minimum construction route, scope, and engineering activity needed to reach the current target reliably—not merely the smallest code diff.

SLK guidance helps members decide how to continue. Rework, communication recovery, member recovery, plan adjustment, and exemption remain available as situational options.

RTK, Probe CLI, and Ponytail are optional external efficiency aids. They may be installed once in the Codex-wide environment, but installation does not authorize use in a project: the Owner chooses them per Run. SLK uses them explicitly without automatic hooks, MCP, or extra agents; native commands and raw evidence remain the fallback and authority.

Cross-Agent handoffs use the accepted `slk-transport` artifact with exact role endpoints and native Agent activation. A database row, background message, or conversation-title match is not delivery; the current sender hands off only after exact native-start evidence and otherwise keeps responsibility. See [`docs/transport/SLK-TRANSPORT.md`](docs/transport/SLK-TRANSPORT.md).

## 4.0 state and LE BI

SLK 4.0 adds one configurable machine-wide data root, a versioned SQLite authority, durable evidence, deterministic Markdown exports, and the standalone read-only **LE BI** desktop view. Supervisor, Checker, and Worker write only their own existing facts through the authenticated `slk-state` CLI; the database does not schedule work or add a fourth role. `slk-bi-query` exposes stable read-only JSON for Agents, while LE BI presents the same projections without credentials or mutation commands. The public method is `Run → CELL`; the 4.0 database retains its original grouping fields only for stored-data compatibility and LE BI does not expose them. See [`docs/state/SLK-STATE.md`](docs/state/SLK-STATE.md), [`docs/state/SLK-BI.md`](docs/state/SLK-BI.md), the independent [`state-core acceptance`](docs/state/SLK-STATE-ACCEPTANCE.md), and [`BI acceptance`](docs/state/SLK-BI-ACCEPTANCE.md).

LE BI displays active SLK Runs as compact rows, whether independent or owned by a CLK/GLK project. Expanding a row shows only that SLK's roles, models, and CELL records; completed, abandoned, and superseded SLKs move to the archive immediately. BI does not confirm message delivery, infer current process liveness, repair communication, or modify the Run. Future LCaS rc.08/rc.09 may embed these read components; that integration is not required to operate SLK 4.0.

## Skill collection

The active collection lives in [`skills/`](skills/):

- [`skills/small-loop-skill/SKILL.md`](skills/small-loop-skill/SKILL.md) — lightweight identity and router;
- 13 sibling Skills for planning, resource continuity, role-based model selection, Supervisor Grill, team lifecycle, CELL work, recording, rework, adjustment, communication recovery, and closure. Rework can call an available project-appropriate Debug Skill when root-cause diagnosis is needed.

The 13 companion Skills are not standalone methods. Each applies only inside a Run that has selected Small Loop Skill (SLK) and has been routed to that situation by the main Skill or the same collection flow.

Ordinary work reads the main Skill and the current situational Skill. Additional guidance is loaded when the situation changes. When maintaining SLK prompts, pair corrections for demonstrated misuse with direct “Do not…” reminders in an independent negative-prompt section; revise existing reminders rather than stacking duplicates. These sections clarify the same method, not another workflow or an approval/stop checklist.

## Run record

Supervisor initializes the Run and its first plan revision. Worker, Checker, and Supervisor append their own engineering facts to the configured SLK data root; deterministic `SLK-RUN-<RUN-ID>.md` exports are generated from that authority, outside the product repository. The template remains at [`skills/slk-record-run/assets/SLK-RUN.template.md`](skills/slk-record-run/assets/SLK-RUN.template.md) for readable structure and compatibility.

## Install

Place the 14 directories under `skills/` as sibling directories in the Codex Skill root. The main router and 13 focused companion Skills cover planning, resource continuity, model selection, execution, checking, recovery, records, and closure. Invoke `$small-loop-skill`; it recommends the relevant sibling Skill as the Run changes.

A new Windows machine also needs one-time DSH, OCRV, cross-Agent transport, and state-tool configuration. Follow the [`SLK 4.0 Windows runtime setup guide`](docs/runtime/SLK-WINDOWS-RUNTIME.md). These machine-level components are shared by projects rather than reinstalled for every project.

## Validation

```text
python scripts/validate_repository.py
python -m pytest -q
```

## Previous method

SLK **v3.0.8** remains the last lightweight prompt-only release, and **v2.6.0** remains the previous monolithic recovery release. SLK 4.0 keeps the 3.x method semantics and adds durable cross-Agent state and read-only presentation rather than replacing the three-role Loop.

## License

MIT.
