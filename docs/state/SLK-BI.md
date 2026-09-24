# LE BI — SLK 4.2.11 Read-Only View

LE BI presents machine-wide role-authored state plus accepted operational observations. It is a read-only desktop application and does not participate in construction, inspection, transport, recovery, exemption, or closure.

## Data source

The application resolves the same machine-wide `config.json` used by `slk-state` and `slk-bi-query`, then opens the configured SQLite database read-only for every refresh. The database remains authoritative; BI keeps no second state store.

If `SLK_CONFIG_PATH` is not set, the core uses the operating system's local-data SLK configuration path. Tests and isolated environments may set `SLK_CONFIG_PATH` to an explicit configuration file. The configuration contains an absolute data-root path and is created outside BI through the state CLI.

## Read surfaces

The desktop adapter and Agent CLI share these versioned projections:

- `projects`
- `runs [--project-id ID]`
- `run --run-id ID`
- `graph --run-id ID`
- `roles --run-id ID`
- `plans --run-id ID`
- `events --run-id ID`
- `evidence --run-id ID`

Agents use `slk-bi-query`. The desktop uses the same `slk-state-core` functions directly; there is no local HTTP service, MCP server, port, or resident state daemon.

## Refresh and stale data

BI refreshes on window focus and a three-second interval while the window is visible. Hidden windows pause polling. A transient read failure keeps the last successful snapshot visible and labels it stale with the exact error. Missing configuration, an empty data root, an unsupported projection schema, and a read failure have distinct presentation states.

The active surface contains one row per explicit SLK Run identity. Immutable project identity groups independent SLKs into stable quiet colors; `source_kind` and `source_project_name` group CLK/GLK-owned SLKs by parent while retaining explicit labels. Explicit predecessor lineage or a validated reconciliation receipt—not title/project/timestamp similarity—marks `CURRENT`, `HISTORY`, `DUPLICATE_ACTIVE_RUN`, or `ORPHANED_IDENTITY`; conflicts remain visible rather than being guessed away. The Run projection reads one stored runtime snapshot and exposes its revision-bound method/plan/TOKEN/event/message plus the current whole-Run Overwatcher binding, native-status receipts, cycles, incidents and transitions. Expanded details keep Supervisor/Checker/Worker as the three technical role cards and show Overwatcher in a separate compact operational strip whose binding, native liveness and cycle are never collapsed into a synthetic “working” claim. A centrally retired Checker or Worker is immediately projected as archived with no active endpoint; a planned archive is not. Closed, abandoned, and superseded SLKs appear only in the archive.

Refresh is observation only. It does not wake an Agent, acknowledge a token, retry transport, change a Run, or write a heartbeat.

## Display density

Visible text uses one shared 120% scale relative to the original LE BI typography. Icons, native window controls, and segmented progress geometry keep their original dimensions. An active list with zero through five Runs has no vertical scrolling state; six or more Runs use a viewport of approximately five collapsed rows with vertical scrolling. The threshold is the number of active Run identities, so expanding a row does not change whether the list is scrollable. The archive keeps its existing behavior.

## Status language

- `Responsibility: <role>` means the last accepted SLK TOKEN points to that role.
- `Started, not delivered` means the latest authored work fact is unfinished.
- `Candidate delivered` means candidate submission is recorded.
- `Awaiting D2` means D1 PASS is recorded and Run closure remains pending.
- `Run identity conflict` and `Run identity unconfirmed` report duplicate-active or orphaned lineage without guessing a winner.
- `Activity unproved` means an accepted operational observation invalidated a stale activity claim; it does not reduce or increase D1/D2 progress.
- `Closed` means `RUN_CLOSED` is recorded.

These labels describe durable facts. The Overwatcher strip reports central binding, latest native liveness and latest cycle separately. An unresolved incident or late cadence is shown as paused; `TERMINAL_CLOSE` is shown as closed; `COMPLETED`, `MISSING`, or `MISMATCHED` native liveness is never called active merely because the binding remains. BI itself does not keep the Session active, schedule the next cycle, commit TOKEN, repair continuity, or prove native delivery. Exact Agent reality remains bound to immutable evidence, not a BI inference.

## Security boundary

The Tauri application registers only eight read commands plus the minimal native window capabilities required for drag, pin, minimize, close, and dynamic size. It has no role credential input, state write command, shell plugin, HTTP plugin, updater, telemetry, network listener, or remote content. Role endpoint history exposes runtime, provider, model, reasoning, host, session, adapter, version, and lifecycle, but not credentials or native address payloads.

Supervisor, Checker, and Worker author engineering state through their Run-scoped credentials. A bound Overwatcher has a separate credential for append-only operational observations only. No role, including Overwatcher, receives a BI mutation command; Owner, BI, and other Agents remain read-only.

## Build and operation

Frontend checks:

```text
pnpm --dir apps/slk-bi install
pnpm --dir apps/slk-bi test
pnpm --dir apps/slk-bi typecheck
pnpm --dir apps/slk-bi build:ui
```

Desktop development and release builds:

```text
pnpm --dir apps/slk-bi tauri dev
pwsh -NoProfile -NonInteractive -File scripts/build_release_artifacts.ps1 -OutputDirectory <artifact-root> -CargoTargetDirectory <target-root>
```

The release script invokes `tauri build --no-bundle`, requires a `custom-protocol` release fingerprint, and rejects Vite client/source entry markers before packaging. Plain `cargo build --release -p slk-bi-desktop` is not a release path. A deployed cold start must work with no Node, pnpm, Vite, network, or localhost:1430 listener. The accepted binary and evidence are recorded in [`SLK-BI-ACCEPTANCE.md`](SLK-BI-ACCEPTANCE.md).

## Troubleshooting

- **Not configured:** configure the data root with `slk-state`; BI intentionally has no configure action.
- **Unsupported schema:** update BI and do not interpret newer fields using an older frontend.
- **Transient database read:** keep the stale snapshot visible and retry through normal refresh.
- **Missing evidence file:** retain the evidence record and investigate through the owning SLK role; BI does not repair or remove it.
- **A role appears active but may not be working:** treat lifecycle and old work facts as records, inspect native activity evidence, and record `ACTIVITY_UNPROVEN` when appropriate; never infer current work from a heartbeat or visible task alone.

## Future LCaS integration

LCaS rc.08 or rc.09 may mount the React feature components and link the Rust read core as an internal panel. That future host should preserve the same read-only commands and must not turn BI into an Overwatcher or state writer. The current standalone desktop remains independently usable.
