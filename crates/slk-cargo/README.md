# slk-cargo

The scoped Cargo execution and cleanup tool for SLK. Existing process ownership, resource classification and protected-path behavior remain in this module; state access uses the single pinned `slk-state-core` implementation.

## Development

From an independent checkout, run `cargo test --locked` and `cargo build --release --locked`. The existing CLI, runner and cleanup contract tests live in `tests`. Windows runner tests require Python available as `python`; they use test-owned processes and temporary paths.

Inside the SLK parent workspace, use `cargo test -p slk-cargo --locked`, with the parent Cargo patch selecting the local canonical core subtree. The Windows binary is `target/release/slk-cargo.exe`.

## Delivery

SLK installs the precompiled tool; it does not compile this tool during ordinary preparation. Managed artifacts carry build-input hashes, target, toolchain, product version, size and SHA-256, not Cargo caches or user projects.

The extracted repository starts with tag `1.0.0`; its Cargo product version remains aligned with SLK rather than being reset by extraction.
