# SLK 4.2.5 State Core

SLK uses one configured machine-wide data root for structured Run state, evidence, operational observations, and deterministic Markdown exports. Project repositories remain unchanged. SQLite is authoritative; `SLK-RUN-<RUN-ID>.md` is a regenerated view.

## Interfaces

- `slk-state configure --data-root <absolute>` selects the one data root and initializes its empty versioned database.
- `slk-state init-run --request <json>` initializes a Run, records an explicit predecessor when this is a successor, and returns the Supervisor write credential once.
- `slk-state reconcile-run-identities --request <json>` lets the canonical Run's current Supervisor archive only the explicitly named historical roots after exact snapshot and closed Owner-evidence validation; it appends one immutable reconciliation receipt.
- `slk-state adopt-method-contract --request <json>` supports the declared legacy transitions plus `4.2.2 → 4.2.3 → 4.2.4 → 4.2.5`, preserving `origin_slk_version`, TOKEN and engineering history; each revisioned adoption requires an exact `ABSENT`, hash-verified `PRESERVED_ACTIVE`, or `CONTINUITY_RECOVERY_REQUIRED` Overwatcher assertion.
- `slk-state bind-overwatcher`, `record-overwatch-cycle`, `record-overwatcher-status`, `replace-overwatcher`, `record-observation`, and `close-overwatcher` maintain at most one optional whole-Run Agent Session/foreground turn, revision-bound cycles, native status and explicit continuity transitions. `wait-for-change` is a bounded read in the same process, not a scheduler. Supervisor authorizes binding/replacement; observation commands use the separate `SLK_OVERWATCHER_CREDENTIAL`.
- `slk-state register-role`, `replace-role`, `rebind-session`, `revise-plan`, `write`, `register-evidence`, and `commit-delivery-start` are authenticated mutations. `commit-delivery-start` atomically records verified start evidence, advances TOKEN, appends `TRANSPORT_STARTED`, and stores one runtime snapshot; legacy `handoff` remains only below the revisioned runtime contract. Exact 4.2.4+ Worker event replay is idempotent, while a reused event ID with different content fails closed. `authenticate-role` performs a read-only exact credential/role check and returns only role identity plus current runtime revision. Credentials are supplied only through `SLK_ROLE_CREDENTIAL`.
- `slk-state export --run-id <id>` and `verify-evidence --run-id <id>` require an active role credential.
- `slk-bi-query projects|runs|run|graph|roles|plans|events|evidence` opens SQLite read-only for one invocation. It has no mutation or credential surface.

## Administration payloads

Read each exact `administrative_snapshot` from `slk-bi-query run --run-id <id>` immediately before submission. With the canonical Supervisor credential in `SLK_ROLE_CREDENTIAL`, reconciliation uses:

```json
{"receipt_id":"reconcile-...","canonical_run_id":"RUN-CANONICAL","canonical_snapshot":{"run_id":"RUN-CANONICAL","project_id":"...","slk_version":"4.1.1","state":"active","closure_state":"open","archived_at":null,"superseded_by_run_id":null,"predecessor_run_id":null,"event_count":0,"latest_event_id":"...","token_sequence":10,"token_holder_role_instance_id":"...","role_count":3,"evidence_count":0},"source_snapshots":[{"run_id":"RUN-SOURCE","project_id":"...","slk_version":"4.1.1","state":"active","closure_state":"open","archived_at":null,"superseded_by_run_id":null,"predecessor_run_id":null,"event_count":0,"latest_event_id":"...","token_sequence":1,"token_holder_role_instance_id":"...","role_count":1,"evidence_count":0}],"owner_authorization":{"source_thread_id":"...","message_id":"...","content_sha256":"<64 lowercase hex>","decision":"APPROVE_RUN_IDENTITY_RECONCILIATION","occurred_at":"<RFC3339>"},"reason":"...","occurred_at":"<RFC3339>"}
```

Submit it with `slk-state reconcile-run-identities --request reconcile.json`. Then read a fresh canonical snapshot and use:

```json
{"receipt_id":"adopt-...","run_id":"RUN-CANONICAL","expected_snapshot":{"run_id":"RUN-CANONICAL","project_id":"...","slk_version":"4.2.2","state":"active","closure_state":"open","archived_at":null,"superseded_by_run_id":null,"predecessor_run_id":null,"event_count":0,"latest_event_id":"...","token_sequence":10,"token_holder_role_instance_id":"...","role_count":3,"evidence_count":0},"from_version":"4.2.2","to_version":"4.2.3","owner_authorization":{"source_thread_id":"...","message_id":"...","content_sha256":"<64 lowercase hex>","decision":"APPROVE_METHOD_CONTRACT_ADOPTION","occurred_at":"<RFC3339>"},"reconciliation_receipt_id":null,"compatibility":{"topology":"PRESERVED","role_bindings":"PRESERVED","token":"PRESERVED","engineering_history":"PRESERVED","overwatcher":"ABSENT"},"reason":"...","occurred_at":"<RFC3339>"}
```

Submit it with `slk-state adopt-method-contract --request adopt.json`. Both payloads reject unknown fields, inferred Run discovery, stale snapshots, changed immutable receipt replays, unsupported version paths and missing/mismatched Owner evidence.

Supervisor, Checker, and Worker write only the engineering facts owned by their existing SLK boundaries. A bound Overwatcher can append only its complete eight-part cycle and delivery/activity/recovery/conflict/closure observations; it cannot hand off TOKEN, write D0/D1/D2, change a plan or role, set acceptance, or close the Run. Owner, BI, and other Agents query only. A hash-verified native `started.json` must exist before `commit-delivery-start`; a database row, terminal result, launcher exit, or old message alone never proves delivery.

## State behavior

Every Run has one monotonic TOKEN history, one current plan revision, ordered CELL definitions, complete role-instance history, append-only work events and hashed evidence. Schema v7 additionally stores one monotonically increasing `runtime_revision`; each snapshot binds the exact method/plan/TOKEN/event/message and current Overwatcher identity at one committed instant. A bound Overwatcher is confirmed once for the whole Run, not per CELL; every cycle must match the same binding/session/turn, one runtime revision, 180–300 second cadence, fixed checklist and verified evidence bytes. `LATE` records cadence health but is not `INACTIVE`, and a projected `active` role does not prove new cycles are still occurring. The read-only cadence inspector wakes the same binding after one missed interval and returns more than two intervals to Supervisor review; exact completed/missing/mismatched native evidence still opens the continuity violation. A Run without a binding is unaffected. Normal close requires a terminal Run plus the exact final cycle/revision. The core creates no heartbeat, scheduled task, daemon or background Agent.

Run identity is explicit. A successor names its predecessor; one lineage head is current, predecessors are history, multiple active heads are `DUPLICATE_ACTIVE_RUN`, and unverifiable lineage is `ORPHANED_IDENTITY`. Separately initialized roots become a valid canonical/history set only through a matching immutable reconciliation receipt whose stored pair still agrees with current metadata. Titles, project names, and timestamps never merge Runs. Schema v7 keeps origin/effective versions, administration receipts, transport starts, runtime snapshots, native-status facts, continuity incidents and binding transitions append-only. None rewrites work events, roles, credentials, TOKEN, evidence, CELL state, D0/D1/D2, or plan history. `working` is derived from current accepted evidence, never a stale chat status, TOKEN holder, cadence timer, heartbeat or BI process.

Successful writes attempt to refresh the Markdown export. An export warning does not undo an already committed SQLite fact; rerun `slk-state export` after the output path is available.
