# slk-state-core

The canonical Rust state library for Small Loop Skill. This directory owns the SQL migrations, transaction and permission checks, evidence handling, and read models. Dependent tools consume this library; they do not maintain copies of its SQL or rules.

## Development

From an independent checkout, run `cargo test --locked` and `cargo build --release --locked`. The tests use temporary state roots and include the migrations in this directory. No parent repository or running Agent is required.

Within the SLK parent workspace, use `cargo test -p slk-state-core --locked`. The parent patches dependent tools' pinned Git dependency to this same local subtree, so there remains one implementation.

## Delivery and versioning

This is a library, not an extra service or a user-facing executable. Ordinary SLK installation uses the precompiled state/query/Cargo/BI tools. Development artifacts belong in the managed `artifacts` directory with their target, toolchain, build-input hashes, sizes and SHA-256 values; do not archive Cargo caches or user state.

The extracted repository's first tag is `1.0.0`. The crate version is the SLK product version, not that extraction tag: state creation records `CARGO_PKG_VERSION`, so changing it to `1.0.0` would change Run semantics.
