# slk-bi-query

The read-only JSON query command for SLK BI. It consumes the same pinned `slk-state-core` read models as the desktop BI and does not create a second schema or write path.

## Development

From an independent checkout, run `cargo test --locked` and `cargo build --release --locked`. On Windows the binary is `target/release/slk-bi-query.exe`. `slk-bi-query --help` does not open the configured database.

In the SLK parent workspace, run `cargo test -p slk-bi-query --locked`; the parent patches the pinned core dependency to the local canonical subtree. Cross-tool query/state fixtures remain in the parent repository.

## Delivery

Ordinary SLK setup uses a precompiled binary. Managed artifacts record exact build-input hashes, target, toolchain, product version, size and SHA-256; no user configuration or database belongs in the artifact.

The independent repository's first `1.0.0` tag is distinct from the SLK product version declared in Cargo.
