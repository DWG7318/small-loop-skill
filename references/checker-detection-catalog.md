# SLK Checker Detection Catalog

This reference belongs only to SLK. It does not authorize MSLK topology,
subagents, hidden roles, or a separate Checker. Read it before defining any
`GO_DETECTION_PROFILE`.

## Mature Detection Skills

Provision mature detection skills through the combined role's Supervisor
responsibility. The baseline catalog is
`superpowers:verification-before-completion`,
`superpowers:systematic-debugging`, `superpowers:test-driven-development`,
`security-best-practices`, and `playwright`, plus trusted official or established
language/framework inspection skills selected for the actual stack.

Record each skill source, version, and compatibility with the current Codex
environment. Confirm it is installed and readable. Any skill that requires
subagents is incompatible with SLK and must not be loaded. A skill guides Checker
responsibility but never becomes a hidden Checker or transfers acceptance.

## Mature Detection Tools

CodeGraph is mandatory for code or repository work when relevant source can be
indexed. Establish the structural and dependency baseline, ownership boundaries,
entry points, call/dependency paths, and affected closure before the first CELL.
Refresh the changed graph slice after each CELL and the broader baseline at GO
and final acceptance. CodeGraph complements source, test, and runtime evidence.

Build a task-fit layered detection stack from mature tools:

- native compiler, type checker, formatter, linter, and test runner;
- CodeGraph, diff, and ownership-boundary inspection;
- Semgrep or CodeQL with pinned project rules;
- Gitleaks with reviewed allowlists;
- OSV-Scanner or Trivy, with SBOM/container checks when relevant;
- focused/regression tests plus coverage and mutation testing;
- Playwright or an equivalent real runtime harness;
- Spectral, Schemathesis, or another API or schema contract validator.

Record tool version, configuration, and omission rationale in the GO plan. An
unselected catalog layer needs a risk-based plan rationale; convenience, speed,
or Worker confidence is not a rationale.

## Precision And Learning

Checker responsibility maintains an acceptance matrix mapping every criterion
to an independent action, expected result, and evidence path. Maintain a
false-positive register with reviewed suppressions and expiry/revisit conditions;
never silence a finding only to make a scan green.

Record focused, graph-impact, regression, security, and runtime results as
`REGRESSION_EVIDENCE` linked to the CELL, GO profile, and manifest versions.
Checker responsibility must not accept a CELL from Worker self-report alone.
Tool output is evidence, not the acceptance decision: reconcile conflicts and
preserve redacted raw summaries or stable references.

After every accepted CELL and GO, calibrate from escaped defects, noisy rules,
new dependencies, and changed risk. Detection evidence may update the next CELL,
GO revision, or supplementary GO only through the versioned planning rules.

If a required skill, tool, permission, or safe execution capacity is unavailable,
record `CONDITION_BLOCKED`. Supervisor responsibility must provision or safely
resolve it, or request specific Owner assistance. Never silently substitute a
weaker capability or accept an incomplete detection system.
