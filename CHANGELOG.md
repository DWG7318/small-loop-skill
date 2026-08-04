# Changelog

## 2.5.0

- Added the Worker-only four-level wake ladder for the frozen Checker, scoped
  GO/CELL n/N delivery messages, matching `WAKE_ACK`, deterministic temporary
  heartbeat, and Patrol-readable `PENDING_WAKE` fallback.
- Prohibited positive-timeout/looped Supervisor waits and added exactly one visible
  non-authoritative Run Patrol conversation/heartbeat using
  `gpt-5.6-luna` + `xhigh`.
- Bound all positive Supervisor waits (including one-shot/outside-loop), loops, and
  wait-all to fixed Patrol alerts; only timeout-zero snapshots are normal.
- Bound frozen workload `LOW/MEDIUM/HIGH` to 10/15/30-minute Patrol intervals and
  required the complete unique minimum-error checklist in every patrol cycle.
- Defined visible peer tasks and planning “subtasks” separately from prohibited
  spawned, delegated, hidden, or background agents.
- Added receipt-derived layered progress: Worker delivery position, Checker D1
  acceptance, and Supervisor D2 GO/Run milestones with versioned denominators.
- Bound every D2/D3/Owner material verdict to exactly one later Supervisor progress
  event using event/receipt/verdict identity; GO candidate readiness is unique per
  Required-set version and binds the final D1 acceptance event.
- Added versioned device capacity and cumulative engineering load, total-cost
  `CELL_CAPACITY_GATE`, dynamic feedback, `CELL_SCOPE_EXCEEDED`, post-dispatch split
  defects, and severe 3+ successor re-evaluation.
- Added default-deny task Pin capability for the SLK Control responsibilities and
  Worker, with non-technical Patrol denied separately; Owner-only provenance and
  immutable Pin-then-Unpin history remain enforced.
- Added lightweight `RUN_RUNTIME_INDEX` completeness validation for dispatch-bound
  RUN/GO/CELL/ROUND capacity PASS, wake, progress, and current complete Patrol
  evidence.
- Added one closed runtime schema, explicit optimized-safe validator, fail-closed
  templates, simulation gate, tests, mirrors, and migration/reference material.
- Preserved Control + persistent Worker as the formal engineering topology and
  D0-D3/Owner authority. Patrol is a safeguard, not a third technical role.

## 2.4.0

- Added candidate-bound `DEFECT_LINEAGE` and repair-round records to D1 failures
  and D0 repair candidates.
- Required evidence-backed reproduction or documented non-reproduction, one active
  root-cause hypothesis, one minimal experiment, and root cause before product
  change.
- Added defect-only, risk-proportional regression-first evidence: fail-before,
  pass-after, and regression coverage, or a Checker-approved exemption with
  alternative evidence.
- Added a hard gate after three Checker-rejected immutable repair candidates:
  ordinary rework stops and Control routes architecture review, method-boundary
  exit, or a versioned Contract revision.
- Kept the existing two-conversation topology and D0-D3 authority; no D4, role,
  general TDD mandate, Chain/Stage/Barrier, or graph activation was added.

## 2.3.1

- Preserved the canonical `Small Loop Skill` identity and exactly two visible
  conversations: one Control and one persistent Worker.
- Added non-interchangeable Supervisor, Checker, and Verifier responsibility modes
  inside the Control Conversation; Checker owns D1 and Verifier owns D2/D3.
- Made every D0-D3 and Owner receipt template fail closed with canonical `PENDING`.
- Replaced assertion-only plan checks with strict serial-plan validation and stable
  error codes that remain active under `python -O`.
- Required D2 PASS for every current Required GO; formal resolution now changes the
  Required set only through a versioned Baseline Amendment.
- Added minimum auditable Receipt Envelopes, Current/Active pointers, candidate
  invalidation, known-risk security hard brakes, Manifest verification, Windows CI,
  and a complete MIT License.
- Kept Calabash and centralized project security audit under LCCoding ownership.

## 2.3.0 (withdrawn draft)

- This draft was never approved for installation or release because it contained
  success-by-default receipts, weak validation, an undefined D2 bypass, incomplete
  release integrity, and an unresolved identity/topology change.

## 1.9.1

- Replaced brittle exact free-text readiness grading with deterministic public
  multiple-choice packets and stable `choice_id` submissions.
- Preserved the 25/25 threshold, hidden answer-key boundary, seeded question order,
  and fail-closed receipt behavior.

## 1.9.0

- Added mandatory Full/Minimum Calabash for product-affecting runs and a narrow
  technical exemption.
- Defined Supervisor and Checker as non-interchangeable responsibilities inside one
  Control Conversation.
- Required independent Checker worktree/sandbox and runtime-state isolation.
- Restored Worker ownership of product rework; deprecated ambiguous `REDO`.
- Added `PROJECT_AUTONOMY_ENVELOPE` and prohibited routine Owner confirmation.
- Added `GO_CALABASH_TRACE`, `GO_EVIDENCE_CONTRACT`, GO-boundary acceptance, and
  cross-GO CELL dependency prohibition.
- Added tiered detection and clarified final composition audit.
- Updated method boundaries to Chain Loop Skill (CLK) and Graph Loop Skill (GLK).
