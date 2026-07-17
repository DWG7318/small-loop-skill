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
repairs every Worker-result defect itself, sends the next CELL, keeps the
same-thread heartbeat, resolves plan defects, writes the final result queue,
and performs final acceptance. Repair tasks are never returned to the Worker.

SLK and MSLK are mutually exclusive. Select SLK exactly once for a project run;
never load both skills, switch methods, repeat the invocation, or borrow MSLK
capabilities. If SLK is not suitable, stop and return the method decision to the
Owner instead of converting the active run.

All roles must be visible Codex conversations under the same project. SLK never
uses subagents, background agents, hidden workers, or `delegate_task`.
Create or unarchive a role conversation only when formal work is ready; archive
it immediately when that work finishes. Later same-project work should
unarchive the existing conversation instead of creating a duplicate.

Before formal role launch or CELL execution, run a no-side-effect simulation of
the first assignment, delivery, validation, and routing cycle. Formal work is
allowed only after the simulation records `SIMULATION_PASS`.

After each GO, the Supervisor responsibility within the combined
Supervisor/Checker reviews the actual accepted result. The Supervisor may
propose adjustments to unstarted GO or an append-only supplementary GO for
historical work. Preserve all historical evidence and identifiers, and require
`GO_REVISION_SIMULATION_PASS` before executing the revised plan.

The combined Supervisor/Checker uses `gpt-5.6-sol xhigh`. Workers range from
`gpt-5.5 high` to `gpt-5.6-sol high`, selected by task type. GO scope follows
project need and ignores device limits; CELLs are made smaller as needed for
reliable execution on the current computer.

Install the `small-loop-skill` folder under your Codex skills directory, then
invoke `$small-loop-skill` for one supervised sequential loop.

Current version: `1.3.0`.

Version `1.3.0` makes Supervisor repair ownership mandatory, updates model
tiers, and makes CELL sizing device-aware without constraining GO scope.
