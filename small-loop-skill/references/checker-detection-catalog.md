# SLK Checker Detection Catalog

`DETECTION_CAPABILITY_MANIFEST` inventories what Checker can truly execute.
`GO_DETECTION_PROFILE` allocates required capabilities and assigns each to one tier.

## CELL_ALWAYS

Fast, high-signal checks for every candidate:

- formatter/linter/type checks for affected code;
- focused unit or contract checks;
- changed-content secret scan;
- artifact identity and write-scope checks;
- method-log and Markdown line-budget checks.

## CELL_TRIGGERED

Checks with frozen machine-checkable predicates:

- CodeGraph impact when source topology changes;
- Semgrep/CodeQL when relevant languages/paths change;
- dependency/container scan when manifests or lockfiles change;
- browser/E2E checks when user flows change;
- migration checks when schemas change;
- permission/safety checks when governed surfaces change.

A false predicate produces `NOT_TRIGGERED` with evidence. Plain “not applicable” is
invalid.

## GO_BOUNDARY

Checker executes the complete Calabash-traced GO outcome checks in a fresh isolated
environment:

- end-to-end user/business flow;
- GO-wide contract/state-transition/regression checks;
- required screenshot, event, audit, or reproducibility evidence;
- frozen-output compatibility;
- allocated performance, reliability, mutation, or safety checks.

## PROJECT_FINAL

Supervisor consumes Checker-produced project-final technical receipts during final
composition audit:

- integrated end-to-end path;
- cross-GO frozen-output compatibility;
- full security/dependency/build/release checks;
- project-wide performance or recovery exercise.

These do not replace GO acceptance.

## Receipt

```text
capability_id
tier
version
configuration_hash
trigger_predicate
trigger_result
command_or_action
candidate_identity
environment_id
result
evidence_reference
```

Valid results: `RUN_PASS`, `RUN_FAIL`, `NOT_TRIGGERED`, `BLOCKED`.
Worker checks never replace Checker checks.
