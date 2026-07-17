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

Install the `small-loop-skill` folder under your Codex skills directory, then
invoke `$small-loop-skill` for one supervised sequential loop.

Current version: `1.2.6`.

Version `1.2.6` requires lifecycle-managed visible same-project conversations,
makes SLK and MSLK strictly exclusive and non-repeatable, and adds the
mandatory pre-work simulation gate.
