# SLK 4.4.2 local compatibility and adoption

4.4.2 is an adjacent, explicit method adoption from 4.4.1. Installing the package does not resume a Run, dispatch a CELL, start or reload Temporal, replace a role, modify BI/WebBI, or change product files.

At an Owner-selected stable Supervisor boundary, preserve the exact Run identity, four role bindings and Sessions, plan/CELL history, TOKEN, candidates, D0/D1/D2, OW cycles, transport attempts and Temporal workflow histories. Submit one hash-bound `4.4.1 → 4.4.2` adoption through the existing Supervisor administration path. Old 4.4.0/4.4.1 requests stay immutable and are consumed only through their existing compatibility paths; they are never relabelled.

Before the next dispatch, produce fresh 4.4.2 readiness and Role Eval evidence. Freeze the OCRV token/time execution limits, confirm the canonical Temporal Checker attempt root, and prove current role endpoints and credential consumers. Supervisor reviews remaining undispatched CELL sizes against the actual DSH capability and cumulative load without changing the Run outcome or acceptance strength.

The ordinary loop still belongs to Checker and Worker. The first formal product D1 failure may use the bounded same-CELL rework path. A second consecutive formal D1 failure stops ordinary rework: Supervisor compares both rounds, version-replans the unaccepted remainder into dependency-ordered small or medium successor CELLs with independent D0/D1, then returns the revised plan to Checker. INCOMPLETE, tool/transport failure and duplicate receipts do not count. If no honest split remains, keep the Run blocked and choose another explicit route rather than issuing a third ordinary retry.

BI/WebBI remain 1.1.0. No Docker installation, extra role, scheduler, daemon, wmux substrate, push, tag or Release is part of this migration.
