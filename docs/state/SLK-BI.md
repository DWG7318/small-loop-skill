# LE BI — SLK 4.0 Read-Only View

LE BI presents the machine-wide state written by the existing Supervisor, Checker, and Worker. It is a read-only desktop application and does not participate in construction, inspection, transport, recovery, exemption, or closure.

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

The active surface contains only SLK rows. `source_kind` and `source_project_name` identify independent, CLK-owned, or GLK-owned SLKs for labeling and quiet color grouping. Expansion contains roles/models and CELL facts only; upper-level Chain and Node logic stays outside BI. Closed, abandoned, and superseded SLKs appear only in the archive.

Refresh is observation only. It does not wake an Agent, acknowledge a token, retry transport, change a Run, or write a heartbeat.

## Status language

- `Responsibility: <role>` means the last accepted SLK TOKEN points to that role.
- `Started, not delivered` means the latest authored work fact is unfinished.
- `Candidate delivered` means candidate submission is recorded.
- `Awaiting D2` means D1 PASS is recorded and Run closure remains pending.
- `Closed` means `RUN_CLOSED` is recorded.

These labels describe durable facts. They do not prove that a process is currently running, a person is watching, or a native message was delivered. Exact Agent reality is confirmed through the existing role communication path, not by BI inference.

## Security boundary

The Tauri application registers only eight read commands plus the minimal native window capabilities required for drag, pin, minimize, close, and dynamic size. It has no role credential input, state write command, shell plugin, HTTP plugin, updater, telemetry, network listener, or remote content. Role endpoint history exposes runtime, provider, model, reasoning, host, session, adapter, version, and lifecycle, but not credentials or native address payloads.

Only Supervisor, Checker, and Worker can author state through their Run-scoped credentials. Owner, Overwatcher, BI, and other Agents are read-only.

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
pnpm --dir apps/slk-bi tauri build --no-bundle
```

Use an external `CARGO_TARGET_DIR` when source-tree build output is undesirable. The accepted binary and complete evidence are recorded in [`SLK-BI-ACCEPTANCE.md`](SLK-BI-ACCEPTANCE.md).

## Troubleshooting

- **Not configured:** configure the data root with `slk-state`; BI intentionally has no configure action.
- **Unsupported schema:** update BI and do not interpret newer fields using an older frontend.
- **Transient database read:** keep the stale snapshot visible and retry through normal refresh.
- **Missing evidence file:** retain the evidence record and investigate through the owning SLK role; BI does not repair or remove it.
- **A role appears active but may not be working:** treat the lifecycle and latest authored fact as records, then use normal Agent communication for reality confirmation.

## Future LCaS integration

LCaS rc.08 or rc.09 may mount the React feature components and link the Rust read core as an internal panel. That future host should preserve the same read-only commands and must not turn BI into an Overwatcher or state writer. The current standalone desktop remains independently usable.
