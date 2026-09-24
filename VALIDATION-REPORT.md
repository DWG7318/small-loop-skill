# Validation Report — SLK 4.2.8 Candidate

Date: 2026-09-24

Branch: `feature/slk-4.2.8-overwatcher-credential-rotation`

Base candidate: `61f7e7756234773603666ed2d780ef80e6fe7e39`

## Scope

SLK 4.2.8 is a narrow recovery patch over 4.2.7. It adds one Supervisor-authenticated action for rotating the write credential of the exact current ACTIVE Overwatcher binding when the one-time secret was lost or the caller mistakenly stored the non-secret credential ID. The action preserves role, Session, foreground turn, binding revision, TOKEN, engineering history, continuity, CELL/D0/D1/D2 and BI authority; it advances only the runtime revision and stores one append-only audit receipt.

Bind, replace and rotate responses now distinguish `overwatcher_credential_id` from the one-time `overwatcher_write_credential` and label delivery `ONE_TIME_NON_REPLAYABLE`. The old secret and the credential ID both fail authentication, rotation replay fails closed, and exact Supervisor/binding/runtime/role/Session/turn/current-credential/evidence mismatches are rejected.

Schema v8 adds only the append-only rotation receipt table. Rotation metadata is not exposed through general Run projection or LE BI. A stranded 4.2.7 Run may rotate under its current contract, authenticate the returned write secret, record a valid cycle for the same binding, and then adopt 4.2.8 with `PRESERVED_ACTIVE`; the rotation never invents continuity evidence.

## Evidence

- TDD RED reproduced the absent rotation request/action/CLI/table and the ambiguous output field names before implementation.
- Focused exact-binding positive, wrong-authority/stale-identity/replay negative, CLI secret-vs-ID and append-only schema tests: PASS.
- Rust workspace: 100 integration tests passed; unit and documentation test targets passed.
- Python full suite: 282 passed.
- Python optimized-mode suite: 282 passed; the expected pytest warning notes that Python assertions are disabled under `-O`.
- LE BI: 21 tests passed; TypeScript typecheck passed. No BI projection exposes credential identifiers.
- Role Eval case pack: 62 cases, PASS; SHA-256 `42891fc04f147e6bf89f13007e11eabf5cf2a28541c247e34942bc7d80ffd79e`.
- Repository validator, closed JSON contract parsing, schema-v8 migration/backup checks and root/install packaging tests: PASS.
- Windows helper/runtime guidance continues to require hidden/no-window execution; no visible PowerShell, cmd or helper console is introduced.

## Boundaries

No LCaS/R3B product file, Run state, candidate, CELL, D2, model policy, Docker component, remote branch, tag or Release is changed. The patch adds no role, heartbeat, scheduler, daemon, workflow engine, BoM route, automatic recovery or BI write path. Local installation replaces only the hash-closed SLK package; the Supervisor remains responsible for any later explicit R3B rotation and method adoption.
