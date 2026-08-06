# Validation Report — SLK 2.5.1

Local validation date: 2026-08-06
Local platform: Windows, Python 3.13
Base revision: `origin/main` at SLK 2.5.0, with the 2.5.1 causal-experiment-preflight update

## Verified locally

- PASS: repository structure, Small Loop Skill identity, 2.5.0 version alignment,
  Control+Worker formal topology, one Patrol safeguard, root/install mirrors, file
  set, and SHA-256 Manifest;
- PASS: official minimal Serial Plan and referenced frozen GO Contract hashes;
- PASS: 110 full pytest tests;
- PASS: causal-experiment preflight validates identifier format, request shape,
  authority seed existence and uniqueness, and one-SQLite/one-repository/no-reset
  topology before a credited experiment can begin;
- PASS: an invalid preflight creates zero business calls and writes, consumes no
  causal-experiment credit, and can be corrected inside the same checkpoint only
  when the correction is fixture- or new-harness-only;
- PASS: 71 focused runtime-control and authority-contract tests;
- PASS: 57 runtime-control CLI behavior tests;
- PASS: 10 targeted acceptance-REDO tests, each covering its ordinary path and at
  least one explicit `python -O` fail-closed path. They prove SLK-only technical
  roles plus separate Patrol Pin denial, any positive/looped/wait-all Supervisor
  wait detection, exact and unique progress triggers, complete Patrol checklists,
  Run-index completeness and Round binding, and workload/interval binding;
- PASS: JSON Schema draft 2020-12 structure check and 12 representative valid
  instances covering all twelve runtime record types;
- PASS: all 50 required injected-clock simulation scenario IDs are present exactly
  once with PASS/evidence in a valid simulation record;
- PASS: Worker levels 1-4, archive/host repair, no guessed/replacement Checker,
  deterministic temporary heartbeat, `PENDING_WAKE`, matching ACK/mechanical-start
  stop, and 120-second ceilings without real sleeps;
- PASS: every Patrol cycle contains exactly one of all seven minimum-error checks;
  fixed finding/result/alert mappings reject missing, duplicate, free-text, and
  missed-alert records while legal pause/block/external-wait remains normal;
- PASS: Supervisor timeout-zero snapshots remain allowed, while any positive wait,
  a looped wait, or wait-all is rejected regardless of `inside_loop`;
- PASS: layered Worker/Checker/Supervisor progress, ACK-before-checking, unique
  receipt-derived D1/D2 numerators, exact final-D1 GO-candidate trigger, one GO
  candidate per Required-set version, exactly one ordered progress event per
  Required-set amendment, and exactly one later Supervisor progress event for each
  D2/D3/Owner verdict;
- PASS: measurable device profile, cumulative load, total-cost capacity gate, early
  PASS versus later split, low-resource block, logical/device concurrency
  separation, execution scope exit, and severe 3/6/7/8-successor handling;
- PASS: lightweight `RUN_RUNTIME_INDEX` completeness over every formal
  RUN/GO/CELL/ROUND dispatch, current capacity PASS, wake outcome, Worker delivery,
  and one complete current Patrol cycle; omissions, unindexed extras, duplicates,
  stale versions, and wrong scopes fail closed;
- PASS: SLK technical Pin-role enumeration is exactly the three Control
  responsibilities plus Worker. Patrol Pin/Unpin denial is validated separately;
  extra roles are rejected and no cross-method role remains in SLK assets;
- PASS: proven Owner manual/exact Pin authorization, fixed unauthorized/unknown
  alerts, no automatic Patrol Unpin, and retained violation after Unpin;
- PASS: workload class is frozen and mechanically maps `LOW→10`, `MEDIUM→15`, and
  `HIGH→30` Patrol minutes;
- PASS: 5 JSON and 51 YAML release files parse as UTF-8;
- PASS: blank technical/runtime templates are `PENDING` and never imply success;
- PASS: no unfinished placeholder markers in release assets, no detected private
  key/token pattern, method-boundary wording is negative-only, and
  `git diff --check` is clean.

## Preserved boundaries

- D0-D3, immutable Candidate binding, causal defect repair, security hard brakes,
  and Owner Acceptance remain unchanged. The causal-experiment preflight is a
  zero-credit gate before D0 causal evidence, not a new D-stage.
- Run Patrol is not a technical role and owns no planning, product, verification,
  acceptance, progress, Pin, or Unpin action.
- The Run index is method-completeness evidence, not a session Runtime, scheduler,
  message bus, or additional authority.
- No D4, universal TDD, general device monitor, CLK Chain/Stage/Barrier ownership,
  or GLK graph activation was added.
- No Docker/system dependency installation, new Codex task, or subagent occurred.

## Remote evidence boundary

GitHub Actions is configured to run repository and Serial Plan validation on
`ubuntu-latest` and `windows-latest`. This local report does not claim remote CI
results; any push, merge, tag, or Release is reported separately after it occurs.
