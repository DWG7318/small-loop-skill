# SLK BI Acceptance

## 4.2.6 production cold-start and display repair

Date: 2026-09-23

Result: PASS for the fresh production artifact before packaging; Owner visually accepted the corrected window.

- Built through `scripts/build_release_artifacts.ps1`, whose BI path is `pnpm tauri build --no-bundle`; ordinary Cargo is not used to produce the desktop artifact.
- The release fingerprint records both `features` and `declared_features` as `["custom-protocol", "default"]`.
- The PE contains the embedded production assets `index-5vxWFpRv.js` and `index-CumzRgVj.css`, and contains neither `@vite/client` nor `/src/main.tsx`.
- Visible typography is uniformly 120% of the original sizes without scaling icons, window controls, or progress segments. Active lists with up to five Runs have no scrollbar; six or more use a five-row internal viewport. The document itself cannot scroll.
- Artifact: `C:\Users\DWG\.codex\.tmp\slk-bi-4.2.6-ui-20260923-1725\artifacts\slk-bi-desktop.exe`.
- Size: `10910208` bytes.
- SHA-256: `87ead858dcf0134e224593d9f4d4b017bf0e068bc88528976a4f564bd2765862`.
- With no process or listener on port 1430, the artifact cold-started as a responsive `LE BI` window and opened no network connection.
- WebView2 Breadcrumbs grew from 4620 to 5037 bytes while the historical `ERR_CONNECTION_REFUSED` count remained exactly 3; the cold start added no new refusal.
- The SQLite database and WAL SHA-256 values were identical before and after the read-only launch.
- The captured window displayed the current LCaS R3B row, SLK 4.2.6, and CELL 3/4 from the configured read-only `D:\SLK-Data` authority. `slk-bi-query` independently returned current run `SLK-RUN-LCAS-RC08-GUI-WINDOWS-STABILITY-R3B`.

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
