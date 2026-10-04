# LE BI / WebBI 1.1.0 — SLK Read-Only View

LE BI presents machine-wide role-authored state plus accepted operational observations. BI 1.1.0 is versioned independently from the SLK method contract: the desktop and browser share one source version while every Run continues to show its actual SLK version. Neither surface participates in construction, inspection, transport, recovery, exemption, or closure.

## Data source

The desktop resolves the same machine-wide `config.json` used by `slk-state` and `slk-bi-query`, then opens the configured SQLite database read-only for every refresh. Readers explicitly support schema 8 and 9 because migration 0009 changes only OW write constraints, not read columns; other versions fail closed. Reading never migrates the database or changes a Run's method version. WebBI stores only the bounded display projection uploaded by each desktop; that online archive is non-authoritative and never writes back to SLK state.

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

Agents use `slk-bi-query`. The desktop uses the same `slk-state-core` functions directly; there is no local HTTP service, MCP server, port, Node sidecar, or resident state daemon.

## Refresh and stale data

Desktop BI refreshes on window focus and a three-second interval while visible. Its built-in WebBI uploader checks for a changed bounded projection every 30 seconds. WebBI independently refreshes its server view every 30 seconds; neither interval creates an engineering message or unread mark. Hidden browser/desktop views pause their read refresh. A transient desktop read failure keeps the last successful snapshot visible and labels it stale with the exact error.

The active surface contains one row per explicit SLK Run identity. Immutable project identity groups independent SLKs into stable quiet colors; `source_kind` and `source_project_name` group CLK/GLK-owned SLKs by parent while retaining explicit labels. Explicit predecessor lineage or a validated reconciliation receipt—not title/project/timestamp similarity—marks `CURRENT`, `HISTORY`, `DUPLICATE_ACTIVE_RUN`, or `ORPHANED_IDENTITY`; conflicts remain visible rather than being guessed away. The Run projection reads one stored runtime snapshot. Expanded details show Supervisor, Checker, Worker, and a registered Overwatcher as complete identities; the separate Overwatcher operational strip still reports binding/liveness/cycle and never turns them into a synthetic “working” claim. Closed, abandoned, and superseded Runs appear only in the archive and remain stored.

Refresh is observation only. It does not wake an Agent, acknowledge a token, retry transport, change a Run, or write a heartbeat.

## Authoritative message and unread contract

Unread state and ntfy use a closed catalog of existing state-core event and Overwatcher-observation types. The originating Agent authors the exact type under its existing role authority. BI and WebBI validate and project that type; they never classify free text, derive a type from a display status, or write a replacement fact. Unknown types and role/type mismatches fail closed.

Each message identity is the immutable source kind plus source ID. The first view/upload is a silent historical bootstrap. A later unseen source identity creates the green unread mark; opening that Run acknowledges only those displayed identities in local UI storage. Polling, duration changes, repeat uploads, and normal no-change Overwatcher cycles create no mark.

## WebBI archive and upload

Each computer uploads independently to one HTTPS endpoint. The server keys Runs and messages by stable `device_id`; same-named Runs on different devices never overwrite one another. The browser default is `进行中`, with only `已归档` as the other list. There is no device mode and no `全部` mode. Run detail remains within the desktop BI display scope.

Desktop configuration is per computer:

```text
SLK_BI_DEVICE_ID=<stable non-sensitive id>
SLK_BI_DEVICE_NAME=<human-readable name>
SLK_WEBBI_URL=https://slk.lcsp.work
SLK_WEBBI_UPLOAD_TOKEN=<device upload token>
```

All four values are required to enable upload. Missing values leave local BI fully operational and make sync a no-op. The uploader accepts HTTPS (or localhost for development), caps one envelope at 10 MiB, uses a 15-second timeout, sends only messages not yet confirmed during the current process, and safely relies on server deduplication after restart. It does not copy local proxy, path, port, credential, hardware, source, or log data.

Cloudflare deployment uses one Worker, static assets, D1, and Cloudflare Access. Before deployment, replace the D1 placeholder in `apps/slk-bi/wrangler.jsonc`, apply `webbi/migrations/0001.sql`, and set `WEBBI_INGEST_TOKEN`, `WEBBI_ADMIN_TOKEN`, and a base64-encoded 32-byte `WEBBI_SETTINGS_ENCRYPTION_KEY` as Worker secrets. Static/browser access should be protected by Cloudflare Access; API uploads also require the ingest bearer token.

## ntfy notification contract

WebBI stores ntfy server/topic/auth configuration server-side. Secrets are AES-GCM encrypted at rest and are never returned to the browser. Leaving an already stored credential blank preserves it only when the auth mode is unchanged; a new auth mode requires a new credential. The user chooses either all eligible formal message types or exact catalog entries such as `EVENT:D1_FAILED`; broad BI-created categories are invalid.

The first device bootstrap sends no phone notification. Later newly inserted selected messages are delivered once per configuration version/device/message identity. Notification failure is recorded without changing or rejecting the authoritative SLK fact.

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

The Tauri application registers nine read/metadata commands, one bounded outbound WebBI upload command, and the minimal native window capabilities required for drag, pin, minimize, close, and dynamic size. It has no role credential input, SLK state write command, shell/HTTP/updater plugin, telemetry, network listener, or remote UI content. Upload credentials stay in the native process and are not exposed through metadata or projections.

Supervisor, Checker, and Worker author engineering state through their Run-scoped credentials. A bound Overwatcher has a separate credential for append-only operational observations only. No role, including Overwatcher, receives a BI mutation command; Owner, BI, and other Agents remain read-only.

## Build and operation

Frontend checks:

```text
pnpm --dir apps/slk-bi install
pnpm --dir apps/slk-bi test
pnpm --dir apps/slk-bi typecheck
pnpm --dir apps/slk-bi build:ui
```

WebBI local/deployment commands:

```text
pnpm --dir apps/slk-bi build:webbi
pnpm --dir apps/slk-bi dev:webbi
pnpm --dir apps/slk-bi migrate:webbi
pnpm --dir apps/slk-bi deploy:webbi
```

Migration/deployment require an authenticated Cloudflare environment and an actual D1 database ID. They are publication actions, not part of local BI validation.

Desktop development and release builds:

```text
pnpm --dir apps/slk-bi tauri dev
pwsh -NoProfile -NonInteractive -File scripts/build_release_artifacts.ps1 -OutputDirectory <artifact-root> -CargoTargetDirectory <target-root>
```

The release script invokes `tauri build --no-bundle`, requires a `custom-protocol` release fingerprint, and rejects Vite client/source entry markers before packaging. Plain `cargo build --release -p slk-bi-desktop` is not a release path. A deployed cold start must work with no Node, pnpm, Vite, network, or localhost:1430 listener. The accepted binary and evidence are recorded in [`SLK-BI-ACCEPTANCE.md`](SLK-BI-ACCEPTANCE.md).

## Troubleshooting

- **Not configured:** configure the data root with `slk-state`; BI intentionally has no configure action.
- **Unsupported schema:** use the hash-verified installed BI. Schema 8 and 9 cold-start without migration; an unreviewed version still requires the matching reader or a backed-up writer migration before opening. A responsive window alone is not a successful launch: verify the configured Run projections load.
- **Transient database read:** keep the stale snapshot visible and retry through normal refresh.
- **Missing evidence file:** retain the evidence record and investigate through the owning SLK role; BI does not repair or remove it.
- **A role appears active but may not be working:** treat lifecycle and old work facts as records, inspect native activity evidence, and record `ACTIVITY_UNPROVEN` when appropriate; never infer current work from a heartbeat or visible task alone.

## Future LCaS integration

LCaS rc.08 or rc.09 may mount the React feature components and link the Rust read core as an internal panel. That future host should preserve the same read-only commands and must not turn BI into an Overwatcher or state writer. The current standalone desktop remains independently usable.
