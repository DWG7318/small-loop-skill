# Migration from SLK 2.6.0 to 3.0.0

This section records the original 3.0.0 boundary. The 3.0.9 changes at the end supersede its event-activated Supervisor behavior; historical Runs are not rewritten.

SLK 3.0.0 is a new method boundary. Existing Runs can remain on their bound 2.6.0 method. A new Run can choose 3.0.0 and create a fresh root Run record.

## Topology

```text
2.6.0: Control responsibilities ↔ Worker + Patrol
3.0.0: Supervisor ↔ Checker ↔ Worker
```

- Supervisor, Checker, and Worker use separate visible project conversations.
- Checker owns CELL-level D1.
- Supervisor owns Run-level D2.
- Supervisor is event-activated for setup, escalated help, recovery, exemptions, and D2; Checker and Worker own the daily CELL loop.
- Worker keeps a minimum D0 before delivery.
- The previous GO-level verification layer leaves the current method; the previous Run-level D3 becomes D2.
- Patrol, Pin governance, runtime index, fixed model binding, capacity gate, and Owner acceptance receipts leave the active Skill surface.

## Guidance model

The 2.6.0 monolith becomes one small router plus 12 sibling situational Skills. Role-based model choice becomes a small on-demand Skill used during Run planning or capability adjustment; it describes capability tiers rather than fixed vendor models. Generic root-cause diagnosis is routed to an available project-appropriate Debug Skill rather than duplicated inside SLK.

## Records

Create `SLK-RUN-<RUN-ID>.md` in the project root from the 3.0 template. Each role writes its own work, including failures, rework, exemptions and handoffs. Existing 2.6 receipts can remain with the old Run rather than being reinterpreted as 3.0 records.

## Recovery

The `v2.6.0` tag and Release preserve the previous repository and install tree. Choosing 3.0.0 installs the Skill collection as sibling directories and leaves the historical release available.

## 3.0.5 planning clarification

Runs adopting 3.0.5 keep D0, D1, and D2 as inspection layers rather than adding inspection-only CELLs. For midstream adoption into completed or partly completed work, re-plan only the still-needed construction: preserve and reuse completed results, and size the route, scope, and engineering activities needed to reach the current target reliably. Findings enter the CELL plan only when they require implementation work.

## 3.0.8 → 3.0.9 independent maintenance

Base: `v3.0.8`, commit `870b0e517c7a1cd9b2592e9e4a9115b54a312160`. This is not a 4.x downgrade or a merge from 4.x. Main/global 4.x deployments remain separate.

Supervisor now stays active with low-token native observation and owns onsite recovery/recording; Worker and Checker retain their existing handoff and acceptance responsibilities. Interrupted work resumes the original node, model requests are distinguished from effective new turns, and the existing root Markdown gets one current summary with separate historical evidence. No new role, runtime or fixed timing gate is added.

Adopt at a Run boundary in the authorized project only: verify the new Skill payload before replacing that project's old callable 3.0.8 entries. Preserve closed Run provenance, candidates and evidence, plus unrelated project/global Skills. Do not silently rebind a still-active Run.

## 3.0.9 → 3.1.0

Base: `fc03fc422b61ff7d266835cfb39799ffd68f3062`. Replace only the authorized project's 3.x Skills after its active Run ends; never merge 4.x runtime or replace global 4.x. D1 escalation, role boundaries and final-action handoffs stay unchanged. D2 findings no longer force model changes by count; recovery accounts for external jobs left behind by an ended turn. Carry forward the Owner-approved Supervisor recommendation (6.1-sol/high minimum recommended).

BI 1.1.4 is an independent compiled companion. Register the existing Markdown through its creator Supervisor, without migrating engineering state. The source remains authoritative. Missing metadata is unknown; no invented OW, timings or message types. See `skills/slk-record-run/references/bi.md`. The new BI reference makes 16 Skill payload files; retain all 13 Skills.
