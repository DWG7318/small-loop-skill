# Small Loop Skill (SLK)

A Codex skill for one bounded project executed by one persistent Worker under one
visible Control Conversation with distinct Supervisor and Checker responsibilities.

Current version: **1.9.0**

## Topology

```text
Owner
  ↓
Control Conversation
  ├─ Supervisor responsibility
  └─ Checker responsibility
         ↕
      one Worker
```

Supervisor and Checker share a conversation but are not one interchangeable role.
Checker validates immutable candidates in a separate clean environment.

## Definition first

Product-affecting work requires Full Calabash or Minimum Calabash:

```text
Grandpa → Product Architecture → Ontology
```

A narrow non-product technical task may use a documented `CALABASH_EXEMPTION`.
Every product-facing GO has a `GO_CALABASH_TRACE` and `GO_EVIDENCE_CONTRACT`.

## Core 1.9.0 changes

- conditionally mandatory Calabash Gate;
- explicit Supervisor/Checker responsibility modes in one Control Conversation;
- isolated Checker validation environment;
- Worker-owned product implementation and rework;
- routine Owner confirmation forbidden inside the autonomy envelope;
- Calabash-traced GO evidence acceptance;
- no cross-GO CELL dependency;
- tiered detection;
- clear boundaries to CLK and GLK.

## Method boundary

Use CLK for fixed parallel Chains advancing through synchronized Levels. Use GLK
for a free GO graph with Grapher, conditions, joins, fallbacks, or cycles.

## Install

Install `small-loop-skill/` and invoke:

```text
$small-loop-skill
```

## License

MIT.
