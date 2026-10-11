# slk-state

The `slk-state` command-line entry point for authenticated SLK state transactions. Its only state implementation is the pinned `slk-state-core` dependency; SQL, role permissions and transaction rules are not duplicated here.

## Development

From an independent checkout, run `cargo test --locked` and `cargo build --release --locked`. The binary is `target/release/slk-state.exe` on Windows. `slk-state --help` and `slk-state --version` do not require a configured database or role credential.

In the SLK parent workspace, `cargo test -p slk-state-cli --locked` uses the local canonical core subtree via the parent's Cargo patch. Cross-tool method and transport tests remain in the parent repository.

## Delivery

SLK installs the precompiled binary; the user does not build this project during preparation. Managed artifacts record the build inputs, target, toolchain, product version, size and SHA-256. Preserve credentials, configuration and Run data when replacing a binary.

The independent repository's initial `1.0.0` tag records extraction, not a product-version downgrade. The command and core continue to use the SLK product version.
