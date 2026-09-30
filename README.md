# Small Loop Skill (SLK)

Current version: **4.3.4**

SLK is the linear form of Loop Engineering for one bounded small or medium Run, or one relatively independent small/medium scope inside a larger project. One SLK is one Run, and the Run directly contains one serial CELL path.

## Core

```text
Supervisor ↔ Checker ↔ Worker

        optional Overwatcher (observe/recover/escalate only)

CELL dispatch → Worker construction + D0 → candidate → isolated Checker D1 → PASS/rework → Supervisor D2
```

```text
Plan Run/checks → verify fixed role bindings/options with `preflight-run` → size initial CELLs
→ Original creates Supervisor and hands off → Supervisor role Eval → root record
→ Supervisor creates Checker → Checker role Eval → Checker creates Worker
→ communication tests → first CELL
```

Codex is the Supervisor (`gpt-5.6-sol` + `xhigh`), OCRV is the Checker (Qwen3.8-Max), and DSH is the Worker (DeepSeek V4 Flash); runtime, model, session, and adapter identities are validated instead of inferred from prompts. Supervisor is activated for setup, escalated help, exemptions, member recovery, and D2. Checker and Worker own the daily CELL loop; Supervisor does not wait online for each CELL. D1 PASS advances acceptance; D1 INCOMPLETE leaves D1 open and TOKEN with Checker; a formal D1 FAIL alone permits the closed `Checker → Supervisor → same Worker` rework route, where Supervisor supplies a structured directive without redoing D1. A Run may additionally bind one dedicated, non-reusable Overwatcher Agent Session. Once bound, that same Session keeps one foreground active turn and performs a complete proactive cycle every 180–300 seconds; it is not a heartbeat, scheduled task, daemon, background Agent, relay, BI/TOKEN editor, or D0/D1/D2 authority.

Run planning keeps D0, D1, and D2 as the existing inspection layers instead of creating inspection-only CELLs. Checks prefer existing entrances and direct product evidence, distinguish checking-tool/environment failures from product defects, and reuse still-valid objective evidence without repeating whole lower-level reviews or building a checking system first; insufficient evidence stays unproved, not PASS. When SLK joins an already completed or partly completed project, the plan preserves and reuses completed work, then chooses the reasonable minimum construction route, scope, and engineering activity needed to reach the current target reliably—not merely the smallest code diff.

SLK guidance helps members decide how to continue. Rework, communication recovery, member recovery, plan adjustment, and exemption remain available as situational options.

RTK, Probe CLI, and Ponytail are optional external efficiency aids. They may be installed once in the Codex-wide environment, but installation does not authorize use in a project: the Owner chooses them per Run. SLK uses them explicitly without automatic hooks, MCP, or extra agents; native commands and raw evidence remain the fallback and authority.

Cross-Agent handoffs use the accepted `slk-transport` artifact with exact role endpoints and native Agent activation. In 4.3.4, `preflight-run` fails closed unless the exact Codex/DSH/OCRV bindings, local capacity/workspace/capabilities and Owner ON/OFF decisions for every option are complete. OCRV materializes and measures its compact background, proves each dynamic segment with native `review --preview` plus real excludes, runs segments sequentially, stops on a blocking finding, and forms one compact D1 without reinjecting full segment results. RTK and Probe CLI remain optional with native fallback; no daemon, MCP, second Checker or new role is introduced. Existing Desktop current-turn recovery, TOKEN and D0/D1/D2 authority stay unchanged. See [`docs/transport/SLK-TRANSPORT.md`](docs/transport/SLK-TRANSPORT.md).

4.3.4 continues to ship the optional `SLK.Start` and `SLK.Run` Temporal templates introduced in 4.3.0. They require explicit per-Run selection and an existing service/adapter, do not install Docker or become a hard dependency, and never decide engineering state. Direct mode remains the fallback. See [`docs/runtime/SLK-TEMPORAL.md`](docs/runtime/SLK-TEMPORAL.md).

## 4.0 state and LE BI

SLK 4.0 added one configurable machine-wide data root, a versioned SQLite authority, durable evidence, deterministic Markdown exports, and the standalone read-only **LE BI** desktop view. In 4.3.4, Supervisor, Checker, and Worker still write only their own engineering facts; an optional whole-Run Overwatcher remains non-authoritative and never becomes a scheduler. Rework requests follow the live authority boundary, and repeated Overwatcher pause/resume cycles have distinct append-only incident identities. Exact snapshots preserve engineering history and TOKEN during explicit adoption through `4.3.4`; `slk-bi-query` and LE BI remain read-only. See [`docs/state/SLK-STATE.md`](docs/state/SLK-STATE.md) and [`docs/state/SLK-BI.md`](docs/state/SLK-BI.md).

LE BI displays each explicit Run identity as one compact row, whether independent or owned by a CLK/GLK project. Explicit predecessor lineage distinguishes current, historical, duplicate-active, and orphaned identities; titles and timestamps never merge Runs. Expanding a row shows the three technical roles, CELL facts, and a separate compact Overwatcher operational strip when bound. BI does not confirm message delivery, repair communication, or modify the Run; accepted observations may conservatively show that activity is unproved without changing engineering progress.

## Skill collection

The active collection lives in [`skills/`](skills/):

- [`skills/small-loop-skill/SKILL.md`](skills/small-loop-skill/SKILL.md) — lightweight identity and situational entry;
- 14 sibling Skills for planning, resource continuity, role-based model selection, closed role Eval, team lifecycle, optional Overwatcher observation, CELL work, recording, rework, adjustment, communication recovery, and closure. Rework can call an available project-appropriate Debug Skill when root-cause diagnosis is needed.

The 14 companion Skills are not standalone methods. Each applies only inside a Run that has selected Small Loop Skill (SLK) and has been routed to that situation by the main Skill or the same collection flow.

Ordinary work reads the main Skill and the current situational Skill. Additional guidance is loaded when the situation changes. When maintaining SLK prompts, pair corrections for demonstrated misuse with direct “Do not…” reminders in an independent negative-prompt section; revise existing reminders rather than stacking duplicates. These sections clarify the same method, not another workflow or an approval/stop checklist.

## Run record

Supervisor initializes the Run and its first plan revision. Worker, Checker, and Supervisor append their own engineering facts to the configured SLK data root; an enabled Overwatcher appends only its own complete cycles and operational observations. Deterministic `SLK-RUN-<RUN-ID>.md` exports are generated from that authority, outside the product repository. The template remains at [`skills/slk-record-run/assets/SLK-RUN.template.md`](skills/slk-record-run/assets/SLK-RUN.template.md) for readable structure and compatibility.

## Install

Place the 15 directories under `skills/` as sibling directories in the Codex Skill root. The main entry and 14 focused companion Skills cover planning, resource continuity, model selection, execution, checking, optional observation, recovery, records, and closure. Invoke `$small-loop-skill`; it recommends the relevant sibling Skill as the Run changes.

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
