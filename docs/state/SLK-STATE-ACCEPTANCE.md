# SLK 4.0 State Core Acceptance

Acceptance date: **2026-09-20**  
Source commit: `f163a121518bda9017bdb672113e35ef1ccfbda0`  
Result: **PASS**

## Toolchain

- `rustc 1.94.0 (4a4ef493e 2026-03-02)`
- `cargo 1.94.0 (85eff7c80 2026-01-15)`
- `Python 3.14.0`
- SQLite migration: `1`
- read projection schema: `slk.bi.run/v1`

## Automated verification

- Rust workspace: **24 passed**, 0 failed across authorization, concurrency, configuration, evidence, export, query, schema, and write-flow suites.
- Writer/query CLI contracts: **4 passed**, 0 failed.
- `cargo fmt --all -- --check`: PASS.
- `cargo clippy --workspace --all-targets --offline -- -D warnings`: PASS.

## Two-Run acceptance

Two independent Runs used one temporary configured data root and executed concurrently. Each Run registered a distinct Supervisor, Checker, and Worker and completed the four-leg `SLK TOKEN` route, Worker D0, Checker D1, Supervisor D2, and `RUN_CLOSED`.

| Fact | Run A | Run B |
| --- | --- | --- |
| Run ID | `run-a` | `run-b` |
| Role count | 3 | 3 |
| Event count | 15 | 15 |
| Supervisor credential SHA-256 | `3bd00b12f744232fa08f26c1394240e199d27009f980fbaa4abd4ccd6ae6d2e2` | `30ee094528d29085912c2e69eeba85dc46245ba85b3812d718dee1eaf34e1464` |
| Current Checker credential SHA-256 | `3d27e6d66e0e0eafc0bba868a92e6d4b8c740cb456b1d7b78e66a8a55e21b719` | `56b6afd16afa39e245ef1d4b2a945c6b5649604da8776b75029ef4c8f6d95947` |
| Worker credential SHA-256 | `9ad3b435649257d2cf4277a4f56056fa9450c627e74a26a547b6ac666680385c` | `bc2c441e74abd3c8ac3713e689dad1ab8e0babdb7eb6fb2563c688d90c6e3321` |
| Deterministic Markdown SHA-256 | `86e6920b4b2c017774786c4954053d7fe799917ef0fb2521863f94bbe4facd1f` | `96ca9501bb56d002ae6b40675870d02228c8c4efb0aba8b9845e1447b5d9e1f7` |

Run A replaced its Checker and preserved the retired identity and endpoint history. Run B rebound the existing Checker to a new session and preserved the role instance and credential. Both Runs appended a correction without rewriting the original event. Both evidence files were copied, hashed, and verified as `present_and_matching`.

A simulated live resource conflict and recovery kept responsibility and the current CELL with the Worker, did not advance the TOKEN, and did not increment D1 rework. A Run A credential attempting to author a Run B event was rejected.

## Read-only surface

With no BI process running, `slk-bi-query` returned `projects`, `runs`, `run`, `graph`, `roles`, `plans`, `events`, and `evidence` for both Runs. The combined canonical query result SHA-256 was:

`52a0b3cf31032783c4978c6e847fb7abcb9b1ff4d0673a78482c029077d7d103`

No query output exposed a credential field. The query executable offers no write, dispatch, approval, exemption, or credential command.

## Immutability and retained evidence

The acceptance wrote only beneath `D:\SLK\.codex\.tmp\slk-4-state-acceptance`; the source worktree was byte-unmodified during both Runs. The machine-readable result remains at:

`D:\SLK\.codex\.tmp\slk-4-state-acceptance\acceptance-result.json`

This accepts the state core and read API. It does not accept the standalone desktop BI, which remains the next serial subsystem.
