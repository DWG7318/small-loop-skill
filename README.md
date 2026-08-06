# Small Loop Skill (SLK)

Small Loop Skill is the strict serial engineering method for one bounded LCCoding
Run executed through one formal Control Conversation and one persistent Worker
Conversation, with one non-authoritative Run Patrol safeguard.

Current version: **2.5.1**

```text
Owner
  ↓
Control Conversation
  ├─ Supervisor responsibility
  ├─ Checker responsibility (D1)
  └─ Verifier responsibility (D2/D3)
         ↕
one persistent Worker Conversation (D0)

one Run Patrol safeguard (no technical authority)
```

Only one Control responsibility mode is active for a formal decision. Only one CELL
may be active. Verifier responsibility uses a clean validation environment and
immutable candidate evidence; SLK does not claim blind conversation-memory
independence and does not add a third formal engineering conversation.

## Run flow

```text
Frozen LCCoding Run Contract
→ strict Serial Plan
→ GO-001 → GO-002 → … → GO-N
→ D3 Run Verification
→ Run Owner Acceptance
→ LOOP_OWNER_ACCEPTED
```

SLK consumes product meaning and acceptance from LCCoding. It does not own Calabash,
centralized project security audit, packaging, delivery, or project completion.

Use CLK for fixed parallel Chains/Stages. Use GLK for branches, joins, fallbacks,
cycles, or a free GO graph.

## Causal defect repair

After D1 rejects a candidate, Checker binds one `DEFECT_LINEAGE` to the immutable
failed candidate, failure fingerprint, reproduction evidence, and repair round.
Worker establishes stable reproduction—or evidence that it cannot be reproduced—
then tests one root-cause hypothesis with one minimal experiment before making the
smallest root-cause repair.

Before the credited experiment, SLK validates concrete IDs, request shape, authority
seeds, and the planned one-SQLite/one-Repository/no-reset topology without invoking
a business action. A bad fixture is corrected in the same checkpoint and consumes
zero causal credit; it cannot create an artificial Control-Worker loop.

For a stably reproducible, reasonably automatable defect, D0 carries candidate-bound
fail-before, pass-after, and risk-scaled regression evidence. Other cases require a
Checker-approved exemption and alternative evidence. Three Checker-rejected repair
candidates in the same lineage prohibit a fourth ordinary rework and route to
architecture review, method-boundary exit, or a versioned Contract revision.

This discipline is embedded only in D0/D1 defect repair. It adds no D4, role, visible
conversation, Chain/Stage/Barrier, or graph activation.

## Runtime safeguards

SLK 2.5.0 adds a Worker-only four-level Checker wake ladder, prohibits Supervisor
wait loops, derives layered progress from D1/D2 receipts, and uses exactly one
non-authoritative Patrol. Supervisor freezes measurable device capacity and
cumulative engineering load; only a pre-dispatch `CELL_CAPACITY_GATE` PASS permits
work. Workload maps `LOW→10`, `MEDIUM→15`, and `HIGH→30` Patrol minutes; every cycle
proves the full minimum-error checklist. The Control responsibilities and Worker
default to task Pin denied, while non-technical Patrol is denied separately. Every
material verdict has one bound Supervisor progress update, and a lightweight
`RUN_RUNTIME_INDEX` proves each dispatch has capacity, wake, progress, and Patrol
evidence without becoming a Runtime.

See [runtime control and progress](references/runtime-control-and-progress.md).

## Validation

```text
python scripts/validate_repository.py
python scripts/validate_serial_plan.py examples/minimal-run/serial-plan.yaml
python scripts/validate_defect_repair.py <d0-or-d1-receipt.yaml>
python scripts/validate_runtime_control.py <runtime-record.yaml>
python -m pytest -q
```

## Install

Install `small-loop-skill/` and invoke `$small-loop-skill`.

## License

MIT.
