# Small Loop Skill Standard Specification 2.4.0

## 1. Identity

Small Loop Skill (SLK) governs one bounded engineering Run represented honestly as
one strict ordered sequence of independently verifiable GO outcomes.

SLK owns Serial Plan construction and execution, Current/Active GO control, CELL
routing, D0-D3 interfaces, immediate Run Owner Acceptance, and the
`LOOP_OWNER_ACCEPTED` handoff.

SLK does not own Proposal, Project Initialization, Calabash, product definition,
centralized project vulnerability audit, packaging, delivery, or project completion.

## 2. Frozen input

SLK requires a frozen LCCoding `RUN_CONTRACT` containing:

- `run_id`, `feature_slice_id`, `run_feature`, and bounded `run_scope`;
- product, integration, and applicable UI baseline identities and hashes;
- acceptance claims, counter-evidence, and evidence requirements;
- allowed autonomy and Owner-exclusive decisions;
- candidate repository and environment bindings;
- Run-local security requirements and hard brakes.

SLK never invents missing product intent. A materially incomplete input returns
`RUN_CONTRACT_INCOMPLETE` to LCCoding.

## 3. Canonical topology

SLK uses exactly two visible conversations:

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

Every formal Control record declares exactly one active responsibility mode. There
is no third visible Verification Conversation, hidden agent, background role, or
second Worker. One Worker and one CELL may be active at a time.

The Verifier mode validates in a clean environment against an immutable candidate.
Because it shares the Control Conversation, SLK does not claim blind
conversation-memory independence. If blind model-context verification is mandatory,
SLK is not suitable.

## 4. Suitability

Use SLK only when every verified GO has exactly one canonical next GO, no fixed
parallel Chain/Stage is required, no free branch/join/fallback/cycle exists, and one
persistent Worker can own the complete bounded write domain.

Use CLK for fixed parallel Chains/Stages. Use GLK for a free GO graph.

## 5. Canonical objects

### GO

A GO is one bounded independently verifiable engineering outcome, not a file edit,
command, role, module name, or business-workflow step.

Each Serial Plan GO binds:

```yaml
go_id:
ordinal:
go_contract_ref:
go_contract_version:
go_contract_hash:
lifecycle_state:
required:
d2_receipt:
formal_resolution:
```

The referenced frozen GO Contract contains intent, scope, claim, acceptance,
counter-evidence, evidence requirements, readiness conditions, and security impact.

### CELL

A CELL is the smallest independently inspectable implementation unit inside one GO.
CELLs remain strictly serial and never create a second execution topology.

### Current and Active pointers

`current_go_id` identifies the earliest unresolved Required GO. `active_go_id`
identifies the Current GO whose CELL is being implemented. These are Run-level
pointers, not GO lifecycle states. Each pointer is singular or null, and Active must
equal Current.

## 6. Invariants

1. Required GO ordinals are unique and form `1..N`.
2. Every GO resolves to one frozen GO Contract version and SHA-256.
3. There is at most one Current GO and one Active GO.
4. Active, when present, equals Current and is in `IMPLEMENTING` lifecycle state.
5. Only one CELL is active at a time.
6. Every current Required predecessor has D2 PASS for the exact predecessor
   candidate.
7. Every current Required GO must have D2 PASS before D3.
8. A formal resolution is not a substitute for D2 for a Required GO.
9. No hidden Chain, Stage, barrier, branch, merge, fallback, or cycle is allowed.
10. No silent insertion, deletion, reorder, split, merge, or receipt inheritance is
    allowed.

## 7. Responsibility authority

### Supervisor responsibility

Owns Run Contract intake, method suitability, Serial Plan and Baseline, Current and
Active pointers, provisioning, routing, Baseline Amendments, Owner-exclusive
escalation, Owner Acceptance preparation, and final handoff recording. It signs no
D1, D2, or D3 technical verdict.

### Worker

Implements the one authorized CELL in its bound mutable workspace and emits D0
evidence. It never accepts its own work, chooses the next CELL, changes the plan, or
contacts Owner.

### Checker responsibility

Validates an exact immutable CELL candidate in a clean Checker environment and owns
D1 PASS/FAIL plus CELL rework routing. It does not modify product artifacts and then
accept that edit.

### Verifier responsibility

Consumes D0/D1 receipts and validates GO composition for D2 in a fresh GO-boundary
environment. After every current Required GO has D2 PASS, it validates cross-GO Run
composition for D3 in a fresh Run-boundary environment. D2 and D3 use separate
receipts even when the same Control mode performs both.

### Owner

After D3 PASS, Owner performs bounded product acceptance for the exact Run candidate.
Only an explicit Owner verdict may produce `LOOP_OWNER_ACCEPTED`.

## 8. Verification layers

- D0 asks whether local implementation behaves as intended and evidence is ready.
- D1 asks whether the immutable CELL candidate satisfies its frozen CELL Contract.
- D2 asks whether accepted CELLs compose the frozen GO claim.
- D3 asks whether all D2-verified GOs compose the frozen Run Feature.

Higher layers consume lower immutable receipts and add only layer-specific claims and
risks. A check is repeated only for candidate/environment change, expired or
contradictory evidence, composition effects, expanded regression, or a specific new
risk. Repetition records source layer, reason, scope difference, and result.

## 9. Causal defect repair

This discipline applies only when D1 identifies an implementation defect inside the
current bounded strictly serial Run.

D1 Checker binds one `DEFECT_LINEAGE` to the exact immutable failed Candidate,
failure fingerprint, reproduction evidence, and repair round.
`defect_repair.failed_candidate_ref` must equal the D1 Receipt Envelope
`candidate_ref`. The original failure alone uses round zero; every repair Candidate,
whether passed or rejected, uses round one or greater. Only a later immutable repair
Candidate rejected by Checker increments `rejected_fix_candidate_count`;
unsuccessful investigation hypotheses do not count as repair Candidates.

Before product change, Worker D0 must record stable reproduction or evidence-backed
`NOT_REPRODUCIBLE`, one scalar active root-cause hypothesis, and one minimal
experiment that changes one variable. Product change requires a
`CONFIRMED` root cause and is limited to the smallest root-cause repair.

Every repair D0 carries the lineage `failed_candidate_ref`. When the defect is
stably reproducible and reasonably automatable, D0 `fail_before_ref.candidate_ref`
must equal that failed Candidate and `pass_after_ref.candidate_ref` must equal the
D0 Receipt Envelope `candidate_ref`; D0 also binds risk-scaled regression evidence
to the repair Candidate. Otherwise D0 records a reasoned exemption and alternative
evidence; D1 Checker must explicitly approve it.
This is defect-repair discipline, not a universal TDD requirement.

After three Checker-rejected immutable repair Candidates in one lineage, a fourth
ordinary `CELL_REWORK` is forbidden. Supervisor routes
`ARCHITECTURE_REVIEW_REQUIRED`, `METHOD_BOUNDARY_EXCEEDED`, or a versioned Contract
revision through `CONTRACT_REVISION_REQUIRED` using existing amendment authority.
The selected route binds a traceable `route_ref`. Owner is contacted only if the
chosen route crosses an Owner-exclusive decision in the Run Contract.

All causal evidence remains inside D0/D1. D2/D3 continue to add only GO/Run
composition evidence. This mechanism creates no D4, role, visible conversation,
Chain/Stage/Barrier, or graph activation.

## 10. Fail-closed receipts

Every blank D0-D3, Owner Acceptance, and Run Receipt uses the canonical state
`PENDING`. Silence, timeout, missing fields, unavailable environments, stale green
tests, or confidence never imply success.

Every Receipt Envelope binds receipt and type identities, contract and baseline
references, candidate provenance, responsibility, execution context reference,
issue time, evidence, consumed receipt identities and hashes, invalidation, and
supersession.

A material candidate change invalidates the affected receipt and every dependent
higher receipt. Product-visible change after Owner Acceptance invalidates that
acceptance.

## 11. Lifecycle and transitions

GO lifecycle values are:

```text
FROZEN
READY
IMPLEMENTING
D1_PENDING
D2_PENDING
VERIFIED
BLOCKED
CANCELLED
SUPERSEDED
```

The frozen transition table rejects skipped or unauthorized transitions. Every
transition binds its actor, trigger receipt, candidate, baseline, and timestamp.

## 12. Formal resolution

Formal resolution is limited to `CANCELLED_BY_AUTHORITY`, `REMOVED_FROM_SCOPE`, and
`SUPERSEDED`. It requires a versioned `BASELINE_AMENDMENT` with authority, reason,
evidence, old/new Required sequence, affected receipts, and replacement relation.

The amendment must remove the GO from the current Required set before D3. No GO that
remains Required may use formal resolution instead of D2 PASS.

## 13. Security boundary

SLK runs the safety checks required by the current Run Contract. LCCoding owns the
centralized project-wide vulnerability audit after Required Runs are accepted.

Known Critical/High vulnerabilities, authentication or authorization bypass,
privilege escalation, credential leakage, cross-tenant leakage, destructive risk,
or a failed Run security requirement blocks D3 and Owner Acceptance. A security fix
that changes the candidate invalidates affected D0-D3 receipts; product-visible
change also invalidates prior Run Owner Acceptance.

This hard brake does not make SLK responsible for full project penetration,
supply-chain, or centralized vulnerability closure.

## 14. Run Owner Acceptance

After D3 PASS, Supervisor provides the Run Feature, exact candidate identity,
entry/account/role, short steps, visible outcomes, known limitations, and invisible
risks covered by D3.

Allowed Owner verdicts are:

```text
LOOP_OWNER_ACCEPTED
LOOP_PRODUCT_REWORK
PRODUCT_DEFINITION_CHANGE
NEW_FEATURE_REQUEST
```

Owner Acceptance is not another technical test. Product-definition changes return
to LCCoding; bounded product defects return to the persistent Worker.

## 15. Completion

SLK completion requires every current Required GO to have D2 PASS, one D3 PASS for
the exact final candidate, synchronized non-invalidated receipts, no unresolved hard
brake, and explicit `LOOP_OWNER_ACCEPTED`.

Output is `SLK_RUN_RECEIPT` plus `LOOP_OWNER_ACCEPTED`. It is never
`DELIVERY_READY`, `VULNERABILITY_CLOSED`, or project completion.
