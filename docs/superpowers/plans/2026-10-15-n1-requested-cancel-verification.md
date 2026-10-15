# N1 REQUESTED cancellation verification

Scope: source-only 4.x repair in the isolated `bi-113-run09-repair` worktree.
No installation, provider/Temporal network call, live Run write, deployment, Docker,
or native agent invocation was performed. 3.x is unchanged.

## Behavior

- Existing sealed `resume-run` accepts explicit `cancel_requested: true` plus a
  nonblank `reason`, bound to the exact original request, Supervisor, Run, pause
  and current runtime revision. It does not invoke the census or resume preflight.
- Temporal -> central -> Temporal retains the same cancellation event on retries.
  Central cancellation has exactly four detail fields and never fabricates
  `RUN_PAUSED`, `QUIESCENT`, or a TOKEN transition.
- REQUESTED -> RESUMED preserves member residency time and the original pending
  operation. A new pause ID clears the old confirmed timestamp; delayed PAUSED
  cannot resurrect a cancelled request. Checkpoint validation permits cancellation
  without inventing a pause timestamp.
- The existing lifecycle Temporal subprocess explicitly passes `credential=None`,
  matching the real required keyword-only command signature.

## RED then GREEN

PowerShell environment (existing installations; no SDK install):

```powershell
$env:PATH = 'C:/Users/DWG/.cargo/bin;' + $env:PATH
$env:PYTHONPATH = 'C:/Users/DWG/.codex/tools/slk/runtime/python/Lib/site-packages'
```

Python: `C:/Python314/python.exe`; installed Temporal SDK: `1.34.0`.

RED commands and observed failures before the corresponding production edits:

```powershell
cargo test -p slk-state-core --locked --offline --test write_flow cancel_requested -- --test-threads=1
python -m pytest tests/transport/test_run_pause.py -k 'cancel or strict_command' -q
python -m pytest tests/temporal/test_run_pause.py -k cancel -q --tb=short
```

- Rust: 1 failed / 1 passed; valid REQUESTED cancellation rejected by the lifecycle
  transition guard.
- Transport: 6 failed / 13 passed; cancellation rejected by the closed schema and
  the strict command-signature test exposed missing `credential`.
- Temporal: 4 failed / 1 passed; transition rejected, cancellation checkpoint
  rejected, and new REQUESTED inherited a previous confirmed timestamp.
- The initial default-Python combined run skipped Temporal due to missing SDK on
  that interpreter's default path; that skip is not treated as RED or GREEN.

Final GREEN commands:

```powershell
cargo build -p slk-state-cli --locked --offline
cargo build -p slk-bi-query --locked --offline
cargo test -p slk-state-core --locked --offline --test write_flow -- --test-threads=1
python -m pytest tests/transport/test_run_pause.py tests/transport/test_supervisor_admin.py tests/temporal/test_run_pause.py tests/temporal/test_contracts.py tests/temporal/test_continuity.py tests/temporal/test_closed_execution_recovery.py tests/temporal/test_runtime_waits.py tests/temporal/test_sdk_contract.py -k 'not real_sdk' -q --tb=short -rs
```

Results: both local builds succeeded; Rust 38 passed; Python 148 passed and 3
deliberately deselected service-starting tests. No skipped tests in the final run.
The builds remove the five earlier missing-CLI skips. Building only `slk-state`
first exposed its test fixture's missing sibling `slk-bi-query`; building the
query binary resolved those setup failures without a source change.

Sealed-consumer tests keep real request/hash/binding validation, RoleHost lifecycle
and retry matching; only DPAPI/process/native boundaries are substituted. They
exercise first Temporal, central, and final Temporal failure/retry, wrong role,
Run, pause, revision, false marker, blank reason, extra fields, original author,
missing REQUESTED, already PAUSED, changed original request, and changed committed
details. Separate real Rust tests prove unchanged TOKEN and another Run; pure
workflow tests prove unchanged pending-operation identity and another Run.

## Actual historical offline SDK replay

Inputs were read only from:
`D:/LCaS/.codex/.tmp/SLK-RUN-LCAS-RC08-IDENTITY-AWARE-MESSAGE-DELIVERY/prepared/maintenance/requested-cancel-entry`.

| History | Events | SHA-256 | Result |
| --- | ---: | --- | --- |
| run-original-history.json | 4776 | 03fe132ad952966b5073864d0d2c1b32c2976ae5a456f8a7848b52d4fa2a826d | REPLAY_PASSED |
| run-after-history.json | 4786 | 1d080dfa24926325e47081dff3973d7432fc9e5cef6dc91cdf06b9e1e45914e6 | REPLAY_PASSED |

For each saved JSON history the repaired repository workflow was passed to:
`await Replayer(workflows=[RunSlkWorkflow]).replay_workflow(WorkflowHistory.from_json('offline-run09', saved_json))`.
No `Client.connect`, activity execution, or server/daemon was used. This verifies
SDK replay compatibility with the two recorded actual histories; it does not
claim online deployment, current Run state, or live restoration acceptance.
