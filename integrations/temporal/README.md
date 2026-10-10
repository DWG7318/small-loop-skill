# SLK 4.4.3 Temporal continuity templates

This package provides the required reusable `SLK.Start` and `SLK.Run` templates. A shared headless Temporal service may run many isolated Run workflow pairs; each pair keeps exact startup, delivery/native-start acknowledgement, original-sender recovery, 30-minute member residency, 20-minute OW audit, OW-exit guard and terminal closure facts.

It is not another SLK implementation. D0/D1/D2, TOKEN, role/model binding, BI and engineering decisions remain in the Skills, state and transport tools. Temporal never relays ordinary work or treats tool/terminal success as native-start proof.

## Provisioning

Install this package in an isolated operator-managed Python environment:

```powershell
py -m venv .venv-slk-temporal
.\.venv-slk-temporal\Scripts\python -m pip install .\integrations\temporal
```

This installs the official Python SDK only. It does not install/start a Temporal server, Docker, Windows service, Agent or hidden scheduler. SLK core imports remain usable without the SDK, but a 4.4.3 Run cannot pass readiness until the separately provisioned service, worker and adapter are verifiably READY.

Installing files does not upgrade an already-loaded worker or an old Python environment. Before the next Run, install the accepted global mirror into its operator-managed environment, verify package version 4.4.3 plus actual imported source paths/hashes and the new queue/config binding. Preserve completed old pairs/history and the shared service; do not relabel a loaded 4.4.2 worker or silently restart its old pair.

## Entry points and adapter

```powershell
slk-temporal-worker --address 127.0.0.1:7233 --task-queue slk-local --standard-config-root C:\slk\temporal-runs
slk-temporal-start --address 127.0.0.1:7233 --request .\start-slk.json --standard-config-root C:\slk\temporal-runs --identity-out C:\slk\temporal-runs\RUN-A.identity.json
slk-temporal-admit --identity C:\slk\temporal-runs\RUN-A.identity.json --identity-sha256 <sha256>
slk-transport continue-staged-handoff --binding .\role-host.json --sha256 <sha256> --source-attempt .\attempts\<run-id>\<message-id>
```

The built-in standard adapter is the normal path. Before `start`, `<run_id>.bootstrap.json` contains only the exact query command and central state config; it verifies the current four-role registry/runtime and does not require a Role Host, OW start evidence or workflow identity. `start` creates the deterministic pair once and writes its real native identity while the child remains `AWAITING_ADMISSION`. Only then create the full `<run_id>.json`, freeze the identity-aware Role Host and OW evidence, and set `admission_kind` plus `admission_path`: ordinary Runs select `PRODUCT`/`preflight-new-run`; only a disposable one-CELL Run with a `slk-conformance/<SLK-CONFORMANCE-…>` evidence root and separate clean, fixed-HEAD, no-remote sample Git selects `ISOLATED_CONFORMANCE_SAMPLE`/`preflight-conformance-sample`. Call `admit` afterward. Any delivery before successful admission is rejected. A caller-supplied adapter remains an advanced compatibility path, not a requirement for ordinary SLK.

The delivery client is not a second sender. The original registered role owns the message and enters through the hash-bound Role Host above; the Host uses its sealed credential, submits one bounded update to the exact existing native Run, validates `native-started`, then commits TOKEN. If an exact external request already produced `started.json`, pass `--temporal-request <path> --temporal-request-sha256 <sha256>` so only that operation's missing ACK and commit run; a locally proven ACK makes retry commit-only. Neither case repeats request or native launch. The current role host, identity proof and canonical attempt root must match readiness byte-for-byte; no source-only `PYTHONPATH`, direct-transport fallback or rebuilt workflow pair qualifies.

The adapter defines five async functions: `prepare_run(value)`, `deliver_message(value)`, `request_recovery(value)`, `inspect_overwatcher(value)`, and `notify_supervisor(value)`. `prepare_run` is invoked only by explicit post-pair admission. Each side-effect activity has one Temporal attempt and calls existing state/transport entrances with exact role credentials. Native activity must come from `slk-transport inspect-native-activity`; adapters must not invent another PID/session/start heuristic.

For an already-active Codex Desktop OW, run installed `slk-transport attest-desktop-overwatcher` from a trusted Desktop host before admission. It reads the exact registered thread/turn/input item without sending or invoking a model and emits hash-bound start/attestation files. The frozen reader identifies that attestation creator only; every 1200-second audit must inherit its own real Desktop caller thread/pipe/originator, while the attested target identity stays unchanged. Use `slk.temporal-standard-adapter/v2` with `attestation_path` and `attestation_sha256`; each audit performs a fresh `read_thread` through `inspect-native-activity` instead of trusting the saved snapshot. Point OW readiness at installed `slk-overwatcher-capabilities.json`.

For new 4.4.3 histories, `notify_supervisor` calls the installed `slk-transport notify-supervisor --request <json>` with its frozen Supervisor endpoint and fresh Run projection; it returns the exact native-proof receipt, not a preset `NOTIFIED`. Supply genuinely inherited native Desktop host capability; do not fabricate a caller or resume a Desktop-owned thread through CLI. The existing OW audit/owning-host exit hook uses `observe_overwatcher_exit` and sends its notice to `overwatcher_exited`; unexpected exits do not rely on OW's final message. Failed or malformed notification keeps a visible runtime guard and bounded monitoring; it never clears the guard or counts as takeover. Historical 4.4.1 patch markers retain old command/receipt replay branches, not permission to use legacy echo-only readiness for new work.

See [`docs/runtime/SLK-TEMPORAL.md`](../../docs/runtime/SLK-TEMPORAL.md) for the fail-closed runtime and closure contract.
