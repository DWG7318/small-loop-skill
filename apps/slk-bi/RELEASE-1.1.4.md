# BI / WebBI 1.1.4

- Universal desktop source reading: existing state DB plus 3.x Markdown workbooks; method version is not an admission whitelist. Desktop still owns reading/uploading; WebBI only consumes that upload.
- Creator-bound registration and archive receipts for closed registered workbooks. No engineering-source writes, invented PASS, arbitrary Supervisor takeover or public archive action. Existing state-DB Runs retain their original method close authority.
- Per-source failure isolation; missing model/timing fields stay unprovided; explicit native CELL IDs and split counts are preserved. View-only unread revisions do not invent ntfy message types.
- Persistent cloud archive cannot be undone by stale active uploads. Existing BI 1.1.0–1.1.3 producers remain compatible.
- Preserve 1.1.3 layout, scrolling, 10×3 CELL display limit, newest-first detail, background transparency and notification settings.

## Verification

- Frontend: 230 tests; typecheck and production assets built, including missing/mixed-unknown progress.
- Independent Git-pinned core: 17 Rust desktop/read/identity tests, without parent workspace patches.
- Actual SQLite persistence test: archived A stays archived after old/new-envelope stale retries; same Run ID on device B stays independent.
- Precompiled Windows binary: version 1.1.4, no Vite development markers, source-free CLI register/read/archive and quoted-argument capture passed; the synthetic source bytes remain unchanged.
- Real read-only T13 workbook: 3.0.9, 3 members, 22/22 CELLs, CLOSED; no fabricated OW/events. No T13 files were changed or re-opened.
- Hosted WebBI served 1.1.4 at `slk.lcsp.work` after deployment; actual run acceptance and human GUI review are not claimed by these headless checks.

See `UNIVERSAL-SOURCES.md` for commands and identity trust boundary. The Run09 method-level close-census repair remains outside this release (4.5.4); no 4.5.4 method code is changed here. The compiled desktop and WebBI assets are in `artifacts/windows-x86_64/payload.zip`, indexed by `ARTIFACTS.json`.
