# Small Loop Skill (SLK)

Small Loop Skill is the strict serial engineering method for one bounded LCCoding
Run executed through one visible Control Conversation and one persistent Worker
Conversation.

Current version: **2.3.1**

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

## Validation

```text
python scripts/validate_repository.py
python scripts/validate_serial_plan.py examples/minimal-run/serial-plan.yaml
python -m pytest -q
```

## Install

Install `small-loop-skill/` and invoke `$small-loop-skill`.

## License

MIT.
