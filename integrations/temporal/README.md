# SLK 4.4.2 Temporal continuity templates

This package provides the required reusable `SLK.Start` and `SLK.Run` templates. A shared headless Temporal service may run many isolated Run workflow pairs; each pair keeps exact startup, delivery/native-start acknowledgement, original-sender recovery, 30-minute member residency, 20-minute OW audit, OW-exit guard and terminal closure facts.

It is not another SLK implementation. D0/D1/D2, TOKEN, role/model binding, BI and engineering decisions remain in the Skills, state and transport tools. Temporal never relays ordinary work or treats tool/terminal success as native-start proof.

## Provisioning

Install this package in an isolated operator-managed Python environment:

```powershell
py -m venv .venv-slk-temporal
.\.venv-slk-temporal\Scripts\python -m pip install .\integrations\temporal
```

This installs the official Python SDK only. It does not install/start a Temporal server, Docker, Windows service, Agent or hidden scheduler. SLK core imports remain usable without the SDK, but a 4.4.2 Run cannot pass readiness until the separately provisioned service, worker and adapter are verifiably READY.

## Entry points and adapter

```powershell
slk-temporal-worker --address 127.0.0.1:7233 --task-queue slk-local --adapter-module my_slk_temporal_adapter
slk-temporal-start --address 127.0.0.1:7233 --request .\start-slk.json
python -m slk_temporal.delivery_client request-delivery --identity .\workflow-identity.json --identity-sha256 <sha256> --request .\delivery.json --request-sha256 <sha256>
```

The delivery client is not a second sender. The original registered role owns the message; this client submits one bounded update to the exact existing native Run, after which its Activity is the sole physical launcher. `native-started` acknowledges the exact v2 receipt. The current role host, identity proof and canonical attempt root must match readiness byte-for-byte; no source-only `PYTHONPATH`, direct-transport fallback or rebuilt workflow pair qualifies.

The adapter defines five async functions: `prepare_run(value)`, `deliver_message(value)`, `request_recovery(value)`, `inspect_overwatcher(value)`, and `notify_supervisor(value)`. Each side-effect activity has one Temporal attempt and calls existing state/transport entrances with exact role credentials. Native activity must come from `slk-transport inspect-native-activity`; adapters must not invent another PID/session/start heuristic.

For new 4.4.2 histories, `notify_supervisor` calls the installed `slk-transport notify-supervisor --request <json>` with its frozen Supervisor endpoint and fresh Run projection; it returns the exact native-proof receipt, not a preset `NOTIFIED`. Supply genuinely inherited native Desktop host capability; do not fabricate a caller or resume a Desktop-owned thread through CLI. The existing OW audit/owning-host exit hook uses `observe_overwatcher_exit` and sends its notice to `overwatcher_exited`; unexpected exits do not rely on OW's final message. Failed or malformed notification keeps a visible runtime guard and bounded monitoring; it never clears the guard or counts as takeover. Historical 4.4.1 patch markers retain old command/receipt replay branches, not permission to use legacy echo-only readiness for new work.

See [`docs/runtime/SLK-TEMPORAL.md`](../../docs/runtime/SLK-TEMPORAL.md) for the fail-closed runtime and closure contract.
