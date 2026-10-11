# SLK 4.5.0 Temporal continuity templates

## Current delivery and ordinary startup

The unified prebuilt SLK package includes the pinned Python SDK and Temporal CLI.
Ordinary users call `tools/slk/bin/slk-temporal*.cmd`; they do not install Python,
pip packages or a server per Run. Development-only isolated package builds may
use this prefix's `pyproject.toml`. No installer enables Docker or creates an
unrequested OS service/scheduler.

One shared headless server/worker manages independent `SLK.Start`/`SLK.Run`
pairs. Keep the existing bootstrap → identity → frozen Role Host/OW proof →
PRODUCT admission ordering. For 4.5.0, `preflight-new-run` uses the lightweight
`preflight-basic` contract, not historical seven-leg conformance. Admission
checks the actual current native OW child once, without requiring an earlier
cycle or first CELL. The parent Supervisor owns one child across its Runs;
closing one pair neither closes that child nor the shared service.

Twenty minutes is a preparation aim, not a deadline or failure gate. The
independent 1200-second OW audit and 1800-second member-residency notice are
continuity functions, not preparation limits.

The following 4.4.3 provisioning/legacy-Desktop instructions are historical
maintenance references only. The 4.5.0 native wiring section below defines
current OW evidence; never send a 4.5.0 child through the old Desktop contract.

This package provides the required reusable `SLK.Start` and `SLK.Run` templates. A shared headless Temporal service may run many isolated Run workflow pairs; each pair keeps exact startup, delivery/native-start acknowledgement, original-sender recovery, 30-minute member residency, 20-minute OW audit, OW-exit guard and terminal closure facts.

It is not another SLK implementation. D0/D1/D2, TOKEN, role/model binding, BI and engineering decisions remain in the Skills, state and transport tools. Temporal never relays ordinary work or treats tool/terminal success as native-start proof.

## Historical source provisioning (4.4.3)

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

For new 4.4.3 histories, `notify_supervisor` calls the installed `slk-transport notify-supervisor --request <json>` with its frozen Supervisor endpoint and fresh Run projection; it returns the exact native-proof receipt, not a preset `NOTIFIED`. Supply genuinely inherited native Desktop host capability; do not fabricate a caller or resume a Desktop-owned thread through CLI. Failed or malformed notification keeps a visible runtime guard and bounded monitoring; it never clears the guard or counts as takeover. Historical 4.4.1 patch markers retain old command/receipt replay branches, not permission to use legacy echo-only readiness for new work. Earlier text claiming an automatically connected `observe_overwatcher_exit` owning-host hook was incorrect: the helper alone did not register such a hook.

## 4.5.0 native OW wiring (source support, not a release/deployment claim)

4.5.0 uses the actual Supervisor's one direct native subagent across all its Runs. In the existing v2 config, `attestation_path`/`attestation_sha256` refer to `slk.subagent-overwatcher-proof/v1`, not the historical Desktop attestation. v1 is not accepted for 4.5.0. Config loading only checks the frozen hash/method/Run/role/endpoint/start association; ordinary delivery does not require a live OW sample. Audit and resume invoke the original transport reader with `--subagent-overwatcher-proof`, its hash and one fresh central projection. It rejoins the unique active Supervisor's runtime/parent Session/endpoint host, and the unique active OW's role/child Session/endpoint/current execution. The parent host is a registered declaration; the private rollout does not independently attest it.

The reader only reads the exact parent's current private JSONL. It does not invoke native `list_agents`, copy conversation bodies, probe the reader PID, or extend the original 300-second query/output freshness limit. A 600-second OW self-observation does not refresh the parent's native list sample. A 1200-second audit without a fresh sample therefore produces `ANOMALY`, never confirmed death, stop, restart or automatic child wake. Supervisor obtains a fresh native `list_agents` result and repeats the same proof probe/cadence check. Unsupported native statuses remain unknown. The current reader supports original running/completed samples; the audit also recognizes a verified `FAILED_WITHOUT_TERMINAL` should the native reader provide one, not an invented failed status dictionary.

The six-field audit receipt is unchanged. Only immutable 4.5.0 startup accepts `EXITED`, for fresh native `COMPLETED_WITHOUT_TERMINAL`/`FAILED_WITHOUT_TERMINAL`; this takes precedence over late/missing cadence and sets the existing `OVERWATCHER_EXIT_REQUIRES_SUPERVISOR_CONFIRMATION` guard. A `CLEAR` also requires this Run's 600-second cycle for the same current child Session and execution. Small native/cadence audit evidence is retained under `notification_attempt_root/<run_id>/overwatcher-audits/<evidence_sha256>.json`; re-observing the same audit cycle does not overwrite a different observation. Unknown or stale evidence requires Supervisor inspection. Failed notice delivery retains the guard and monitoring. Notice acceptance is not proof the Supervisor has read or taken over.

When a native completion callback reaches an active parent, Supervisor can obtain a fresh native list sample and current central Run projection, then use these actual local entrances (absolute file paths and actual hashes):

```text
slk-transport observe-overwatcher-exit --started STARTED.json --subagent-overwatcher-proof PROOF.json --subagent-overwatcher-proof-sha256 SHA256 --runtime-projection FRESH-RUN.json --requested-by-role-instance-id SUPERVISOR-ID
python -m slk_temporal.delivery_client overwatcher-exited --identity EXACT-PAIR.json --identity-sha256 SHA256 --request VERIFIED-EXIT-NOTICE.json --request-sha256 SHA256
python -m slk_temporal.delivery_client resolve-runtime-guard --identity EXACT-PAIR.json --identity-sha256 SHA256 --request SUPERVISOR-RESOLUTION.json --request-sha256 SHA256
```

The read-only first command rechecks original spawn/followup/status records plus current registration; it emits the existing closed five-field exit notice only for a confirmed native exit, `NO_CONFIRMED_EXIT` for live execution, and rejects unknown/stale evidence. Supervisor saves that notice unchanged for the second command. Both client operations use the existing exact hashed workflow identity and updates, reject changed Run/Supervisor/OW/event or nonclosed replies, and retain the trusted-local-client authority boundary; they are not a defense against an arbitrary privileged shell. No automatic callback registration or guaranteed wake of an idle/finished parent turn is claimed. The independent 20-minute audit is the fallback, not a new background poller.

For recovery, Supervisor first runs `inspect-native-activity --started ... --subagent-overwatcher-proof ... --subagent-overwatcher-proof-sha256 ... --runtime-projection ...` and `inspect-overwatcher-cadence --runtime-projection ... --observed-at ...` against fresh evidence. The existing closed resolution contains `event_id, run_id, supervisor_role_instance_id, blocker_event_id, resolution: OVERWATCHER_RESTORED, evidence_sha256`. Restored means trustworthy current evidence is restored; it does not require restarting the child. The update receipt proves only acceptance of that Supervisor resolution, not an independent repair or engineering approval. A guard blocks the next CELL but allows the exact already-running CELL to finish its handoffs; unknown current scope cannot be guessed. OW remains read-only apart from its own observations and parent reports, continues 600-second self-checks after reporting, and cannot dispatch/retry/repair or write engineering state. Stop requires Supervisor's second confirmation. Closing one Run only closes its own workflow pair, not the shared OW, worker or service.

`slk-overwatcher-native-capabilities.json` is a separate static descriptor of the native spawn/list/followup record reader. It does not relabel the 4.4.2 Desktop descriptor or prove a particular child is active. Actual 4.5.0 readiness uses the current basic contract and native proof; source or descriptor presence alone never stamps a package released, installed or ready.

See [`docs/runtime/SLK-TEMPORAL.md`](../../docs/runtime/SLK-TEMPORAL.md) for the fail-closed runtime and closure contract.
