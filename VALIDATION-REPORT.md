# Validation Report — SLK 2.6.0 Candidate

Local validation date: 2026-08-06
Local platform: Windows, Python 3.14
Branch: `feature/slk-2.6.0-model-policy`

## Verified locally

- PASS: Small Loop Skill identity, 2.6.0 version alignment, unchanged
  Control+Worker formal topology, one non-authoritative Patrol, and existing D0-D3 /
  Owner authority;
- PASS: 123 full pytest tests;
- PASS: 86 focused runtime-control and authority-contract tests;
- PASS: 72 runtime-control CLI behavior tests under ordinary and `python -O` execution;
- PASS: 15 focused model-policy tests, including ordinary and `python -O`
  adversarial execution;
- PASS: Terra + `xhigh` default bindings for Supervisor, Checker, Verifier, Worker,
  and Patrol, with distinct binding IDs and unchanged role isolation;
- PASS: Worker Luna + `xhigh` only for an exact CELL/Round whose frozen Contract is
  fine-grained, LOW-risk, and explicitly Luna-eligible;
- PASS: Sol + `xhigh` only for high-difficulty correction, root-cause diagnosis, or
  complex rework;
- PASS: proven capability-equivalent non-reference substitutes with matching
  reference class and immutable equivalence evidence;
- PASS: known Terra/Luna/Sol actual models require exact reference/class binding in
  all six cross-class spoof directions; equivalence evidence cannot relabel them,
  and uppercase, mixed-case, or outer-whitespace GPT aliases fail closed before the
  external-equivalence path;
- PASS: every SLK role retains exactly one stable `role_instance_id` for the Run,
  the persistent Worker cannot be duplicated, and no role instance can be shared;
- PASS: GPT 5.5/lower, unauthorized `ultra`,
  cost/convenience downgrade, ordinary-work Sol, Patrol Luna/Sol, unevidenced or
  misclassified substitutes, missing revalidation, and silent/no-op switch history
  fail closed;
- PASS: model/effort switches require contiguous supersession, immutable reason /
  evidence, and new readiness/isolation/verification PASS;
- PASS: `RUN_RUNTIME_CONTRACT`, runtime-index dispatches, Patrol receipts, CELL
  Contract, D0-D3/Supervisor/amendment templates, and current trace identity are
  consistently bound without adding a router or decision layer;
- PASS: JSON Schema draft 2020-12 structure and 13 representative valid instances
  covering all thirteen runtime record types;
- PASS: all 63 required injected-clock simulation scenario IDs are present exactly
  once with PASS/evidence;
- PASS: existing wake, Supervisor-wait, full Patrol checklist, progress, capacity,
  task Pin, causal repair, candidate, and Run-index fail-closed tests remain green;
- PASS: repository validator, official Serial Plan, Manifest/hash/version/identity,
  and 40 root/install mirror byte comparisons;
- PASS: 5 JSON and 53 YAML release files parse as UTF-8;
- PASS: blank technical/runtime templates remain `PENDING`; no unfinished
  placeholder, secret pattern, cross-method ownership, topology expansion, or
  `git diff --check` error is present.

## Preserved boundaries

- `MODEL_BINDING_TRACE` is readiness and execution evidence, not a model router,
  cost optimizer, scheduler, message bus, or Runtime method.
- Same actual model never merges role authority, candidates, environments, or
  receipts.
- Patrol remains non-technical and owns no D0-D3, implementation, verification,
  acceptance, progress, Pin/Unpin, dispatch, or repair action.
- No D4, role, conversation, Worker, parallelism, universal TDD, device monitor,
  CLK/GLK topology behavior, or LCCoding product-definition logic was added.
- No Docker/system dependency installation, new Codex task, subagent, push, merge,
  tag, Release, or PR occurred.

## Remaining risk

Capability equivalence for a non-reference provider/model is evidence-governed; SLK
validates the declared class, reference, and immutable proof but does not benchmark
external model providers. Owner/Control remains responsible for admitting that
evidence at a versioned boundary.

## Remote evidence boundary

This candidate is local only. The report does not claim remote branch, CI, tag, or
Release evidence.
