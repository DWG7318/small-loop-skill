# Causal Defect Repair

This discipline applies only after D1 identifies a defect in one bounded strictly
serial Run.

## D1 lineage binding

Checker binds the immutable failed Candidate, a stable failure fingerprint,
reproduction evidence, and one `defect_lineage_id`. The original failure opens
round zero. Each later Checker-rejected immutable repair Candidate advances the
round once; discarded hypotheses and experiments do not.

## D0 investigation and repair

Worker records either a stable reproduction or evidence that reproduction was not
achieved. Investigation keeps one scalar active hypothesis and changes one variable
in one minimal experiment. A product change is allowed only after the root cause is
confirmed by evidence, and its scope is limited to the smallest root-cause repair.

When the defect is stably reproducible and reasonably automatable, D0 binds:

- fail-before evidence to the failed Candidate;
- pass-after evidence to the repair Candidate;
- regression evidence proportional to the changed risk.

When that rule is not applicable, D0 records a reason and alternative evidence.
Checker must explicitly approve the exemption in D1.

## Third-rejection gate

At three Checker-rejected immutable repair Candidates in one lineage, a fourth
ordinary rework is forbidden. Supervisor selects one of:

- `ARCHITECTURE_REVIEW_REQUIRED`;
- `METHOD_BOUNDARY_EXCEEDED`;
- `CONTRACT_REVISION_REQUIRED` through existing versioned amendment authority.

The D1 receipt binds the selected route to a traceable `route_ref`. This gate does
not automatically contact Owner. Owner is involved only when the
chosen route crosses an Owner-exclusive decision already defined by the Run
Contract.

The discipline remains within D0/D1. D2 and D3 continue to add only GO and Run
composition evidence.
