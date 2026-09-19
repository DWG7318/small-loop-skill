# SLK 4.0 State Core

SLK 4.0 uses one configured machine-wide data root for structured Run state, evidence, and deterministic Markdown exports. Project repositories remain unchanged. SQLite is authoritative; `SLK-RUN-<RUN-ID>.md` is a regenerated view.

## Interfaces

- `slk-state configure --data-root <absolute>` selects the one data root.
- `slk-state init-run --request <json>` initializes a Run and returns the Supervisor write credential once.
- `slk-state register-role`, `replace-role`, `rebind-session`, `revise-plan`, `write`, `register-evidence`, and `handoff` are authenticated mutations. `rebind-session` preserves the role instance and credential while retiring the previous endpoint; `replace-role` revokes the replaced identity. The credential is supplied only through `SLK_ROLE_CREDENTIAL`.
- `slk-state export --run-id <id>` and `verify-evidence --run-id <id>` require an active role credential.
- `slk-bi-query projects|runs|run|graph|roles|plans|events|evidence` opens SQLite read-only for one invocation. It has no mutation or credential surface.

Supervisor, Checker, and Worker write only the facts owned by their existing SLK boundaries. Owner, Overwatcher, future BI, and other Agents query only. A successful native `slk-transport` start precedes `slk-state handoff`; a database row alone never proves delivery.

## State behavior

Every Run has one monotonic token history, one current plan revision, ordered GO/CELL definitions, complete role-instance history, append-only work events, and hashed evidence identities. Role replacement revokes the old credential and endpoint without rewriting history. A session rebound appends a new endpoint version. A changed engineering scheme appends a plan revision. A factual correction is a new authored event whose `corrects_event_id` points to the same role instance's earlier event; the original fact remains intact.

`working` is derived only from the latest authored unfinished event, not from a stale chat status, a token owner, or a BI process. Resource contention leaves the same role, TOKEN, CELL, and rework count in place; see the on-demand SLK resource-continuity reference.

Successful writes attempt to refresh the Markdown export. An export warning does not undo an already committed SQLite fact; rerun `slk-state export` after the output path is available.
