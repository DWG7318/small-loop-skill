# Required Temporal continuity for SLK 4.4.2

## Boundary

One shared, headless local Temporal service may host many SLK Runs. Every 4.4.2 Run must prove service/worker readiness before dispatch and owns one deterministic `SLK.Start` plus one independent `SLK.Run`; ending one Run closes only its workflows, not the shared service or another Run.

`slk-transport reload-temporal-worker` is the only bounded code-reload entrance. A hash-bound request freezes the exact old process chain, adapter/workflow bytes, task queue and existing Start/Run workflow IDs, native run IDs and startup fingerprint. It stops only those processes, starts the same queue headlessly with the new source, and succeeds only after `slk_temporal.inspector` re-queries the identical workflow pair. It never calls a workflow start/terminate API or resets history.

Temporal stores continuity and timing facts only. It never decides D0/D1/D2, moves TOKEN, writes BI, selects a model, creates/replaces a role, chooses a CELL, or becomes a communication participant. Direct registered members remain the first responsibility: Checker sends the CELL to Worker, Worker returns the candidate to Checker, Checker sends formal D1 FAIL or final D2 readiness to Supervisor, and Supervisor sends the first bounded rework directive or version-replans after a second consecutive formal failure.

For a ready 4.4.2 Run, that original sender invokes hash-bound `slk-transport continue-staged-handoff`; its Role Host submits the exact delivery through `slk_temporal.delivery_client`, the existing `SLK.Run` schedules the sole `slk.deliver_message` Activity, and that Activity is the only physical native launcher. After validating the exact native start, the same Host uses the sealed sender credential to commit central TOKEN. If an externally submitted exact operation already launched the receiver, the caller also supplies that request path/hash so the Host records only its missing ACK before commit; a Host-owned acknowledged retry is commit-only. Neither path repeats request or native launch. Historical v1 hosts remain readable for old evidence, but cannot satisfy current Temporal readiness.

The only positive activation fact is a matching `slk.native-start/v2` acknowledgement. Tool success, terminal output, process exit, visible text, BI state and old activity do not substitute.

## Runtime guarantees

- Delivery timeout asks the exact original sender to recover the unchanged message; OW never relays or retries normal communication.
- A member timer begins only after matching native start. If one responsibility remains on that member for more than 30 minutes, Temporal sends one scoped notice directly to the registered Supervisor; it does not decide whether the work is defective.
- Every 20 minutes Temporal checks the registered OW native activity. Missing, mismatched, terminal, or anomalous evidence freezes the Run runtime guard and notifies Supervisor.
- Every OW exit, including a Supervisor-requested stop, freezes the guard and notifies Supervisor for a second confirmation. Only an exact current-Supervisor resolution with restored OW evidence clears it.
- While the guard is unresolved, no next CELL may dispatch. Mechanical recovery and Supervisor-directed repair may coexist, but Supervisor chooses and records the resolution.

## Windows local setup

1. Provision the official Temporal CLI/service outside this repository and operate it headlessly on the local machine. SLK never installs Docker or a service.
2. Install `integrations/temporal` without network/dependency changes in the Run's registered Python environment and start `slk-temporal-worker --standard-config-root <root>` on the frozen task queue. Prove the installed `start`, `admit` and `delivery` entries from that exact environment; no caller adapter module is required.
3. Write the closed `<run>.bootstrap.json`, then call `slk-temporal-start ... --identity-out <absolute path>`. It validates the live central four-role registry and creates the deterministic pair once; the child remains `AWAITING_ADMISSION` and rejects delivery.
4. Inspect the real pair, freeze its identity into RoleHost/OW/readiness evidence, and write the full `<run>.json` with an explicit admission kind/path. An existing Codex Desktop OW first uses installed `attest-desktop-overwatcher`; standard config v2 binds its attestation path/hash, and every audit passes that proof to `inspect-native-activity` for a fresh platform `read_thread`. The request's `reader_thread_id` records the trusted attestation creator; later audits use each invocation's genuinely inherited Desktop caller thread/pipe/originator while keeping the target OW Run/role/endpoint/thread/turn/input/hash immutable. The installed `integrations/temporal/slk-overwatcher-capabilities.json` is its closed readiness fact. A product Run uses `PRODUCT` + `preflight-new-run` and a distinct sealed source. Only a disposable one-CELL Run may use `ISOLATED_CONFORMANCE_SAMPLE` + `preflight-conformance-sample`: runtime evidence is contained by `slk-conformance/<SLK-CONFORMANCE-…>`, Worker uses the exact separate sample Git proven clean, fixed at the contracted HEAD and without a remote, and Supervisor/Checker/OW preserve their truthful native workspaces/cwd. The CELL `root_record_path` remains the exact automatically exported record under the active `SLK_CONFIG_PATH` data root; it is not copied into the sample Git. Call `slk-temporal-admit` with the hash-bound identity; only `READY/IDLE` permits its bounded dispatch.
5. Preserve bootstrap receipt, startup fingerprint, native workflow IDs, admission receipt, update receipts and terminal closure as Run evidence. After a plan split, freeze the new RoleHost revision and atomically replace only the current Host path/hash in that Run's full config before standard `CELL_DISPATCH`.

A development server is suitable only for local evaluation. Durable production operation needs separately governed backup, access control and availability. A missing SDK may not break import of the SLK core, but a 4.4.2 Run without proven Temporal readiness is blocked.

## Closed operation

The startup request binds version 4.4.2, Run/revision/task queue, timeouts, idempotency key and exactly one Supervisor, Checker, Worker and Overwatcher endpoint. Unknown fields, padded identities, duplicate role instances, missing OW, invalid hashes, wrong versions, stale update events and mismatched acknowledgements fail closed.

Startup is deliberately two-stage. Bootstrap proves current central identities and service reachability, then creates the unique workflow pair; it cannot claim product readiness. Full admission runs only after that pair's native IDs are available and the exact Host/OW evidence exists. It is idempotent for the same identity and never rebuilds the pair. A first-start circular dependency, synthetic native IDs, or delivery while admission is pending fails closed.

Each delivery update freezes operation/message, sender/receiver, payload, GO/CELL/round, runtime revision and start deadline. Duplicate identical updates are idempotent; changed duplicates, extra unresolved deliveries and wrong-scope ACKs are rejected. Temporal records no synthetic progress and cannot turn recovery, terminal completion or elapsed time into acceptance.

`DELIVERY_REQUESTED` may wait only for the matching native v2 receipt. `BLOCKED` and `RECOVERY_REQUIRED` are recorded and returned immediately to the original role; they never become a misleading 300-second native-start timeout. If a crash occurs after `DELIVERY_ACKNOWLEDGED` but before central TOKEN commit, the retry preserves both status-specific update results, validates the existing native receipt and performs only the missing central commit—never a second native launch or second ACK.

## Failure and closure

Service/worker/adapter failure after readiness preserves the last authoritative SLK facts, freezes the runtime guard and routes repair to Supervisor. It never silently falls back to an unguarded Run. After exact Run terminal evidence and Supervisor closure, close only that Run's workflows; keep the shared service available for other Runs.
