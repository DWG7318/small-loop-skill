---
name: small-loop-skill
description: Use SLK for one bounded LCCoding Run whose GO outcomes form exactly one strict serial sequence executed through one visible Control Conversation and one persistent Worker Conversation. Never combine SLK with CLK or GLK in the same Run.
version: 2.4.0
---

# Small Loop Skill (SLK)

## Canonical identity

- Product name: `Small Loop Skill`.
- Abbreviation: `SLK`.
- Invocation: `$small-loop-skill`.
- Repository: `https://github.com/DWG7318/small-loop-skill`.
- Repository ID: `1295599218`.
- Default branch: `main`.
- Current specification version: `2.4.0`.
- Version source: repository `VERSION` file and matching annotated `v*` tag.

## Trigger

Activate when LCCoding selects SLK and supplies a frozen `RUN_CONTRACT` proving one
unique strict serial GO sequence.

Do not activate for incomplete product definition, fixed parallel Chains/Stages, a
free GO graph, branches, joins, fallbacks, cycles, or multiple active Workers.

## Fixed visible topology

Use exactly two visible Codex conversations:

```text
Owner
  ↓
Control Conversation
  ├─ SUPERVISOR_RESPONSIBILITY
  ├─ CHECKER_RESPONSIBILITY
  └─ VERIFIER_RESPONSIBILITY
         ↕
one persistent Worker Conversation
```

Every formal Control decision starts with exactly one `RESPONSIBILITY_MODE` value.
Modes are non-interchangeable. Never create a third Verification Conversation,
second Worker, hidden agent, subagent, or background formal role.

Verifier independence means frozen authority, an immutable candidate, clean
GO/Run-boundary environments, and separately signed D2/D3 receipts. It does not mean
blind conversation-memory isolation.

## Required flow

```text
RUN_CONTRACT
→ SERIAL_BASELINE
→ one Current GO / at most one Active GO
→ CELL: Worker D0 → Checker D1
→ GO: Verifier D2
→ all current Required GOs D2 PASS
→ Verifier D3
→ Run Owner Acceptance
→ LOOP_OWNER_ACCEPTED
```

## Hard rules

1. SLK is the only loop method in the Run.
2. Keep exactly one Control and one persistent Worker conversation.
3. Activate one Control responsibility mode for each formal decision.
4. Execute one CELL at a time; Worker never self-selects the next CELL.
5. Supervisor owns planning, pointers, provisioning, amendments, routing, and Owner
   contact; it signs no D1-D3 verdict.
6. Worker alone owns product implementation and D0 evidence.
7. Checker alone owns D1 CELL acceptance and CELL rework routing.
8. Verifier alone owns D2 GO and D3 Run verification.
9. D1 defect failure binds one immutable Candidate, failure fingerprint,
   reproduction evidence, `DEFECT_LINEAGE`, and repair round.
10. Worker establishes reproduction or evidenced non-reproduction, then tests one
    active root-cause hypothesis with one minimal experiment before product change.
11. A stably reproducible and reasonably automatable defect requires candidate-bound
    fail-before, pass-after, and risk-scaled regression evidence; an exemption
    requires Checker approval and alternative evidence.
12. Three Checker-rejected immutable repair Candidates in one lineage forbid a
    fourth ordinary rework and require architecture review, method-boundary exit, or
    a versioned Contract revision, bound to a traceable `route_ref`.
13. Failed hypotheses do not count as rejected repair Candidates, and regression
    first is not a universal TDD mandate.
14. Worker, Checker, and Verifier never accept product edits they authored in the
   same candidate.
15. Every validation binds the exact immutable candidate and clean environment.
16. Every blank receipt is `PENDING`; absence and silence never pass.
17. Release no successor until every current Required predecessor has D2 PASS.
18. Every current Required GO must have D2 PASS before D3.
19. Formal resolution never replaces D2 for a GO that remains Required.
20. A resolution changes the Required set only through a versioned Baseline
    Amendment.
21. Material candidate change invalidates affected and dependent receipts.
22. Product-visible change invalidates prior Owner Acceptance.
23. Known Critical/High security risk blocks D3 and Owner Acceptance.
24. SLK consumes product meaning from LCCoding and never invents it.
25. SLK never claims centralized vulnerability closure, delivery readiness, or
    project completion.

## Responsibility modes

### Supervisor

Validate Run Contract completeness and SLK suitability; freeze the Serial Baseline;
maintain `current_go_id` and `active_go_id`; provision Worker, Checker, and Verifier
environments; route receipts and rework; issue Baseline Amendments; escalate only
Owner-exclusive decisions; prepare bounded Owner Acceptance; record the verdict.

### Worker

Implement only the authorized CELL in the bound mutable workspace. Return candidate
identity, changes, D0 checks, evidence, and risks. Never accept work, revise the
plan, contact Owner, or start another CELL.

### Checker

Validate the immutable CELL candidate against the frozen CELL Contract in a clean
environment. Sign D1 or return bounded CELL rework. Worker evidence is input, not
Checker evidence.

For a defect failure, bind `DEFECT_LINEAGE`, failed Candidate, fingerprint,
reproduction evidence, repair round, and rejection count. On repaired D1, rerun
independent reproduction and approve either required regression evidence or a
reasoned exemption. The third rejected repair Candidate routes
`ARCHITECTURE_REVIEW_REQUIRED`, `METHOD_BOUNDARY_EXCEEDED`, or
`CONTRACT_REVISION_REQUIRED` with `route_ref` and cannot return ordinary
`CELL_REWORK`.

### Verifier

At a GO boundary, consume valid D0/D1 receipts and add only GO composition,
integration, scope, side-effect, and GO-risk checks for D2. At the Run boundary,
consume valid D2 receipts and add only cross-GO seams, end-to-end route, final
candidate identity, regression delta, and uncovered Run risk for D3.

## Causal defect repair packet

For repair D0, require:

- `defect_lineage_id`, `repair_round`, source D1 failure, and its
  `failed_candidate_ref`;
- `REPRODUCED` or evidence-backed `NOT_REPRODUCIBLE`;
- one scalar hypothesis and one minimal experiment;
- `CONFIRMED` root cause before `product_change_made: true`;
- smallest `change_scope`;
- regression `REQUIRED` with fail-before/pass-after/regression evidence, or
  `EXEMPT` with reason and alternative evidence.

D1 FAIL requires `defect_repair.failed_candidate_ref == candidate_ref`. The original
failure alone uses round zero; every `REPAIR` Candidate uses round one or greater.
For required regression, D0 fail-before Candidate equals `failed_candidate_ref` and
pass-after Candidate equals the D0 Receipt Envelope `candidate_ref`.

Validate D0/D1 repair packets with:

```text
python scripts/validate_defect_repair.py <d0-or-d1-receipt.yaml>
```

This packet changes neither the D0-D3 layers nor the fixed visible topology.

## Current and Active control

Current and Active are singular Run-level pointers, separate from GO lifecycle
state. `active_go_id`, when present, equals `current_go_id`. The active GO must be
`IMPLEMENTING`. A successor cannot become Current until every current Required
predecessor is `VERIFIED` by a valid D2 PASS receipt.

Validate plans with:

```text
python scripts/validate_serial_plan.py <serial-plan.yaml>
```

## Receipt envelope

Every D0-D3, Owner, amendment, and Run receipt records:

- receipt ID/type and `PENDING` until explicit signature;
- frozen contract and baseline references with versions/hashes;
- candidate identity and provenance;
- responsibility and execution-context reference;
- issued time, commands/results, and evidence references/hashes;
- consumed receipt IDs/hashes;
- invalidation and supersession state.

Higher layers consume lower receipts without overwriting them. Repeat a check only
for material candidate/environment change, expired/contradictory evidence,
composition effect, expanded regression, or a specific new risk.

## Formal resolution

Allowed results are `CANCELLED_BY_AUTHORITY`, `REMOVED_FROM_SCOPE`, and
`SUPERSEDED`. Each requires a `BASELINE_AMENDMENT` that removes or replaces the GO
in the Required set and invalidates affected receipts. It is forbidden to treat a
still-Required GO as complete without D2 PASS.

## LCCoding and security boundary

LCCoding owns Calabash, product definition, centralized security audit, packaging,
delivery, and project completion. SLK consumes the frozen Run Contract and performs
its Run-local safety checks.

Known Critical/High vulnerability, authentication/authorization bypass, privilege
escalation, credential or cross-tenant leakage, destructive risk, or failed Run
security claim blocks D3 and Owner Acceptance. Security remediation invalidates all
affected receipts and product-visible change also invalidates Owner Acceptance.

## Owner Acceptance and output

After D3 PASS, give Owner a short guide containing Run Feature, exact candidate,
entry/account/role, inspection steps, visible outcomes, limitations, and D3-covered
invisible risks.

Only explicit Owner verdict `LOOP_OWNER_ACCEPTED` completes SLK. Other routes are
`LOOP_PRODUCT_REWORK`, `PRODUCT_DEFINITION_CHANGE`, and `NEW_FEATURE_REQUEST`.

The output is `SLK_RUN_RECEIPT` plus `LOOP_OWNER_ACCEPTED`, never delivery or
project-level completion.

## Publication gate

Before publishing, verify repository owner/name and ID, default branch, clean tested
installation, matching root/install-tree assets, `VERSION`, Manifest, remote main
HEAD, and annotated release tag. Never publish SLK content to CLK or GLK.

See [SPEC.md](SPEC.md), [serial plan construction](references/serial-plan-construction.md),
[role isolation](references/role-and-environment-isolation.md), [verification
de-duplication](references/verification-de-duplication.md), [amendment and
rework](references/amendment-and-rework.md), [causal defect
repair](references/causal-defect-repair.md), [security boundary](references/security-boundary.md),
and [Owner Acceptance](references/owner-acceptance.md).
