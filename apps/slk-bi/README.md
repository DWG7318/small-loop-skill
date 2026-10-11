# SLK BI / WebBI

The desktop BI and WebBI share this source tree and the same BI product version. Desktop state projection uses the canonical pinned `slk-state-core` dependency. Splitting the repository does not change the UI, read-only state boundary, notification contract or product version.

## Development

Use the Node/pnpm version recorded by `package.json` and `pnpm-lock.yaml`. From an independent checkout:

```powershell
pnpm install --frozen-lockfile
pnpm test
pnpm typecheck
pnpm build:ui
cargo test --manifest-path src-tauri/Cargo.toml --locked
pnpm tauri build --no-bundle
```

The desktop build requires the usual Windows Rust/Tauri development environment. The resulting binary is `src-tauri/target/release/slk-bi-desktop.exe` in an independent checkout; the parent workspace uses its shared `target/release` directory. The parent patches the pinned core Git dependency to the same local subtree.

## Delivery

Ordinary SLK installation opens the precompiled desktop BI without a compiler, npm installation or frontend build. Desktop binaries and the built WebBI belong in managed `artifacts` with exact build inputs, target/toolchain, BI version, sizes and SHA-256 values. Do not archive `node_modules`, Cargo caches, credentials or user state.

The independent repository's initial `1.0.0` tag records extraction. It does not reset the shared BI/WebBI product version.
