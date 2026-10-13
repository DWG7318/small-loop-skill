# Small Loop Skill (SLK)

Current source version: **4.5.2**. See the [452 changes](CHANGELOG.md) and [validation evidence](VALIDATION-REPORT.md). Installation is confirmed by the target machine's installation receipt, not this version label. Existing Run identities and their historical method versions are not relabeled.

SLK is the linear form of Loop Engineering for one bounded small or medium Run, or one relatively independent scope inside a larger project. One SLK is one Run with one serial CELL path.

## Core

```text
Supervisor → Checker → Worker → Checker
                       FAIL → Supervisor → same Worker → Checker
                 final PASS → Supervisor D2

Overwatcher: required Supervisor subagent, truth observation → its parent only
Temporal: required continuity/timing guard; never engineering authority
```

Before any CELL, Supervisor opens the prebuilt BI 1.1.1 and uses `preflight-basic` to confirm the installed SLK, DSH/OCRV, Skills, tools, state, shared Temporal and exact role identities/endpoints. Each member receives a short role brief and role eval; required direct communication is checked without simulating a full engineering Run. Existing strict conformance drills remain developer/regression tools, not an ordinary startup dependency. Missing components use prepared installation/repair recipes, with unfamiliar problems decided by Supervisor. Ten-minute checks and twenty-minute preparation are efficiency aims, never deadlines or failure gates. Ordinary users call prepared products rather than compiling or rebuilding dependencies.

Codex is Supervisor using canonical `gpt-6.1-sol`; Owner freezes `high` or `xhigh` per Run. OCRV is Checker (Qwen3.8-Max); DSH is Worker (DeepSeek V4 Flash). Runtime, model, reasoning, Session, adapter, endpoint and native activity are validated rather than inferred from prompts. Supervisor sizes the frozen engineering solution for DSH: oversized work is pre-split into independently D0/D1-checkable small or medium CELLs without changing acceptance. Most CELLs should pass D1 first try; a second consecutive formal D1 failure requires more serious Supervisor investigation and consideration of smaller versioned successor CELLs (Skill guidance, not an output veto), while Checker retains D1 authority.

Overwatcher is mandatory: each Supervisor owns one native child subagent, registered for every Run that Supervisor manages. A fast, lower-reasoning model is recommended, not hard-coded. It observes actual cross-evidence facts every 600 seconds and reports `ANOMALY` or `UNKNOWN` only to its parent. It never relays normal work, retries delivery, edits BI/TOKEN, judges D0/D1/D2, or repairs a member. Removing one Run does not stop observation of the others. Only its Supervisor may stop it; every exit still requires Supervisor confirmation. Native parent/child identity and an actual current execution—not a tool's acceptance alone—prove activation.

Temporal is one shared headless local service for multiple Runs. Each Run has an independent `SLK.Start` and `SLK.Run`: exact native-start acknowledgement, original-sender recovery, a 30-minute member-residency notice to Supervisor, a 20-minute Overwatcher audit, and a per-Run closure. It never decides engineering state or replaces direct role communication. SLK does not install Docker; unavailable or failed required continuity remains blocked until Supervisor repairs it.

Supervisor stays active through its project, using bounded native waits without taking over ordinary Worker/Checker work. It must not exit and expect its own OW child to wake it. Worker/Checker still stop engineering before their final verified handoff. Owner stop and actual platform interruptions remain authoritative; the method does not promise a child survives its parent's exit.

Run planning keeps tests, review and acceptance inside D0, D1 and D2 rather than creating inspection-only CELLs. Evidence shortage stays unproved, not PASS. RTK, Probe CLI and Ponytail remain optional efficiency aids with native fallbacks and raw evidence retention.

Cross-Agent delivery uses `slk-transport` with immutable endpoints, envelopes, candidate/evidence hashes, sealed role credentials and `slk.native-start/v2`. DSH and OCRV publish compact, atomic native activity plus terminal execution receipts; bulk logs remain local by path/hash. Startup/RPC timeouts protect short calls but never become a death line for engineering after a verified native start. Normal OCRV aggregate budget and review timeout are native `0` (unlimited); historical line/file/background/context estimates remain advisory, while the verified template tool-round default is reported honestly rather than called unlimited. An exact D1 INCOMPLETE moves through `D1_INCOMPLETE_ESCALATION` to Supervisor management without fabricating FAIL/rework/acceptance; non-wait actions return the unchanged candidate to the original Checker as `D1_MANAGEMENT_RETURN` under the normal profile, while old finite-budget evidence and consumed markers remain immutable. Reports are saved and delivered without body-format, length, severity or coverage pre-review. DSH explicitly submits its own D0/candidate actions; original OCRV explicitly calls slk_checker_decide and its existing handoff, never a host-derived verdict. Output delivery and engineering actions are separate. Checker completion can route only the exact next Required CELL or final `D2_READY`. See [`docs/transport/SLK-TRANSPORT.md`](docs/transport/SLK-TRANSPORT.md).

## State and BI

SLK uses a versioned SQLite authority, durable evidence, deterministic Markdown exports and read-only LE BI. BI/WebBI 1.1.1 shows device/version, four-role identity, exact Agent-authored unread messages and archived Runs; the desktop shell stays opaque, renders a visible failure boundary, and rejects an accidental second instance. WebBI accepts independent per-device Run uploads and optional ntfy delivery configured by server URL, username, password and topic; BI/WebBI never infer message types or modify engineering state. See [`docs/state/SLK-STATE.md`](docs/state/SLK-STATE.md) and [`docs/state/SLK-BI.md`](docs/state/SLK-BI.md).

## Skill collection

Install the complete sibling collection under [`skills/`](skills/), using the package inventory rather than a fixed Skill count. The [main Skill](skills/small-loop-skill/SKILL.md) routes to focused guides for planning, role understanding/team preparation, member replacement/archive, Temporal, OW, pause/resume, CELL work, records, recovery and closure. Preparation troubleshooting and construction troubleshooting are separate optional entrances, not new mandatory stages. These guides form one method and are not standalone methods.

## Validation

```text
python scripts/validate_repository.py
python -m pytest -q
```

For Windows machine setup, follow [`docs/runtime/SLK-WINDOWS-RUNTIME.md`](docs/runtime/SLK-WINDOWS-RUNTIME.md). The v3.0.8 tag preserves the prompt-only method and v2.6.0 preserves the earlier monolith.

## License

MIT.
