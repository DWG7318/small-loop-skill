# SLK BI / WebBI

The desktop BI and WebBI share this source tree and the same BI product version. Desktop state projection uses the canonical pinned `slk-state-core` dependency. Splitting the repository does not change the UI, read-only state boundary, notification contract or product version.

Desktop BI is the primary surface; WebBI reads only projections uploaded by desktop BI, never Agents or Run databases directly. A desktop display-rule change must include the matching WebBI change in the same product release. Browser/mobile layout may differ without expanding the data scope.

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

## 1.1.6 formal summaries and upload receipts

The existing desktop Settings gear configures the cloud base URL, upload authorization and
stable device ID. `SLK_WEBBI_URL`, `SLK_WEBBI_UPLOAD_TOKEN` and `SLK_BI_DEVICE_ID` retain
precedence; the UI reports the effective source. Windows saves authorization with user-bound
DPAPI, never browser storage. Other platforms without a secure-store adapter explicitly reject
credential persistence. Missing cloud configuration does not prevent local viewing.

Device labels come only from the Agent's optional per-Run `device_signature`; unknown values
are displayed as `未获取`. The stable device ID remains the cloud storage key and is not derived
from an IP address, hostname or operating-system probe.

BI-private metadata lives beside the SLK configuration in `bi-private/`. Pending uploads are
atomic, independently keyed by device and Run, and retried while BI is open (about 30 seconds).
Closing BI stops uploading; reopening resumes pending items. A Run is shown as `云端已保存`
only when its actual cloud receipt matches the complete payload hash and summary source
revision/hash. HTTP 202 alone is not confirmation. A bad or oversize Run cannot block others.

The Markdown adapter reads only the formal `## 结项总结` section, with `记录者` and
`记录时间` metadata followed by a blank line and the original body. The author must match
the registered creator. Optional `电脑名`, `IP地址`, `OS版本` fields belong in `## Run 定义`.
Revisions are generated persistently by BI, never manually entered. Archived source snapshots
remain immutable. A creator can attach a later formal correction using `--bi-summary <run-id>`;
this does not reopen the Run or change D2, archive time or ownership. Native Codex identity
remains supported; absent a trusted host adapter, other platforms remain read-only. Fake-host
tests demonstrate the interface only, not production platform support.

Cloud deployment must apply `webbi/migrations/0002_receipts.sql` before enabling the 1.1.6
receiver. It adds source ordering metadata and makes formal message deduplication Run-scoped.
Deploy the backward-compatible receiver before distributing the new desktop. Local SQLite
and two-device simulations are not evidence of actual two-machine or deployed-cloud testing.
