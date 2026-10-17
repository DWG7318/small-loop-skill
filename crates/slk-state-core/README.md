# slk-state-core

The canonical Rust state library for Small Loop Skill. This directory owns the SQL migrations, transaction and permission checks, evidence handling, and read models. Dependent tools consume this library; they do not maintain copies of its SQL or rules.

## Development

From an independent checkout, run `cargo test --locked` and `cargo build --release --locked`. The tests use temporary state roots and include the migrations in this directory. No parent repository or running Agent is required.

Within the SLK parent workspace, use `cargo test -p slk-state-core --locked`. The parent patches dependent tools' pinned Git dependency to this same local subtree, so there remains one implementation.

## Closeout summary evidence

`StateStore::record_closeout_summary` accepts `run_id`, a stable `original_id`,
`body`, RFC3339 `recorded_at`, and optional `device_signature` with nullable
`computer_name`, `ip_address`, and `os_version`. The authenticated, currently
registered creator Supervisor is the only writer. The caller cannot choose the
author, source identity, revision or hash. Each original is immutable evidence of
type `run_closeout_summary`; the generic evidence operation rejects that type.

The tool derives `source_id` from the Run and original ID and allocates a
monotonic per-Run `source_revision` in the evidence transaction. The same ID and
content (including device signature) replays; conflicting content is rejected.
Corrections use a new original ID. The unchanged latest content submitted under
a different request ID returns the existing canonical original ID without
creating or reserving another source. Summary writes never advance engineering
events, plan/runtime revisions, TOKEN, D2 or archival facts, including on closed
Runs. No arbitrary body-length cap is imposed.

The optional Run projection `closeout_summary` contains `body`, `authored_by`,
`recorded_at`, `source_id`, `source_revision`, and `content_sha256`.
`device_signature` is a separate optional field. The summary hash is SHA-256 of
compact UTF-8 JSON in exactly that first-five-field order (excluding the hash and
device signature). The evidence file hash protects the entire original, including
device signature. Readers verify the registered original before exposing either
field; a missing/corrupt latest original is omitted without falling back to an
older conclusion. Raw logs are not included in this projection.

## Role capability policy

Effective 4.5.5 Runs record actual runtime/provider/model metadata without brand
allowlists; reasoning may be empty when the platform does not expose a setting.
Known adapter capabilities and independent exact endpoints are still required;
original admission must prove the native operations actually work. Unknown
adapters are not supported merely by registration. Historical Run contracts
remain frozen until separately authorized adoption. The Overwatcher remains the
registered Supervisor's direct child.

## Delivery and versioning

This is a library, not an extra service or a user-facing executable. Ordinary SLK installation uses the precompiled state/query/Cargo/BI tools. Development artifacts belong in the managed `artifacts` directory with their target, toolchain, build-input hashes, sizes and SHA-256 values; do not archive Cargo caches or user state.

The extracted repository's first tag is `1.0.0`. The crate version is the SLK product version, not that extraction tag: state creation records `CARGO_PKG_VERSION`, so changing it to `1.0.0` would change Run semantics.
