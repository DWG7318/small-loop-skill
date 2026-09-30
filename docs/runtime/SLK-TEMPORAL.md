# Optional Temporal continuity for SLK 4.3.4

## Boundary

Temporal is an explicit per-Run continuity option, not a required SLK runtime. The core install and all direct `Supervisor ↔ Checker ↔ Worker` routes work without the SDK or server. One opted-in Run owns one `SLK.Start` parent and one `SLK.Run` child; workflow IDs are deterministic from `run_id`.

The templates persist only startup identity and exact communication facts. They never decide D0/D1/D2, move SLK TOKEN, write BI, select a model, create or replace a role, or choose a CELL. A matching native-start ACK is the only positive activation fact. Delivery success, activity completion, process exit and terminal result are not ACKs.

On bounded ACK timeout, `SLK.Run` requests one exact recovery. A bound Overwatcher is the recovery target; without one, the original sender remains responsible. The receiver, payload hash, scope, CELL, attempt and operation identity cannot change. A matching ACK stops recovery. If no verified route exists, the adapter reports `BLOCKED` rather than inventing progress.

## Windows local setup

1. Obtain the official Temporal CLI for Windows from the [Temporal CLI releases](https://github.com/temporalio/cli/releases). Keep it outside the SLK repository.
2. Start a local development service in a hidden/headless process chosen by the operator. For a persistent development database:

   ```powershell
   temporal.exe server start-dev --ip 127.0.0.1 --port 7233 --ui-port 8233 --db-filename C:\path\to\slk-temporal.db
   ```

3. Create a dedicated Python virtual environment and install `integrations/temporal` as shown in its README.
4. Supply an adapter module whose activities call the already-authoritative SLK state and transport commands. Start `slk-temporal-worker` on the frozen task queue.
5. Write a closed startup JSON matching `StartSlkRequest`, then call `slk-temporal-start` once. Preserve the returned startup fingerprint and workflow IDs with the Run evidence.
6. Stop the local process explicitly when no opted-in Run requires it. The SLK installer never installs, enables or restores a server or Docker.

The development server is suitable for local evaluation, not a production durability claim. Production use requires a separately operated Temporal service and its own backup, access-control and availability decisions.

## Startup request

The exact startup schema is enforced by `slk_temporal.contracts.StartSlkRequest`. It binds method version 4.3.4, `run_id`, runtime revision, task queue, acknowledgement timeout, startup idempotency key, exactly one Supervisor/Checker/Worker endpoint and at most one Overwatcher endpoint. Unknown fields, padded identities, duplicate role instances, invalid hashes and unsupported versions fail closed.

The parent first obtains a hash-bound readiness receipt. It then starts `slk-run-<run_id>` once. A caller may reconnect to the same unchanged parent workflow; a changed request under the same identity is rejected through the frozen startup fingerprint.

## Operation sequence

1. The authoritative sender requests one delivery with immutable operation/message identity, role endpoints, scope, payload SHA-256 and runtime revision.
2. The delivery activity invokes the existing transport boundary once.
3. The receiving native Agent entry records an independently matched native-start ACK.
4. The original sender commits the existing SLK delivery-start transaction. Temporal does not commit TOKEN.
5. If the ACK deadline expires first, the workflow requests exact recovery from the Overwatcher or sender. It does not retry side effects invisibly or alter engineering scope.

Only one unresolved delivery is permitted per serial Run workflow. Duplicate unchanged updates are idempotent; changed duplicates and mismatched ACKs fail closed.

## Fallback

- SDK/package absent: use normal SLK direct communication.
- Service unreachable before opt-in readiness: do not start Temporal mode; use direct mode or report a startup blockage.
- Service becomes unavailable after opt-in: retain the last authoritative SLK state and report continuity as unavailable; do not infer ACK, D1, D2 or progress.
- Adapter cannot verify a continuation route: return `BLOCKED`; Supervisor decides outside Temporal.

No fallback may silently change receiver, model, reasoning effort, role instance, CELL, attempt, payload or acceptance authority.
