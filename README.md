# Small Loop Skill (SLK)

A Codex skill for running one bounded project through one
`Supervisor/Checker <-> Worker` loop.

The official abbreviation is **SLK**. Use `SLK` in conversation and
documentation; use `$small-loop-skill` as the Codex invocation name.

```text
Owner -> Supervisor/Checker <-> Worker
```

The Worker owns multiple GO phases. Each GO contains sequential CELLs. The
combined Supervisor/Checker sends one CELL at a time, validates delivery,
routes rework or the next CELL, keeps the same-thread heartbeat, resolves plan
defects, writes the final result queue, and performs final acceptance.

Use MSLK instead when the project needs multiple materially independent Workers
and Checker/Worker pairs in parallel.

Install the `small-loop-skill` folder under your Codex skills directory, then
invoke `$small-loop-skill` for one supervised sequential loop.

Current version: `1.2.5`.

Version `1.2.5` adds CELL-level Worker model planning: use only 5.6 Terra or
Sol at `medium` or higher, while the combined Supervisor/Checker is recommended
to use 5.6 Sol at `xhigh`.
