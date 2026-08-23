# Changelog

## 3.0.1

- Clarified that every role ends its current activity after dispatch, delivery, or boundary work and is reactivated only by a real message.
- Removed ambiguous progress-state and bounded-wait wording that could encourage `wait_threads` monitoring and contaminate later D1 or D2 judgment.

## 3.0.0

- Reframed SLK as one lightweight router plus 12 situational sibling Skills.
- Restored three visible conversations: Supervisor, Checker, and Worker.
- Simplified verification to minimum Worker D0, isolated Checker D1, and combined-result Supervisor D2.
- Replaced Control modes, Verifier, Patrol, runtime indexes, fixed model bindings, Pin policy, capacity gates, D3, and Owner acceptance receipts in the active method.
- Added model/device/headroom-aware CELL planning, state-aware communication recovery, upper-level member recovery, and Supervisor Run adjustment.
- Added one readable root Run record with per-role entries for progress, errors, rework, exemptions, evidence, D2, and archive state.
- Kept Supervisor event-activated rather than continuously involved in the Checker/Worker CELL loop.
- Ordered D1 and D2 evidence so Worker conclusions and detailed CELL history do not lead the independent judgment.
- Routed generic root-cause diagnosis to existing Debug Skills instead of duplicating one inside SLK.
- Added a situational role-model selector: stronger professional coding models for Supervisor and Checker, with a reliable Worker model that may be one capability tier lower for a suitable CELL.
- Completed the final consistency audit: role models now precede initial CELL sizing; root-record creation and Checker readiness sit in their real startup positions; visible creation authority, Owner model choice, Worker-to-Checker recovery, and D2 readiness agree across the collection.
- Marked every companion Skill as SLK-only in both discovery metadata and its opening guidance so it is not mistaken for a standalone engineering method.
- Shifted operational language toward situational recommendations and recovery paths so ordinary deviations lead back to construction.

## 2.6.0

- Replaced fixed model assumptions with one versioned, immutable
  `MODEL_BINDING_TRACE` for the existing SLK roles and scopes.
- Made Terra + `xhigh` the default for technical roles and non-authoritative Patrol.
- Allowed Luna only for Worker execution of an explicitly fine-grained/LOW-risk
  CELL, and Sol only for high-difficulty correction, root-cause diagnosis, or
  complex rework.
- Added capability-class/equivalence evidence for non-reference substitutes and
  retained separate role bindings when roles use the same actual model.
- Rejected GPT 5.5/lower, inferred `ultra`, cost/convenience downgrade reasons,
  ordinary-work Sol, unevidenced substitutes, and silent model/effort switches.
- Bound runtime readiness, dispatch index, Patrol receipts, CELL Contracts, and
  technical receipts to current model evidence without adding a router, role,
  conversation, or D4.

## 2.5.1

- Added a machine-validated, zero-business-call causal experiment preflight for
  concrete identifier format, request shape, authority seeds, and one-SQLite/
  one-Repository/no-reset topology.
- Made invalid fixture or newly leased harness assertions zero-credit and
  correctable within the same authorized checkpoint when product meaning,
  authority, and the active hypothesis remain unchanged.
- Added the preflight receipt template and validator, and bound the policy into the
  D0 receipt template and control kernel.

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
