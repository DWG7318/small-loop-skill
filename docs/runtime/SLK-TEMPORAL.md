# Required Temporal continuity for SLK 4.4.1

## Boundary

One shared, headless local Temporal service may host many SLK Runs. Every 4.4.1 Run must prove service/worker readiness before dispatch and owns one deterministic `SLK.Start` plus one independent `SLK.Run`; ending one Run closes only its workflows, not the shared service or another Run.

`slk-transport reload-temporal-worker` is the only bounded code-reload entrance. A hash-bound request freezes the exact old process chain, adapter/workflow bytes, task queue and existing Start/Run workflow IDs, native run IDs and startup fingerprint. It stops only those processes, starts the same queue headlessly with the new source, and succeeds only after `slk_temporal.inspector` re-queries the identical workflow pair. It never calls a workflow start/terminate API or resets history.

Temporal stores continuity and timing facts only. It never decides D0/D1/D2, moves TOKEN, writes BI, selects a model, creates/replaces a role, chooses a CELL, or becomes a communication participant. Direct registered members remain the first responsibility: Checker sends the CELL to Worker, Worker returns the candidate to Checker, Checker sends formal D1 FAIL or final D2 readiness to Supervisor, and Supervisor sends the structured rework directive to the same Worker.

For a ready 4.4.1 Run, that original sender submits the exact delivery through the hash-bound `slk_temporal.delivery_client`; the existing `SLK.Run` schedules the sole `slk.deliver_message` Activity, and that Activity is the only physical native launcher. The role host never also calls direct transport. Historical v1 hosts remain readable for old evidence, but cannot satisfy current Temporal readiness.

The only positive activation fact is a matching `slk.native-start/v2` acknowledgement. Tool success, terminal output, process exit, visible text, BI state and old activity do not substitute.

## Runtime guarantees

- Delivery timeout asks the exact original sender to recover the unchanged message; OW never relays or retries normal communication.
- A member timer begins only after matching native start. If one responsibility remains on that member for more than 30 minutes, Temporal sends one scoped notice directly to the registered Supervisor; it does not decide whether the work is defective.
- Every 20 minutes Temporal checks the registered OW native activity. Missing, mismatched, terminal, or anomalous evidence freezes the Run runtime guard and notifies Supervisor.
- Every OW exit, including a Supervisor-requested stop, freezes the guard and notifies Supervisor for a second confirmation. Only an exact current-Supervisor resolution with restored OW evidence clears it.
- While the guard is unresolved, no next CELL may dispatch. Mechanical recovery and Supervisor-directed repair may coexist, but Supervisor chooses and records the resolution.

## Windows local setup

1. Provision the official Temporal CLI/service outside this repository and operate it headlessly on the local machine. SLK never installs Docker or a service.
2. Install `integrations/temporal` without network/dependency changes in the Run's registered Python environment and start `slk-temporal-worker` on the frozen task queue. Prove `python -m slk_temporal.delivery_client --help` from that exact environment.
3. Supply an adapter whose five async functions call existing authoritative entrances: `prepare_run`, `deliver_message`, `request_recovery`, `inspect_overwatcher`, and `notify_supervisor`.
4. Before CELL dispatch, pass `slk-run-readiness/v1` with exact service/worker health plus both deterministic workflow identities, then start the closed 4.4.1 request once.
5. Preserve startup fingerprint, workflow IDs, update receipts and terminal closure as Run evidence.

A development server is suitable only for local evaluation. Durable production operation needs separately governed backup, access control and availability. A missing SDK may not break import of the SLK core, but a 4.4.1 Run without proven Temporal readiness is blocked.

## Closed operation

The startup request binds version 4.4.1, Run/revision/task queue, timeouts, idempotency key and exactly one Supervisor, Checker, Worker and Overwatcher endpoint. Unknown fields, padded identities, duplicate role instances, missing OW, invalid hashes, wrong versions, stale update events and mismatched acknowledgements fail closed.

Each delivery update freezes operation/message, sender/receiver, payload, GO/CELL/round, runtime revision and start deadline. Duplicate identical updates are idempotent; changed duplicates, extra unresolved deliveries and wrong-scope ACKs are rejected. Temporal records no synthetic progress and cannot turn recovery, terminal completion or elapsed time into acceptance.

`DELIVERY_REQUESTED` may wait only for the matching native v2 receipt. `BLOCKED` and `RECOVERY_REQUIRED` are recorded and returned immediately to the original role; they never become a misleading 300-second native-start timeout. If a crash occurs after `DELIVERY_ACKNOWLEDGED` but before central TOKEN commit, the retry preserves both status-specific update results, validates the existing native receipt and performs only the missing central commit—never a second native launch or second ACK.

## Failure and closure

Service/worker/adapter failure after readiness preserves the last authoritative SLK facts, freezes the runtime guard and routes repair to Supervisor. It never silently falls back to an unguarded Run. After exact Run terminal evidence and Supervisor closure, close only that Run's workflows; keep the shared service available for other Runs.
