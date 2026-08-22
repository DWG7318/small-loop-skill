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

The 2.6.0 monolith becomes one small router plus 12 sibling situational Skills. Model and computer choices move into Run/CELL planning and event-triggered Supervisor adjustment. The guidance emphasizes recovery, rework, plan adjustment and upper-level help when ordinary work deviates.

## Records

Create `SLK-RUN-<RUN-ID>.md` in the project root from the 3.0 template. Each role writes its own work, including failures, rework, exemptions and handoffs. Existing 2.6 receipts can remain with the old Run rather than being reinterpreted as 3.0 records.

## Recovery

The `v2.6.0` tag and Release preserve the previous repository and install tree. Choosing 3.0.0 installs the Skill collection as sibling directories and leaves the historical release available.
