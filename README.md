# Small Loop Skill (SLK)

A Codex skill for running one bounded project Block through one supervised
`Checker <-> Worker` loop.

The official abbreviation is **SLK**. Use `SLK` in conversation and
documentation; use `$small-loop-skill` as the Codex invocation name.

```text
Owner -> Supervisor -> Checker <-> Worker
```

The Block contains multiple GO phases. Each GO contains sequential CELLs. The
Checker sends one CELL at a time, validates delivery, routes rework or the next
CELL, and writes the final result queue. The Supervisor keeps a same-thread
heartbeat, resolves real plan defects, and performs final acceptance.

Use MSLK instead when the project has multiple materially independent Blocks
that should run through multiple Checker/Worker pairs in parallel.

Install the `small-loop-skill` folder under your Codex skills directory, then
invoke `$small-loop-skill` for one supervised sequential loop.

Current version: `1.2.0`.

Version `1.2.0` separates SLK from MSLK and establishes the single-Block,
single-Checker, single-Worker contract.
