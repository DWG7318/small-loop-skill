# BI 1.1.3 / SLK 4.5.2 build.3 delivery

Owner authorized merge, GitHub push, precompiled delivery, local upgrade and obsolete-code cleanup on 2026-10-15. SLK 3.1.0 and its project installation remain deferred. The method identity remains 4.5.2; the new build tag distinguishes the Run09 repairs without relabeling existing Runs.

## Plan

- Complete: verify and archive the current compiled BI and repaired modules; publish exact independent module refs and refresh the parent mapping.
- Active: merge both scopes to main, verify the merged tree, push and read back GitHub refs.
- Pending: assemble and verify a complete precompiled offline package; install locally using the existing transactional installer.
- Pending: verify installed bytes and source-free commands; retire obsolete managed code while preserving data, credentials, active project 3.x and one rollback.

## Boundaries

- No end-user compilation, Docker, new engineering Run, or provider calls.
- No Computer Use; native headless checks are not visual acceptance.
- No Cloudflare deployment in this local-install request. WebBI source and compiled assets follow BI 1.1.3 in Git; the hosted site is not silently changed.
- Preserve independent review/test evidence in [implementation results](reports/2026-10-15-bi113-run09-implementation-result.md). Historical audit 83's exact cause remains unproven.
- Installed receipts and actual hashes, not a version string, establish deployment.

## Results

Build-time status: all eight changed module main branches and new immutable tags
were pushed and read back. Both product scopes are assembled in this source tree.
The final application batch passes sealed provenance; all seven consumer archives
were restored and checked. Independent consumers resolve exact core
`fbf74df77d2283de6a72541eec829ccb59375955` without the parent workspace patch.

Fresh seven-runtime input audit passed 28,356 files / 989,594,724 bytes. Native
OCRV stays `1.12.13-slkprobe.1.0.1`; its adapters are updated. The old local
installation contained ten generated Python cache files and stale BI/transport
build provenance. The transactional replacement is intended to remove those
code-only inconsistencies, without touching Run databases or identities.

Fresh delivery tests: Rust 198, frontend 221 plus typecheck, release-executable
integration 97, repository/build/artifact/standalone-Python/BI delivery tests 54.
The latter initially exposed one obsolete test expecting transparency presets;
it now verifies the approved 0–100 range, 1% step and absence of the old selector.
Runtime UI behavior already has 40 dedicated tests; no production change was
made for this stale assertion.

This file is frozen before installation so the offline package remains hash-bound.
Actual package, merge/push, installation and cleanup receipts are recorded after
execution under `D:/LCcoding/.codex/.tmp/bi113-build3/`. A consumer must use the
target installation receipt rather than treating this build-time plan as proof.
