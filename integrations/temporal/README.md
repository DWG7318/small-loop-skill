# SLK 4.4.0 Temporal continuity templates

This package provides the required reusable `SLK.Start` and `SLK.Run` templates. A shared headless Temporal service may run many isolated Run workflow pairs; each pair keeps exact startup, delivery/native-start acknowledgement, original-sender recovery, 30-minute member residency, 20-minute OW audit, OW-exit guard and terminal closure facts.

It is not another SLK implementation. D0/D1/D2, TOKEN, role/model binding, BI and engineering decisions remain in the Skills, state and transport tools. Temporal never relays ordinary work or treats tool/terminal success as native-start proof.

## Provisioning

Install this package in an isolated operator-managed Python environment:

```powershell
py -m venv .venv-slk-temporal
.\.venv-slk-temporal\Scripts\python -m pip install .\integrations\temporal
```

This installs the official Python SDK only. It does not install/start a Temporal server, Docker, Windows service, Agent or hidden scheduler. SLK core imports remain usable without the SDK, but a 4.4.0 Run cannot pass readiness until the separately provisioned service, worker and adapter are verifiably READY.

## Entry points and adapter

```powershell
slk-temporal-worker --address 127.0.0.1:7233 --task-queue slk-local --adapter-module my_slk_temporal_adapter
slk-temporal-start --address 127.0.0.1:7233 --request .\start-slk.json
```

The adapter defines five async functions: `prepare_run(value)`, `deliver_message(value)`, `request_recovery(value)`, `inspect_overwatcher(value)`, and `notify_supervisor(value)`. Each side-effect activity has one Temporal attempt and calls existing state/transport entrances with exact role credentials. Native activity must come from `slk-transport inspect-native-activity`; adapters must not invent another PID/session/start heuristic.

See [`docs/runtime/SLK-TEMPORAL.md`](../../docs/runtime/SLK-TEMPORAL.md) for the fail-closed runtime and closure contract.
