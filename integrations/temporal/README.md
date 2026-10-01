# SLK Temporal continuity templates

This optional package contains the two reusable SLK 4.3.6 templates:

- `SLK.Start` (`StartSlkWorkflow`) validates one closed startup identity and starts exactly one deterministic child Run workflow.
- `SLK.Run` (`RunSlkWorkflow`) records delivery, matching native-start acknowledgement, timeout, recovery request and terminal closure.

It is not another SLK implementation. D0, D1, D2, SLK TOKEN, role/model binding, BI and engineering decisions remain in the existing SLK Skills, state and transport tools. A successful activity or terminal tool result is not a native-start acknowledgement.

## Optional installation

Core SLK does not import this package. Install it only in an isolated environment chosen for Temporal operation:

```powershell
py -m venv .venv-slk-temporal
.\.venv-slk-temporal\Scripts\python -m pip install .\integrations\temporal
```

This installs the official Python SDK dependency. It does not install or start a Temporal server, Windows service, Docker, Agent or scheduler.

## Entry points

An existing Temporal endpoint and an explicit adapter module are required:

```powershell
slk-temporal-worker --address 127.0.0.1:7233 --task-queue slk-local --adapter-module my_slk_temporal_adapter
slk-temporal-start --address 127.0.0.1:7233 --request .\start-slk.json
```

The adapter module must define the three async functions `prepare_run(value)`, `deliver_message(value)` and `request_recovery(value)`. Receipts use the exact fields enforced in `workflows.py`; each side-effect activity has one Temporal attempt. Deployment code remains responsible for calling the existing SLK state/transport entry points with bound role credentials, and must reuse `slk-transport inspect-native-activity` rather than inventing a second PID/session/start heuristic.

If the package, adapter or endpoint is absent, do not infer that Temporal mode is active. Continue the normal direct SLK path or report the explicit startup blockage. See `docs/runtime/SLK-TEMPORAL.md` for the Windows local procedure and contract boundaries.
