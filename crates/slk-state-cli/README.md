# slk-state

The `slk-state` command-line entry point for authenticated SLK state transactions. Its only state implementation is the pinned `slk-state-core` dependency; SQL, role permissions and transaction rules are not duplicated here.

## Development

From an independent checkout, run `cargo test --locked` and `cargo build --release --locked`. The binary is `target/release/slk-state.exe` on Windows. `slk-state --help` and `slk-state --version` do not require a configured database or role credential.

In the SLK parent workspace, `cargo test -p slk-state-cli --locked` uses the local canonical core subtree via the parent's Cargo patch. Cross-tool method and transport tests remain in the parent repository.

## Authenticated closeout operations

`close-overwatcher --request <path>` selects only `SLK_ROLE_CREDENTIAL` when
`final_cycle_id` is absent/null (creator Supervisor closing the exact ended child),
or only `SLK_OVERWATCHER_CREDENTIAL` when it is present (the final-cycle path).
There is no credential fallback; an empty cycle string is not proof.

`record-closeout-summary --request <path>` uses `SLK_ROLE_CREDENTIAL` and accepts:

```json
{"run_id":"run-a","original_id":"closeout-1","body":"Accepted result; no blockers.","recorded_at":"2026-10-18T00:00:00Z","device_signature":{"computer_name":null,"ip_address":null,"os_version":null}}
```

The creator-Supervisor-only result has `status` (`summary_recorded` or
`summary_replayed`), `run_id`, `original_id`, generated `closeout_summary`, and an
optional `device_signature`. Reuse the exact original ID and content for retries;
use a new ID for corrections. This does not reopen or advance engineering state.
See the core README for immutable evidence and canonical hash semantics.

## Delivery

SLK installs the precompiled binary; the user does not build this project during preparation. Managed artifacts record the build inputs, target, toolchain, product version, size and SHA-256. Preserve credentials, configuration and Run data when replacing a binary.

The independent repository's initial `1.0.0` tag records extraction, not a product-version downgrade. The command and core continue to use the SLK product version.
