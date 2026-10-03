# SLK BI Acceptance

## BI / WebBI 1.1.0 local candidate

Date: 2026-10-04
Result: PASS for the local source candidate; Cloudflare production deployment remains a separate remote action.

- Desktop and browser use the single BI version `1.1.0`; historical Run method versions remain unchanged.
- The closed message catalog exactly matches all current state-core event and operational-observation types. Unknown categories, wrong-role authorship, duplicate identities, excess fields, and unsupported versions fail closed.
- The first snapshot is a silent history bootstrap. Only a later immutable Agent-authored message identity creates a green unread mark or eligible ntfy delivery; polling, elapsed time, repeat upload, and ordinary Overwatcher cycles do not.
- Desktop upload is built into the existing Tauri process, has no Node sidecar or listener, is disabled without all four per-device settings, accepts HTTPS/localhost only, caps an envelope at 10 MiB, and times out after 15 seconds.
- WebBI keeps same-named Runs isolated by device ID, rejects stale snapshot overwrite, defaults to `进行中`, permanently retains terminal Runs under `已归档`, and exposes no top-level `全部` or device mode.
- ntfy secrets remain server-side and are AES-GCM encrypted in D1. The browser receives only `has_secret`; blank reuse is allowed only for the same auth mode, and a new mode requires a new credential.
- Desktop details show a registered Overwatcher as the fourth complete role while retaining the separate non-authoritative operational status strip.

Automated and build evidence:

- Frontend Vitest: 15 files, 57 tests, PASS.
- Strict TypeScript: PASS.
- Vite production build: PASS; development fixtures and Vite client markers absent.
- Rust workspace: 125 tests, PASS, including 4 BI desktop integration tests.
- Full Python suite: 561 passed, 20 skipped.
- Wrangler 4.147.0 dry-run: PASS; static assets and D1/Assets bindings recognized, no deployment performed.
- Real browser layout check: desktop and 390 px phone list/detail/settings, PASS with no horizontal overflow.

Release boundary: `apps/slk-bi/wrangler.jsonc` intentionally retains a deployment placeholder. Creating the D1 database, setting Worker secrets, applying the remote migration, binding `slk.lcsp.work`, and deploying are not claimed by this local acceptance.

## 4.2.6 production cold-start and display repair

Date: 2026-09-23

Result: PASS for the fresh production artifact before packaging; Owner visually accepted the corrected window.

- Built through `scripts/build_release_artifacts.ps1`, whose BI path is `pnpm tauri build --no-bundle`; ordinary Cargo is not used to produce the desktop artifact.
- The release fingerprint records both `features` and `declared_features` as `["custom-protocol", "default"]`.
- The PE contains the embedded production assets `index-5vxWFpRv.js` and `index-CumzRgVj.css`, and contains neither `@vite/client` nor `/src/main.tsx`.
- Visible typography is uniformly 120% of the original sizes without scaling icons, window controls, or progress segments. Active lists with up to five Runs have no scrollbar; six or more use a five-row internal viewport. Independent projects use immutable project identity to select one of eight stable quiet background tones without replacing semantic status colors. The document itself cannot scroll.
- Artifact: `C:\Users\DWG\.codex\.tmp\slk-bi-4.2.6-project-colors-20260923-1810\artifacts\slk-bi-desktop.exe`.
- Size: `10910208` bytes.
- SHA-256: `40e2f988b16ebd205347baa502586e19b904d3ac6c00dc7650b15a41f7312c1e`.
- With no process or listener on port 1430, the artifact cold-started as a responsive `LE BI` window and opened no network connection.
- WebView2 Breadcrumbs grew from 4620 to 5037 bytes while the historical `ERR_CONNECTION_REFUSED` count remained exactly 3; the cold start added no new refusal.
- The SQLite database and WAL SHA-256 values were identical before and after the read-only launch.
- The captured window displayed the current LCaS R3B row, SLK 4.2.6, and CELL 3/4 from the configured read-only `D:\SLK-Data` authority. `slk-bi-query` independently returned current run `SLK-RUN-LCAS-RC08-GUI-WINDOWS-STABILITY-R3B`.
- A separate six-project read-only fixture displayed LCapi, LCvideo, CWd, LCgpu and WXGate simultaneously with distinct quiet tints and exposed the sixth project through the same five-row internal scrollbar.

The final installed-path check is repeated after the hash-bound local package replaces the broken executable. The original 4.0 acceptance remains below as historical evidence.

## 4.0 original acceptance

Date: 2026-09-20  
Result: PASS  
Accepted source commit: `a313eb7f0ccf8fa6829b136ac7ee1d4e42e0b145`

## Scope accepted

- Standalone Tauri 2 / React 19 read-only BI.
- Global project and Run navigation.
- Serial GO/CELL presentation and current SLK TOKEN responsibility.
- Role runtime, provider, model, reasoning, session, replacement, and endpoint history.
- Authored events, correction links, plan revisions, and evidence projection.
- Light, dark, stale, unconfigured, empty, unsupported-schema, and read-error states.
- No write, acknowledgement, dispatch, repair, exemption, credential, shell, HTTP, updater, or telemetry surface.

## Projection and immutability evidence

The accepted two-Run state fixture is:

`D:\SLK\.codex\.tmp\slk-4-state-acceptance\current`

The eight CLI/desktop view families were read for both Runs where applicable, producing 14 projections. Their combined acceptance SHA-256 is:

`a0840473a44aa9ac4c2e5cbd3cc2384d9359eddb513a8da3b8e4e147f47bd115`

The state database SHA-256 before and after all reads was identical:

`639eb609e7f7aa7d2bef85ca8fdb0b1f3d19f9e6a63b66fb7e77b5e927e5330e`

No credential field was present in the accepted projections. Desktop commands and `slk-bi-query` call the same eight `slk-state-core` projection methods.

## Automated checks

- Rust workspace tests: PASS.
- Rust workspace Clippy with `-D warnings`: PASS.
- Frontend DOM/contract tests: 7 files, 11 tests, PASS.
- Frontend strict TypeScript: PASS.
- Frontend production build: PASS; the development acceptance fixture is absent from the production bundle.
- Repository BI read-only contract: 2 tests, PASS.

## Visual checks

The production UI was exercised through the Codex in-app browser using the accepted two-Run fixture:

- default light layout: PASS;
- default dark layout: PASS;
- compact 980×700 layout: PASS;
- compact inspector open and collapsed: PASS;
- TOKEN responsibility, latest factual state, serial GO/CELL ordering, role provenance, endpoint history, and timeline remained readable;
- no overflow obscured the main view after the compact inspector was collapsed;
- focusable controls and named landmarks are covered by the DOM accessibility test;
- reduced-motion behavior is present in the production stylesheet.

## Desktop binary

Built with `tauri build --no-bundle` using an external Cargo target directory:

`D:\SLK\.codex\.tmp\slk-4-bi-release-target\release\slk-bi-desktop.exe`

- Size: `10627072` bytes
- SHA-256: `a83c56b77ebf01f777c69a8a8b393aca192734780493667ffa566c4b2d8536cb`

Machine-readable evidence is stored at:

`D:\SLK\.codex\.tmp\slk-4-bi-acceptance\acceptance-result.json`

## Boundary retained

The BI only displays durable facts. It does not claim current process liveness from an old event, does not confirm message delivery, and does not alter SLK state. Future LCaS rc.08/rc.09 embedding remains outside this acceptance.
