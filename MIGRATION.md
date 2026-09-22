# Migration from SLK 2.6.0 to 3.0.0

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

## Migration from 3.0.8 to 4.0.0

SLK 4.0 keeps the 3.0.8 three-role method and extends the collection to 14 Skills with one compact resource-continuity guard. It does not introduce another construction role, inspection layer, scheduler, watcher, acknowledgement loop, or Owner write path.

For a new 4.0 Run, configure one machine-wide SLK data root and initialize the Run through `slk-state`. Supervisor, Checker, and Worker then append only the facts at their existing boundaries. Native transport remains responsible for real Agent activation; the state row is written after accepted delivery evidence and never substitutes for it. Existing 3.0.8 Markdown records remain historical records rather than being silently imported as live state.

Other Agents and BI read through `slk-bi-query` or the same core projections. The standalone BI is optional for construction and read-only by design. Existing prompt-only Runs may finish on 3.0.8; adopting 4.0 requires an explicit new 4.0 Run identity and configured state root rather than partially mixing both state models.

## Migration from 4.1.1 to 4.2.0

Existing 4.1.1 Runs remain valid and may finish without an Overwatcher. Before a 4.2 writer or BI opens an older state root, run the normal writable `slk-state configure` migration so the verified backup and schema-v4 tables are created atomically. Do not reinterpret an old Run as having an Overwatcher or infer lineage from its title.

New 4.2 Runs keep the same Supervisor ↔ Checker ↔ Worker direct routes, TOKEN flow, CELL, D0, D1, and D2 semantics. They use the versioned closed role Eval before binding and may optionally bind one dedicated Overwatcher Agent Session. The Overwatcher has a separate observation credential, cannot write engineering facts or BI/TOKEN, cannot become a mandatory relay, and is closed and archived with its Run. Successor Runs name `predecessor_run_id` explicitly; independent Runs leave it empty.

New role registrations use the fixed Codex Supervisor, OCRV Checker, and DSH Worker identities; old prompt-only or all-Codex substitutions are not silently accepted. D1 INCOMPLETE leaves TOKEN with Checker. A formal D1 FAIL uses the closed Checker failure escalation and Supervisor rework directive for the same Worker; this exception does not create a general Supervisor→Worker route or move D1 authority.

Communication recovery now inspects the original immutable attempt first and permits at most one exact retry with the same message, endpoint, payload, and scope. A semantic change returns `SUPERVISOR_DECISION_REQUIRED`. Windows helper processes default to hidden/no-window operation. No Temporal service, daemon, broker, MCP, additional engineering role, or hard optional-tool dependency is introduced.
