# Small Loop Skill (SLK)

Small Loop Skill is the strict serial engineering method for one bounded LCCoding
Run executed through one visible Control Conversation and one persistent Worker
Conversation.

Current version: **2.5.0**

```text
Owner
  ↓
Control Conversation
  ├─ Supervisor responsibility
  ├─ Checker responsibility (D1)
  └─ Verifier responsibility (D2/D3)
         ↕
one persistent Worker Conversation (D0)
```

Only one Control responsibility mode is active for a formal decision. Only one CELL
may be active. Verifier responsibility uses a clean validation environment and
immutable candidate evidence; SLK does not claim blind conversation-memory
independence and does not add a third visible conversation.

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

For a stably reproducible, reasonably automatable defect, D0 carries candidate-bound
fail-before, pass-after, and risk-scaled regression evidence. Other cases require a
Checker-approved exemption and alternative evidence. Three Checker-rejected repair
candidates in the same lineage prohibit a fourth ordinary rework and route to
architecture review, method-boundary exit, or a versioned Contract revision.

This discipline is embedded only in D0/D1 defect repair. It adds no D4, role, visible
conversation, Chain/Stage/Barrier, or graph activation.

## Worker signal continuity

Every formal CELL dispatch has one durable identity and one bound stream:

```text
ACK → PROGRESS* → BLOCKED | FINAL
```

Terminal signals wake Control. An unread terminal is explicitly
`BLOCKED_UNREAD` or `COMPLETED_UNREAD`, never generic silence and never permission
to create another Worker. Control ingests it exactly once and synchronizes route,
Run status, visible progress, and Owner-visible status atomically. Redispatch
requires proven non-delivery and always targets the same persistent Worker.

## Validation

```text
python scripts/validate_repository.py
python scripts/validate_serial_plan.py examples/minimal-run/serial-plan.yaml
python scripts/validate_defect_repair.py <d0-or-d1-receipt.yaml>
python scripts/validate_worker_signal_stream.py <stream.yaml|json>
python -m pytest -q
```

## Install

Install `small-loop-skill/` and invoke `$small-loop-skill`.

## License

MIT.
