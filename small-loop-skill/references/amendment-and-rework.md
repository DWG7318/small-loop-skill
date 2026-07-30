# Amendment and Rework

Implementation defects return to the persistent Worker. CELL Contract defects and
GO/Run plan defects return to Supervisor for a versioned correction.

A D1 implementation-defect failure opens or advances one candidate-bound
`DEFECT_LINEAGE`. Checker records the failed immutable Candidate, failure
fingerprint, reproduction evidence, and repair round. Worker then establishes
reproduction or evidenced non-reproduction, investigates one active hypothesis
through one minimal experiment, confirms root cause before product change, and
returns the smallest root-cause repair in D0.

For defects that are stably reproducible and reasonably automatable, the repair D0
must bind fail-before evidence to the failed Candidate and pass-after plus
risk-scaled regression evidence to the repair Candidate. Otherwise Checker must
approve a reasoned exemption and alternative evidence.

Only a Checker-rejected immutable repair Candidate increments the rejection count;
failed investigation hypotheses do not. At the third rejection, ordinary
`CELL_REWORK` stops. Supervisor must route `ARCHITECTURE_REVIEW_REQUIRED`,
`METHOD_BOUNDARY_EXCEEDED`, or `CONTRACT_REVISION_REQUIRED` and bind a traceable
`route_ref` before further product work.

Formal resolution is limited to cancellation by authority, removal from scope, or
supersession. A versioned Baseline Amendment must change the Required set before the
resolution can take effect. It never substitutes for D2 on a still-Required GO.

Product-definition changes return to LCCoding.
