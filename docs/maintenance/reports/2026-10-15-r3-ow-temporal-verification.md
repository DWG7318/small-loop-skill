# R3 OW/Temporal investigation and terminal-race verification

Scope: source-only work in `C:/Users/DWG/.config/superpowers/worktrees/SLK/bi-113-run09-repair`.
No live Run invocation/write, notification, native agent invocation, service start,
deployment, Docker, Computer Use, or 3.x change was performed. The completed Run09
Temporal pair was not queried live or reopened.

## Separate findings

1. **Existing identity rejection is necessary.**
   `standard_adapter.inspect_overwatcher` passes one fresh central projection to
   the original native inspector before cadence inspection. The transport's
   `validate_subagent_overwatcher_binding` requires the current exact role,
   parent/child Session, endpoint and foreground execution. Configuration-only
   proof/start-pointer replacement does not update that central execution.
   Neither validator nor adapter was changed.
2. **A terminal race is independently reproduced and repaired.**
   `close_run` can terminate continuity while `_inspect_overwatcher` is awaiting
   its Activity. Previously the returned failure/anomaly could still create a
   fresh notice, followed by pending-notice retries and an overdue residency
   notice. A close during one notice could also start the next notice.
   This is a code-level isolated reproduction, **not a finding that this race
   caused Run09 audit83**.

## Field evidence and limits

Read-only evidence root:
`D:/LCaS/.codex/.tmp/SLK-RUN-LCAS-RC08-IDENTITY-AWARE-MESSAGE-DELIVERY/prepared`.

- `temporal-cell03-worker.stderr.log` lines 883/924/1009/1094 name audit80–83.
  Their tracebacks reach adapter line489: native inspection with
  `--runtime-projection`, before the cadence call. The log does not preserve
  those audits' temporary projection or exact subprocess stderr, so it does not
  prove which native validator condition failed on each individual audit.
- `cell03-execution-record.md:225` explicitly records replacing only the
  Temporal adapter's current OW started/proof/hash pointers after native
  followup. This is evidence of the operating seam, not proof that no other
  central operation ever occurred.
- The saved `overwatcher-native/resume-cell03-checkpoint-20261015T045549Z/`
  `subagent-overwatcher-proof.json` identifies new execution
  `codex-subagent-followup:call_657bfb1be5164381aba4909069509559`, previous execution
  `codex-subagent-followup:call_cd7b9d7694cd46de9c0998d0d4efc07b`, checked at
  `2026-10-15T04:59:47.482444Z`, and started SHA-256
  `1c6f71bf631a08bab6a669e5e3c7e7add0ae292c7f65cf03d4b5ea4e975f1467`.
  Do not invent an intermediate central resume or rewrite the native chain.
- The earlier investigation's saved notification projections (including the
  reported old central execution and later retired endpoint) are not the
  missing audit-input snapshot. They cannot alone establish the exact cause of
  audit82/83 or classify audit83 as a newly scheduled versus late notice.
- The report's exact-pair close receipt remains the original operating remedy
  for a Run whose background monitoring is no longer authorized. Central
  administrative closure and role archival remain separate facts.

## Minimal repair

Only `integrations/temporal/src/slk_temporal/workflows.py` changes production
behavior. The existing runtime-check entry points recheck this Run's terminal
continuity after awaited audit/notice work and before scheduling further work.
The marker `slk-run-close-stops-runtime-checks` preserves recorded old commands
when absent during replay. There is no new timer, monitor, schema, identity
relaxation, or global alert filter.

Already attempted audits remain counted. Already attempted notifications retain
their genuine success/failure result. Unattempted pending notices and existing
guards remain in history; closing does not manufacture delivery or repair.
Another Run continues to audit and notify normally.

## Verification

Environment: existing `C:/Python314/python.exe`; Temporal SDK loaded from
`C:/Users/DWG/.codex/tools/slk/runtime/python/Lib/site-packages` via `PYTHONPATH`.
No dependency installation was needed.

RED, before production changes:

```powershell
python -m pytest tests/temporal/test_terminal_runtime_checks.py -q --tb=short
```

Result: **6 failed, 1 passed**. Failures show actual extra notification calls
after terminal close; the legacy-branch counterexample passes.

GREEN:

```powershell
python -m pytest tests/temporal/test_terminal_runtime_checks.py tests/temporal/test_runtime_waits.py tests/temporal/test_451_runtime_truth.py tests/temporal/test_standard_adapter.py tests/temporal/test_contracts.py tests/temporal/test_continuity.py tests/temporal/test_closed_execution_recovery.py tests/temporal/test_sdk_contract.py -q --tb=short
```

Result: **148 passed**. One existing collection warning is emitted because the
imported OW integration-fixture module uses `pytest.mark.asyncio` and this
interpreter has no pytest-asyncio plugin. No async-marked/service-starting test
is claimed executed by this result.

Additional targeted run including the pure OW integration cases and pause tests:
**96 passed, 4 service tests deliberately deselected**, same collection warning.
Tests cover CLEAR/anomaly/error returns after close, two isolated Run objects,
notice success/failure after close, preserved old notices, and the absent-marker
legacy command sequence. They do not start an actual Temporal test service.

Actual offline SDK replay of both saved Run09 histories passed using
`Replayer(workflows=[RunSlkWorkflow]).replay_workflow(WorkflowHistory.from_json(...))`:

| Original saved file | Events | Last event UTC | SHA-256 |
| --- | ---: | --- | --- |
| `maintenance/requested-cancel-entry/run-original-history.json` | 4776 | 2026-10-14 16:29:13.617533600Z | `03fe132ad952966b5073864d0d2c1b32c2976ae5a456f8a7848b52d4fa2a826d` |
| `maintenance/requested-cancel-entry/run-after-history.json` | 4786 | 2026-10-14 16:44:57.667351800Z | `1d080dfa24926325e47081dff3973d7432fc9e5cef6dc91cdf06b9e1e45914e6` |

These histories predate audit74–83 and do not contain the newly reproduced
terminal race. Replay proves compatibility with those original histories;
the explicit absent-marker unit branch proves the retained old command path.
No online rollout or all-R3-root-causes-fixed claim is made.

## Existing original resume path (guidance, not a Run09 mutation)

Use the existing sealed `supervisor-admin resume-overwatcher-turn`, not a new
helper. For native OW, the actual Rust consumer requires current active
role/Session/binding, exact prior foreground, latest positively COMPLETED native
status receipt, and fresh runtime revision; the new active evidence stays
hash-bound. UNKNOWN, MISSING, MISMATCHED or an anomaly cycle is not completion.
After the accepted central operation, read back the current foreground and
require agreement with the new proof before publishing those adapter references.
Do not repair an already-retired binding this way or guess missing intermediate
activation history. Failure leaves the unresolved guard/evidence visible.

Existing real consumer tests:
`slk_450_current_execution_projection_tracks_each_run_without_changing_other_role_shapes`,
`slk_450_resume_requires_positive_completed_not_missing_or_mismatched`, and
`slk_450_anomaly_cycle_cannot_prove_the_old_execution_has_completed` in
`crates/slk-state-core/tests/overwatcher.rs`; exact native projection negatives in
`tests/transport/test_overwatcher_subagent.py`. These names identify the proper
consumer boundary; they are not counted as newly executed Rust tests here.
