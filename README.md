# Small Loop Skill (SLK)

A Codex skill for running one bounded project through one supervised
`Checker <-> Worker` loop.

The official abbreviation is **SLK**. Use `SLK` in conversation and
documentation; use `$small-loop-skill` as the Codex invocation name.

```text
Owner -> Supervisor -> Checker <-> Worker
```

The Worker owns multiple GO phases. Each GO contains sequential CELLs. The
Checker sends one CELL at a time, validates delivery, routes rework or the next
CELL, and writes the final result queue. The Supervisor keeps a same-thread
heartbeat, resolves real plan defects, and performs final acceptance.

Use MSLK instead when the project needs multiple materially independent Workers
and Checker/Worker pairs in parallel.

Install the `small-loop-skill` folder under your Codex skills directory, then
invoke `$small-loop-skill` for one supervised sequential loop.

Current version: `1.2.2`.

Version `1.2.2` defines its single Worker as independently inspectable and
acceptable. SLK has one Worker, one Checker, and one sequential GO/CELL chain.
