# SLK 4.2.2 State Core

SLK uses one configured machine-wide data root for structured Run state, evidence, operational observations, and deterministic Markdown exports. Project repositories remain unchanged. SQLite is authoritative; `SLK-RUN-<RUN-ID>.md` is a regenerated view.

## Interfaces

- `slk-state configure --data-root <absolute>` selects the one data root and initializes its empty versioned database.
- `slk-state init-run --request <json>` initializes a Run, records an explicit predecessor when this is a successor, and returns the Supervisor write credential once.
- `slk-state reconcile-run-identities --request <json>` lets the canonical Run's current Supervisor archive only the explicitly named historical roots after exact snapshot and closed Owner-evidence validation; it appends one immutable reconciliation receipt.
- `slk-state adopt-method-contract --request <json>` explicitly changes an open Run's effective method contract from 4.1.1, 4.2.0, or 4.2.1 to 4.2.2 while preserving `origin_slk_version`; it requires an exact snapshot, closed Owner evidence, no active Overwatcher, and the matching reconciliation receipt when that Run was reconciled.
- `slk-state bind-overwatcher`, `record-overwatch-cycle`, `record-observation`, and `close-overwatcher` bind at most one optional dedicated Agent Session, append complete foreground-cycle facts and closed operational observations, then revoke and archive that binding. Supervisor authorizes the binding; observation commands use the separate `SLK_OVERWATCHER_CREDENTIAL`.
- `slk-state register-role`, `replace-role`, `rebind-session`, `revise-plan`, `write`, `register-evidence`, and `handoff` are authenticated mutations. `rebind-session` preserves the role instance and credential while retiring the previous endpoint; `replace-role` revokes the replaced identity. The credential is supplied only through `SLK_ROLE_CREDENTIAL`.
- `slk-state export --run-id <id>` and `verify-evidence --run-id <id>` require an active role credential.
- `slk-bi-query projects|runs|run|graph|roles|plans|events|evidence` opens SQLite read-only for one invocation. It has no mutation or credential surface.

## Administration payloads

Read each exact `administrative_snapshot` from `slk-bi-query run --run-id <id>` immediately before submission. With the canonical Supervisor credential in `SLK_ROLE_CREDENTIAL`, reconciliation uses:

```json
{"receipt_id":"reconcile-...","canonical_run_id":"RUN-CANONICAL","canonical_snapshot":{"run_id":"RUN-CANONICAL","project_id":"...","slk_version":"4.1.1","state":"active","closure_state":"open","archived_at":null,"superseded_by_run_id":null,"predecessor_run_id":null,"event_count":0,"latest_event_id":"...","token_sequence":10,"token_holder_role_instance_id":"...","role_count":3,"evidence_count":0},"source_snapshots":[{"run_id":"RUN-SOURCE","project_id":"...","slk_version":"4.1.1","state":"active","closure_state":"open","archived_at":null,"superseded_by_run_id":null,"predecessor_run_id":null,"event_count":0,"latest_event_id":"...","token_sequence":1,"token_holder_role_instance_id":"...","role_count":1,"evidence_count":0}],"owner_authorization":{"source_thread_id":"...","message_id":"...","content_sha256":"<64 lowercase hex>","decision":"APPROVE_RUN_IDENTITY_RECONCILIATION","occurred_at":"<RFC3339>"},"reason":"...","occurred_at":"<RFC3339>"}
```

Submit it with `slk-state reconcile-run-identities --request reconcile.json`. Then read a fresh canonical snapshot and use:

```json
{"receipt_id":"adopt-...","run_id":"RUN-CANONICAL","expected_snapshot":{"run_id":"RUN-CANONICAL","project_id":"...","slk_version":"4.1.1","state":"active","closure_state":"open","archived_at":null,"superseded_by_run_id":null,"predecessor_run_id":null,"event_count":0,"latest_event_id":"...","token_sequence":10,"token_holder_role_instance_id":"...","role_count":3,"evidence_count":0},"from_version":"4.1.1","to_version":"4.2.2","owner_authorization":{"source_thread_id":"...","message_id":"...","content_sha256":"<64 lowercase hex>","decision":"APPROVE_METHOD_CONTRACT_ADOPTION","occurred_at":"<RFC3339>"},"reconciliation_receipt_id":"reconcile-...","compatibility":{"topology":"PRESERVED","role_bindings":"PRESERVED","token":"PRESERVED","engineering_history":"PRESERVED","overwatcher":"ABSENT"},"reason":"...","occurred_at":"<RFC3339>"}
```

Submit it with `slk-state adopt-method-contract --request adopt.json`. Both payloads reject unknown fields, inferred Run discovery, stale snapshots, changed immutable receipt replays, unsupported version paths and missing/mismatched Owner evidence.

Supervisor, Checker, and Worker write only the engineering facts owned by their existing SLK boundaries. A bound Overwatcher can append only its complete eight-part cycle and delivery/activity/recovery/conflict/closure observations; it cannot hand off TOKEN, write D0/D1/D2, change a plan or role, set acceptance, or close the Run. Owner, BI, and other Agents query only. A successful native `slk-transport` start precedes `slk-state handoff`; a database row alone never proves delivery.

## State behavior

Every Run has one monotonic token history, one current plan revision, ordered CELL definitions, complete role-instance history, append-only work events, append-only Overwatcher cycles/operational observations, and hashed evidence identities. A bound Overwatcher cycle must match its Session, foreground turn, 180–300 second cadence, current plan/TOKEN/latest event, fixed checklist and native activity evidence. Two missed cycles block a new dispatch or handoff; a Run without a binding is unaffected. The state core validates evidence but creates no heartbeat, scheduled task, daemon or background Agent. The public method hierarchy is `Run → CELL`; the original `go_nodes`/`go_id` fields remain only as a compatibility container.

Run identity is explicit. A successor names its predecessor; one lineage head is current, predecessors are history, multiple active heads are `DUPLICATE_ACTIVE_RUN`, and unverifiable lineage is `ORPHANED_IDENTITY`. Separately initialized roots become a valid canonical/history set only through a matching immutable reconciliation receipt whose stored pair still agrees with current metadata. Titles, project names, and timestamps never merge Runs. Schema v6 keeps origin and effective method versions separate and makes both administrative receipt tables append-only. Neither administration operation rewrites work events, roles, credentials, TOKEN, evidence, CELL state, D0/D1/D2, or plan history. `working` is derived from current accepted evidence, not from a stale chat status, TOKEN owner, heartbeat, or BI process; an accepted `ACTIVITY_UNPROVEN` observation removes the stale working claim without changing progress. Resource contention leaves the same role, TOKEN, CELL, and rework count in place.

Successful writes attempt to refresh the Markdown export. An export warning does not undo an already committed SQLite fact; rerun `slk-state export` after the output path is available.
