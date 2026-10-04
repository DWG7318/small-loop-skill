# Validation Report — SLK 4.4.0 Candidate

WebBI public-read correction (2026-10-04, branch `fix/bi-schema-cold-start`): Owner explicitly approved anonymous read-only viewing. The previous public API read tests were RED (401 instead of 200); the write-only authorization UI/API tests were RED before implementation. Focused 26/26 and complete frontend 78/78 tests pass, and the production TypeScript/Vite build passes; Python full suite remains 616 passed, 2 skipped, with 30/30 repository/package/BI focused tests. Uploads retain ingest authorization; settings-save/test retain separate admin authorization. Public settings redact secrets, arbitrary email/JWT headers grant no writes, and management authorization stays in page memory. No dependency, account/login system, token rotation, database migration or method-version change is introduced. This correction does not replace GitHub release assets.

Cloudflare Worker `slk-webbi` deployment `ad934196-02c0-4f4e-b22c-1ffeeb257f0c` serves the correction at `https://slk.lcsp.work`. The two mistakenly added Access apps for this exact host/upload path were removed; shared account organization/identity-provider settings and all existing Worker secrets were left untouched. Extra workers.dev/preview routes are disabled. Anonymous active/archive/catalog/redacted-settings and historical Run-detail API checks return 200 (0 active, 10 archived); unauthenticated settings PUT, test POST and upload POST return 401 even with a forged email header. Existing admin/ingest credentials reach validation and reject empty invalid payloads with 400, without changing notification configuration version 0 or sending ntfy messages. The real existing browser displays archive rows, historical detail and settings without login or read errors; saving without management authorization is blocked locally. Diff/static-bundle secret-value scan and `git diff --check` pass. Screenshot evidence: `D:/LCcoding/.codex/.tmp/webbi-public-read-20261004/webbi-public-archive.jpg`.

Local post-release BI correction (2026-10-04, branch `fix/bi-schema-cold-start`): explicit read-only schema-8/9 compatibility, accurate source schema version, and three new regression tests. The genuine v8 cold-start test was RED before the fix. Rust workspace 135 passed; package/install tests 6 passed; production build/fingerprint and 99-file local install passed. Three installed-path cold starts read all ten historical Run details, with no STALE/read error in the captured view and unchanged database/configuration hashes. This correction remains local and does not replace published v4.4.0 assets or alter Run method versions. Evidence: `docs/state/SLK-BI-ACCEPTANCE.md`.

Date: 2026-10-04

Branch: `feature/slk-4.4.0-runtime-webbi`

Method: `4.4.0`

BI/WebBI: `1.1.0`

## Candidate boundary

This candidate keeps the serial CELL/D0/D1/D2 method and its three engineering roles. It adds one required non-authoritative Overwatcher, required Temporal continuity/timing, four-role readiness, seven exact direct-communication rehearsals, Checker PASS continuation, bounded native receipts, one-shot Worker completion handling, and round-bound Supervisor rework investigation. It does not add BoM, D3, another engineering authority, heartbeat, background Agent, Docker installation, or product-Run mutation.

Normal communication remains member-owned: initial Supervisor→Checker; ordinary Checker→Worker→Checker; formal D1 FAIL Checker→Supervisor→same Worker→Checker; final D2 readiness Checker→Supervisor. OW only cross-checks truth and reports `ANOMALY`/`UNKNOWN` to Supervisor. Temporal only persists continuity/timing and blocks next dispatch when its runtime guard is unresolved.

## Implemented gates

- `slk-run-readiness/v1` requires exactly Supervisor, Worker, Checker and Overwatcher; BI 1.1.0 visibility; current tool/capability receipts; device/capacity facts; shared Temporal and per-Run workflow readiness; and seven scope-bound send/start/response rehearsals.
- DSH/OCRV publish compact atomic native activity and terminal execution receipts with bounded retry and retained last-good evidence. Bulk output remains local by path, size and SHA-256.
- Checker accepts only current exact D1 PASS and routes only the next Required CELL or final `D2_READY`. Worker continuation is one-shot; terminal-without-result becomes `WORKER_INCOMPLETE`/`NATIVE_TURN_ORPHANED`.
- OW uses one distinct per-Run binding and exact 600-second foreground cycles. One exact Session may serve several Runs only with matching native identity/model/endpoint/cadence facts and separate Run scope. It continues after reporting; only Supervisor may stop it, and every exit raises a confirmable guard.
- One shared headless Temporal service may host many Runs; each Run has its own `SLK.Start`/`SLK.Run`, original-sender recovery, 30-minute member-residency notice, 20-minute OW audit, guard resolution and independent closure.
- The second formal D1 FAIL for the same CELL requires `investigation_mode=AGGRESSIVE`; round one requires `STANDARD`. Checker retains D1 authority.
- BI/WebBI 1.1.0 retains read-only engineering semantics, four-role/device/version display, Agent-authored unread types, per-device Run upload/archive, and ntfy server URL/username/password/topic configuration without exposing the stored password.

## Verification evidence

- `python -m pytest -q` → **616 passed, 2 skipped**. The skips are real-service Temporal SDK scenarios because this machine does not have the optional SDK environment provisioned; core import remains dependency-light, while 4.4 Run readiness still fails closed without a ready service/worker.
- `python -O -m pytest -q tests/transport tests/temporal tests/eval` → **456 passed, 2 skipped**; negative contracts stay fail-closed with assertions optimized out.
- `cargo test --workspace` → **132 passed, 0 failed** across state/schema/migration/OW/BI query/Cargo guard/desktop command suites and doctests.
- `pnpm test` in `apps/slk-bi` → **61 passed**; `pnpm typecheck` and `pnpm build:webbi` → PASS.
- `python scripts/validate_repository.py` → PASS after final Manifest regeneration.
- Sandbox drill uses the rebuilt 4.4.0 `slk-state` binary and passes without product paths.

## Operational limits

No Docker or system dependency was installed. No remote push, merge, tag, Release, product Run reopening, or live LCaS/OCRV/DSH deployment was performed. Real Temporal service admission and real four-Agent communication rehearsal remain per-Run readiness duties, not claims inferred from unit tests.
