# Small Loop Skill (SLK)

Current version: **4.4.2**

SLK is the linear form of Loop Engineering for one bounded small or medium Run, or one relatively independent scope inside a larger project. One SLK is one Run with one serial CELL path.

## Core

```text
Supervisor → Checker → Worker → Checker
                       FAIL → Supervisor → same Worker → Checker
                 final PASS → Supervisor D2

Overwatcher: required, non-authoritative truth observation → Supervisor only
Temporal: required continuity/timing guard; never engineering authority
```

Before any CELL, Supervisor opens BI 1.1.0, establishes the four-role `RUN_TEAM_REGISTRY`, proves current tools/capabilities and device readiness, and binds a real isolated source produced by seven exact communication rehearsals. To create the first source, only a disposable one-CELL Run with a `slk-conformance/<SLK-CONFORMANCE-…>` evidence root and a separate clean, fixed-HEAD, no-remote sample Git may use `preflight-conformance-sample`; it can never dispatch product work. Temporal then uses the built-in two-stage standard adapter: central bootstrap creates the deterministic pair once, and explicit sample or product admission—after its real identity/Host/OW evidence exists—opens delivery. Product Runs always use `preflight-new-run` with a distinct sealed source. Missing, stale, guessed, circular or unqueryable evidence blocks dispatch.

Codex is Supervisor using canonical `gpt-6.1-sol`; Owner freezes `high` or `xhigh` per Run. OCRV is Checker (Qwen3.8-Max); DSH is Worker (DeepSeek V4 Flash). Runtime, model, reasoning, Session, adapter, endpoint and native activity are validated rather than inferred from prompts. Supervisor sizes the frozen engineering solution for DSH: oversized work is pre-split into independently D0/D1-checkable small or medium CELLs without changing acceptance. Most CELLs should pass D1 first try; a second consecutive formal D1 failure stops ordinary rework and requires versioned split/replan of the unaccepted remainder, while Checker retains D1 authority.

Overwatcher is mandatory and observes actual cross-evidence facts every 600 seconds. It never relays normal work, retries delivery, edits BI/TOKEN, judges D0/D1/D2, or repairs a member. It reports `ANOMALY` or `UNKNOWN` only to the exact registered Supervisor and continues observing. One Run has one distinct Overwatcher role binding; one exact active Session may serve multiple Runs only when all native identity/model/endpoint/cadence facts match and every Run remains separately scoped. Only Supervisor may stop it, and every exit triggers a Supervisor-confirmed runtime guard before another CELL may dispatch.

Temporal is one shared headless local service for multiple Runs. Each Run has an independent `SLK.Start` and `SLK.Run`: exact native-start acknowledgement, original-sender recovery, a 30-minute member-residency notice to Supervisor, a 20-minute Overwatcher audit, and a per-Run closure. It never decides engineering state or replaces direct role communication. SLK does not install Docker; unavailable or failed required continuity remains blocked until Supervisor repairs it.

Run planning keeps D0, D1 and D2 as the existing inspection layers. Evidence shortage stays unproved, not PASS. RTK, Probe CLI and Ponytail remain optional efficiency aids with native fallbacks and raw evidence retention.

Cross-Agent delivery uses `slk-transport` with immutable endpoints, envelopes, candidate/evidence hashes, sealed role credentials and `slk.native-start/v2`. DSH and OCRV publish compact, atomic native activity plus terminal execution receipts; bulk logs remain local by path/hash. Startup/RPC timeouts protect short calls but never become a death line for engineering after a verified native start. Normal OCRV aggregate budget and review timeout are native `0` (unlimited); historical line/file/background/context estimates remain advisory, while the verified template tool-round default is reported honestly rather than called unlimited. An exact D1 INCOMPLETE now moves through `D1_INCOMPLETE_ESCALATION` to Supervisor capacity/environment management without fabricating FAIL, rework or D1 acceptance; old finite-budget attempts retain their narrow Owner-authorized recovery lineage. Checker completion can route only the exact next Required CELL or final `D2_READY`. See [`docs/transport/SLK-TRANSPORT.md`](docs/transport/SLK-TRANSPORT.md).

## State and BI

SLK uses a versioned SQLite authority, durable evidence, deterministic Markdown exports and read-only LE BI. BI/WebBI 1.1.0 shows device/version, four-role identity, exact Agent-authored unread messages and archived Runs; the desktop shell stays opaque, renders a visible failure boundary, and rejects an accidental second instance. WebBI accepts independent per-device Run uploads and optional ntfy delivery configured by server URL, username, password and topic; BI/WebBI never infer message types or modify engineering state. See [`docs/state/SLK-STATE.md`](docs/state/SLK-STATE.md) and [`docs/state/SLK-BI.md`](docs/state/SLK-BI.md).

## Skill collection

Install all 16 sibling directories under [`skills/`](skills/): [`skills/small-loop-skill/SKILL.md`](skills/small-loop-skill/SKILL.md) is the main router and 15 focused companion Skills cover planning, capacity, models, role Eval/team readiness, Temporal, Overwatcher observation, CELL execution/checking/rework, records, adjustment, recovery and closure. They are one method collection, not standalone methods.

## Validation

```text
python scripts/validate_repository.py
python -m pytest -q
```

For Windows machine setup, follow [`docs/runtime/SLK-WINDOWS-RUNTIME.md`](docs/runtime/SLK-WINDOWS-RUNTIME.md). The v3.0.8 tag preserves the prompt-only method and v2.6.0 preserves the earlier monolith.

## License

MIT.
