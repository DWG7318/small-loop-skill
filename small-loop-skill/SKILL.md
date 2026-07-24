---
name: small-loop-skill
description: Use when the user says SLK or small-loop-skill, or when one bounded project needs exactly one visible Worker conversation governed by one visible Control Conversation containing distinct Supervisor and Checker responsibilities. Product-affecting work requires Full or Minimum Calabash. Never trigger together with CLK, GLK, or another loop method.
---

# Small Loop Skill (SLK)

Use `SLK` as the official abbreviation and `$small-loop-skill` as the Codex
invocation name.

## Canonical Identity

- Product name: `Small Loop Skill`.
- Abbreviation: `SLK`.
- Canonical repository: `https://github.com/DWG7318/small-loop-skill`.
- Default branch: `main`.
- Version source: repository `VERSION` file and matching `v*` tag.
- Current specification version: `1.9.0`.

Before publishing, verify owner/name, repository identity, default branch, remote
HEAD, tested installation, version file, and release tag. Never publish SLK content
to the CLK or GLK repository.

## Scope and Topology

SLK executes one bounded project through one persistent Worker and one visible
Control Conversation:

```text
Owner
  ↓
Control Conversation
  ├─ Supervisor responsibility
  └─ Checker responsibility
         ↕
      Worker Conversation
```

The Control Conversation is one Codex conversation, but Supervisor and Checker are
**two non-interchangeable responsibilities**, not one undifferentiated role. Each
formal decision declares exactly one active responsibility mode.

```text
Project → one Worker domain → one or more ordered GO → one CELL at a time
```

SLK has no parallel Chain, Level barrier, Grapher, free GO graph, or separate
Verification conversation. Checker performs CELL validation and GO evidence
acceptance in isolated validation environments. If blind GO verification in a
separate conversation is mandatory, select CLK or GLK before launch.

## Mandatory Calabash Applicability Gate

Before solution, GO/CELL planning, readiness, simulation, or formal execution,
Supervisor responsibility records one of:

```text
PROJECT_CALABASH_BASELINE
CALABASH_EXEMPTION
CALABASH_DEFINITION_BLOCKED
```

### Product-affecting work

Every product-affecting SLK run requires a frozen Full or Minimum Calabash.
Minimum Calabash is:

```text
Grandpa → Product Architecture → Ontology
```

If no baseline exists, Supervisor responsibility derives it from authoritative
Owner statements and project evidence. It may normalize one uniquely supported
meaning, but must not choose between materially different product meanings.
Irreducible Owner-exclusive ambiguity is `CALABASH_DEFINITION_BLOCKED`.

Every product-facing GO records a versioned `GO_CALABASH_TRACE`. Its
`GO_EVIDENCE_CONTRACT` derives from that trace. A contract without a current
Calabash source is invalid.

Minimum Calabash omits Contract, Policy, Workflow, Action Catalog, Adapter, and Eval
& Audit; omission is not permission to ignore them. Before an affected GO executes,
Supervisor responsibility derives and freezes the missing governance artifact when
interfaces, permissions, states, actions, agent translation, safety, or evidence
semantics require it.

### Narrow technical exemption

`CALABASH_EXEMPTION` is allowed only when evidence proves that the complete run:

- changes no user-visible or business behavior;
- changes no product meaning, role, journey, state, permission, action, or product
  acceptance;
- is uniquely specified by a frozen technical contract;
- cannot create a product decision through implementation choice.

The exemption records scope, proof, invalidation triggers, and authority. If any
product effect appears, stop, establish Calabash, revise the plan, and re-simulate.

Read [`references/calabash-and-go-acceptance.md`](references/calabash-and-go-acceptance.md).

## Twenty-Four Hard Rules

1. Select SLK exactly once for one project run; never combine or switch methods
   inside the active run.
2. Use exactly two visible Codex conversations: one Control Conversation and one
   Worker Conversation.
3. Keep Supervisor and Checker as distinct responsibilities inside the Control
   Conversation; every formal decision declares one active mode.
4. Freeze a Full/Minimum Calabash for product-affecting work, or a valid narrow
   `CALABASH_EXEMPTION`, before planning or execution.
5. Use one persistent Worker for the whole bounded project; never create a second
   Worker inside SLK.
6. Execute one CELL at a time. Worker never self-selects the next CELL.
7. Keep all formal roles visible under the same Codex project; hidden agents,
   subagents, background roles, and `delegate_task` are forbidden.
8. Bind Worker implementation, Supervisor control, and Checker validation to
   separate authorized mutable environments.
9. Checker validates an exact immutable candidate in a clean environment; the
   Worker's mutable directory is never sufficient acceptance evidence.
10. Worker is the sole ordinary owner of product implementation and product rework.
11. Checker and Supervisor never edit Worker-owned product artifacts and then accept
    that same edit.
12. Checker responsibility is the sole CELL pass/fail and CELL routing authority.
13. Checker responsibility performs GO evidence acceptance only against a frozen
    Calabash-traced contract in a fresh GO-boundary validation environment.
14. Supervisor responsibility owns method selection, Calabash, plan freeze/revision,
    provisioning, Owner-exclusive escalation, and final composition audit.
15. Routine work inside the frozen `PROJECT_AUTONOMY_ENVELOPE` proceeds without
    Owner confirmation or per-action authorization.
16. Only an irreducible Owner-exclusive objective, product-definition, credential,
    legal, destructive, irreversible, materially costly, physical, or external
    account matter may reach Owner.
17. Every CELL requires Worker evidence and independent Checker reproduction or
    inspection against the same immutable candidate identity.
18. Every GO requires `GO_CALABASH_TRACE`, `GO_EVIDENCE_CONTRACT`, accepted CELLs,
    and a separate GO-boundary acceptance pass before completion.
19. A CELL in one GO may never depend on another GO's unfinished CELL, mutable
    intermediate state, or provisional evidence.
20. Cross-GO input is valid only from an accepted predecessor GO and its frozen
    versioned output.
21. Detection is tiered as `CELL_ALWAYS`, `CELL_TRIGGERED`, `GO_BOUNDARY`, and
    `PROJECT_FINAL`.
22. Plans, receipts, evidence, acceptance records, and historical decisions are
    append-only; only declared current-state indexes are mutable.
23. Silence, timeout, stale green tests, unavailable environments, partial files, or
    a role's confidence never imply acceptance.
24. Completion requires every required GO accepted, composition/safety/evidence
    gates passed, no unresolved defects, and `PROJECT_GOAL` satisfied when
    configured.

Schedule, cost, or Owner urgency cannot waive these rules.

## Method Selection Gate

Use SLK only when all of the following hold:

- one persistent Worker can own the complete bounded write domain;
- required GOs can execute in a coherent serial order;
- no concurrently active independent Worker is needed;
- no fixed parallel Chain/Level structure is needed;
- no conditional branch, partial unlock, cycle, arbitrary GO routing, or Grapher is
  needed;
- Checker GO acceptance without a separate blind Verification conversation is
  acceptable for the risk level.

Use CLK when several fixed Chains can advance through ordered, fully synchronized
Levels. Use GLK when the project requires a free GO graph, Grapher, conditional
routing, joins, fallbacks, cycles, or dynamic path choice.

If SLK becomes invalid, preserve accepted evidence, record
`METHOD_BOUNDARY_EXCEEDED`, stop new formal work, and require a separate run with an
explicit method choice. The active run never converts itself.

## Exclusive Mode Lock

Once SLK is selected:

- invoke SLK exactly once;
- do not load, nest, repeat, alternate with, or switch to CLK or GLK;
- do not borrow their role topologies, Verification conversations, Chain/Level
  barriers, Grapher, or routing state;
- implement shared principles entirely inside the SLK topology;
- preserve historical evidence if method selection later fails.

## Visible Conversation Lifecycle

- Create or unarchive the Control and Worker conversations only when readiness or
  formal work is ready.
- Keep a conversation visible while it owns active work.
- Archive it immediately when no authorized task remains.
- For a same-project continuation, unarchive the same conversation; never create a
  duplicate role.
- A new project requires a fresh Worker conversation and fresh control/evidence
  lineage.
- An archived conversation performs no hidden or background work.

## Dual-Responsibility Control Conversation

Every formal Control Conversation record starts with exactly one:

```text
RESPONSIBILITY_MODE: SUPERVISOR
RESPONSIBILITY_MODE: CHECKER
```

### Supervisor responsibility

Owns:

- Calabash applicability and baseline;
- method selection and frozen objective;
- solution, GO/CELL map, dependencies, and versioned plan revision;
- autonomy envelope and execution provisioning;
- Checker capability and isolated environment provisioning;
- safe pause/resume, safeguard patrol, and genuine blocker resolution;
- Owner-exclusive assistance decision;
- optional `PROJECT_GOAL`;
- final project composition audit and final queue.

It does not issue ordinary CELL verdicts or replace Worker implementation.

### Checker responsibility

Owns:

- packaging and dispatching one authorized CELL at a time;
- immutable candidate intake;
- independent CELL validation and detection receipts;
- CELL routing;
- GO-boundary evidence acceptance;
- local accepted, blocked, or plan-defect records.

It does not change Grandpa, objective, scope, acceptance, or plan silently; contact
Owner; or exercise Supervisor-only authority.

A responsibility transition is immediate in the same Control Conversation and is
recorded. The Control Conversation must never wait for, message, wake, or escalate
to itself.

## Mandatory Readiness Eval

Before simulation or formal dispatch, require three current `25/25` receipts:

```text
SUPERVISOR_RESPONSIBILITY
CHECKER_RESPONSIBILITY
WORKER
```

The first two receipts share the same Control Conversation identity but bind
separate responsibility modes. The Checker receipt also binds its validation
environment template and evidence path. Any skill, Eval, responsibility mode,
conversation, context, model binding, Worker, or environment-binding change makes
the affected receipt stale.

Run:

```text
small-loop-skill/scripts/run_slk_readiness_eval.py
```

Partial credit, manual override, inherited receipts, answer-key inspection during an
attempt, missing answers, extra answers, or reordered answers are forbidden.

## Mandatory Simulation Gate

After current readiness receipts exist, run a no-side-effect simulation. It may read
metadata but must not modify project artifacts, execute implementation, call
external services, or start a formal CELL.

The simulation must rehearse:

1. Calabash baseline or valid exemption;
2. one Supervisor-to-Checker responsibility transition;
3. one formal Worker assignment and immutable delivery identity;
4. one clean Checker validation environment;
5. one successful CELL acceptance;
6. one failed CELL routed as `CELL_REWORK` to Worker;
7. one ordinary uncertainty resolved without Owner confirmation;
8. one GO-boundary evidence acceptance;
9. one cross-GO boundary check;
10. one final composition route without responsibility substitution.

Record `SIMULATION_PASS` or `SIMULATION_FAIL`. Formal work requires a current pass.

## Model Policy

Default bindings:

- Control Conversation: `gpt-5.6-sol` with `xhigh` reasoning;
- Worker: `gpt-5.3 high` through `gpt-5.6-sol high`, selected by risk,
  architecture sensitivity, tool burden, and validation burden.

Supervisor and Checker responsibilities may share one model binding because they
share one conversation. This does not remove the requirement for authority and
environment separation. Record any approved model change before the next formal
act; re-run affected readiness and simulation gates.

## Project Autonomy Envelope

Before formal work, Supervisor freezes `PROJECT_AUTONOMY_ENVELOPE`, including:

- authorized write domains and routine commands;
- local build, test, scan, evidence, and non-destructive Git operations;
- temporary test data, local services, and isolated runtime state;
- resource and cost boundaries;
- forbidden destructive, external, privileged, or security-sensitive actions;
- exact Owner-exclusive categories.

Routine Owner confirmation is forbidden. Worker and Checker never ask Owner to
confirm ordinary implementation, inspect code/logs/tests, choose technically
equivalent options, approve continuation, decide whether to fix a recoverable defect,
or repeat an action available to an authorized role or tool.

Uncertainty does not create Owner authority. Before Owner assistance, exhaust Worker
investigation, Checker reproduction and evidence, Supervisor provisioning/plan
repair/recovery, available documentation/tools, and authorized non-destructive paths.

Only Supervisor responsibility may emit `OWNER_ASSISTANCE_REQUIRED`, containing one
specific Owner-exclusive item, evidence of exclusivity, consequence of no action,
and the safest available choices. A generic confirmation request is
`AUTONOMY_VIOLATION` and returns internally.

## Responsibility and Environment Isolation

Read
[`references/responsibility-and-environment-isolation.md`](references/responsibility-and-environment-isolation.md).

Record before formal work:

```text
CONTROL_CONVERSATION_ID
CONTROL_CONTEXT_ID
CONTROL_MODEL_BINDING_ID
SUPERVISOR_CONTROL_WORKSPACE_ID
WORKER_CONVERSATION_ID
WORKER_CONTEXT_ID
WORKER_WORKSPACE_ID
CHECKER_VALIDATION_ENVIRONMENT_TEMPLATE_ID
CHECKER_EVIDENCE_PATH
```

Worker implements only in its bound workspace. Supervisor uses control artifacts,
not the Worker mutable checkout. Checker validates each exact immutable candidate in
a clean disposable worktree or sandbox and writes separate evidence.

When relevant, separate mutable environment files, database/fixture namespaces,
ports, processes, temp paths, browser profiles, cache-write paths, logs, and generated
artifacts. Read-only/content-addressed caches may be shared.

Because Supervisor and Checker share one conversation, SLK does not claim blind
conversation-memory isolation between them. Its Checker independence consists of
frozen Calabash/contract authority, responsibility separation, immutable candidate
identity, clean environment, and evidence independently reproduced from Worker.

If a separate blind model context is required for GO judgment, SLK is the wrong
method; use CLK or GLK. If the required Checker environment cannot be created, record
`CHECKER_ENVIRONMENT_BLOCKED` and fail closed.

## Worker Contract

Worker:

- remains the one persistent implementation owner;
- accepts only one formal CELL or product-rework round from Checker responsibility;
- works only inside frozen scope and the autonomy envelope;
- preserves unrelated changes;
- records append-only method evidence;
- returns immutable artifact identity, changes, checks, risks, and receipts;
- never self-accepts, selects the next CELL, changes the plan, or contacts Owner.

A formal assignment begins:

```text
Formal task: GO-01/CELL-01.01/R01
```

After delivery, the Worker's final visible reply is exactly:

```text
完成，请检验
```

This means ready for Checker validation, never accepted.

## Checker Validation and Routing

Checker validates the exact immutable candidate in a clean environment. Worker-run
checks are input evidence, not Checker evidence.

Valid CELL routes:

```text
NEXT
CELL_REWORK
GO_ACCEPTANCE
COMPLETE
BLOCKED
PLAN_DEFECT
METHOD_BOUNDARY_EXCEEDED
```

- `NEXT`: current CELL accepted; dispatch the next authorized CELL.
- `CELL_REWORK`: product defect is inside the frozen CELL objective; the same Worker
  receives a new Round.
- `GO_ACCEPTANCE`: all required CELLs are accepted; run the GO evidence contract.
- `COMPLETE`: final GO accepted and project closure gates are ready.
- `BLOCKED`: a required condition or capability is unavailable.
- `PLAN_DEFECT`: objective, scope, dependency, architecture, or acceptance requires a
  versioned Supervisor revision.
- `METHOD_BOUNDARY_EXCEEDED`: the project no longer fits one serial Worker loop.

`REDO` is deprecated for new work because it hides whether Worker rework or plan
revision is required.

Checker may correct only Checker-owned validation harnesses, evidence paths, or
coordination metadata that do not modify the product candidate. It never modifies a
Worker-owned product artifact and accepts its own edit.

## Dispatch-Then-Offline Boundary

Before dispatch, Checker completes every prerequisite, progress snapshot, record,
and formal message. Sending the Worker task is its final action. It enters:

```text
OFFLINE_WAITING_WORKER_SIGNAL
```

and does not poll, inspect, or perform pair work while Worker owns the CELL. Only a
Worker completion, blocker, or execution-failure receipt wakes Checker responsibility.
Supervisor safeguard patrol may inspect control state but does not conduct concurrent
product work or Checker acceptance.

## Continuation Condition Gate

Before every assignment, Checker verifies:

- authoritative inputs and same-GO dependencies;
- predecessor GO acceptance and frozen outputs;
- current allowed/forbidden scope;
- required tools, credentials, environment, and safety gates;
- current Calabash trace and evidence contract;
- action coverage by the autonomy envelope.

A clearly failed prerequisite closes dispatch and records `CONDITION_BLOCKED` with
evidence. Checker sends no filler or speculative task. Supervisor resolves it within
existing authority or emits one precise Owner-exclusive request. Checker revalidates
before resume.

## GO and CELL Design

Use only:

```text
Project → one persistent Worker → ordered GO → CELL → Round
```

A GO is a complete independently acceptable outcome. A CELL is the smallest
inspectable implementation package inside one GO. A Round is one Worker attempt.

Every CELL defines:

- objective and authoritative inputs;
- allowed and forbidden write scope;
- output artifact and immutable identity rule;
- focused checks and broader regression;
- evidence and method-log path;
- same-GO dependencies;
- Worker model binding;
- detection-profile reference;
- completion criteria.

Size CELLs by risk and evidence burden. Reduce CELL size for device capacity; do not
shrink GO meaning or weaken acceptance.

## GO Calabash Trace and Evidence Acceptance

Every product-facing GO defines before simulation:

```text
GO_CALABASH_TRACE
GO_EVIDENCE_CONTRACT
GO_DETECTION_PROFILE
```

The trace identifies baseline ID/version/hash, Grandpa clauses, Product Architecture
journey/module/outcome, Ontology concepts/states, any Full-layer artifacts, derived
GO outcome, and invalidation rule.

The evidence contract identifies:

- outcome claim;
- observable product/system facts;
- required evidence;
- counter-evidence and failure signals;
- pass/fail criteria;
- frozen outputs for later GOs;
- GO-boundary commands/inspection;
- contract and environment identities.

After all required CELLs pass, Checker creates a fresh GO-boundary validation
environment from the exact frozen candidate and returns one:

```text
GO_ACCEPTED
GO_EVIDENCE_GAP
GO_REWORK_REQUIRED
GO_PLAN_DEFECT
GO_BLOCKED
CALABASH_TRACE_INVALID
CALABASH_UPGRADE_REQUIRED
```

Only `GO_ACCEPTED` completes the GO and freezes outputs. A product-effect gap after
technical success returns to Calabash analysis; it never starts unbounded code edits.

## GO Boundary Independence

Forbidden:

```text
GO-A/CELL-x → GO-B/CELL-y
```

Allowed:

```text
GO-A all CELLs accepted
→ GO-A GO_ACCEPTED
→ versioned outputs frozen
→ dependent GO-B becomes READY
```

If a CELL needs another unfinished GO's CELL, mutable state, or provisional evidence,
record `GO_BOUNDARY_VIOLATION` and either merge the coupled work into one GO, finish
the predecessor GO first, or redefine GO boundaries. No affected CELL continues
before revision and delta simulation pass.

## Tiered Detection

Read [`references/checker-detection-catalog.md`](references/checker-detection-catalog.md).

`DETECTION_CAPABILITY_MANIFEST` records what Checker can truly execute. Every
`GO_DETECTION_PROFILE` assigns each capability to exactly one tier:

```text
CELL_ALWAYS
CELL_TRIGGERED
GO_BOUNDARY
PROJECT_FINAL
```

Every allocated capability produces a receipt with version/configuration, trigger,
candidate, environment, result, and evidence. Valid results are `RUN_PASS`,
`RUN_FAIL`, `NOT_TRIGGERED`, and `BLOCKED`. `NOT_TRIGGERED` requires evidence that
the frozen predicate is false. Plain “not applicable,” inherited evidence, or
another role's receipt is invalid.

## Progress Display

Every formal Worker assignment includes one project-wide accepted-CELL line:

```text
正在完成 GO-03：35/231 CELL
```

Assigned, active, unchecked, rework-pending, blocked, revoked, and duplicate attempts
do not count. Supervisor current state also records accepted GOs. Display
`全部完成` only after every required GO is `GO_ACCEPTED`, final composition/safety/
evidence passes, and configured `PROJECT_GOAL` is satisfied.

## Optional Project Goal

Use `PROJECT_GOAL`, never the ambiguous bare term `Goal`.

Owner may explicitly define one versioned project-wide objective with measurable
criteria, required evidence, and safety boundaries. Supervisor must not invent,
broaden, or silently change it. Record `PROJECT_GOAL_SATISFIED` only when every
criterion is proved; otherwise record `PROJECT_GOAL_GAP` and append bounded GO/CELL
continuations under the same Worker when SLK remains valid.

## Append-Only Evidence and Mutable State

Append-only:

- accepted/superseded plans and Calabash baselines;
- GO/CELL files and revisions;
- Worker method logs;
- Checker receipts and GO acceptance records;
- queues, incidents, recovery, and control receipts.

Mutable only when explicitly declared:

```text
WORK_CONTINUATION_INDEX
Control board current-status section
ephemeral progress cache
```

Mutable indexes point to history; they never replace it.

## Markdown Context Boundary

Every governed Markdown file has a hard limit of 1000 physical lines. Keep
`WORK_CONTINUATION_INDEX` below 200 lines. Split at semantic boundaries such as GO,
coherent CELL group, evidence batch, or completed decision. Never delete required
detail or break an evidence chain to meet the limit.

## Evidence Paths

Use project-local paths unless stricter ones exist:

```text
coordination/
  plans/
  checker-messages/
  worker-method-logs/
  checker-evidence/
  queues/
  control-board.md
  work-continuation-index.md
```

Worker and Checker evidence remain separate. Every receipt binds plan/GO/CELL/Round,
contract and artifact identity, responsibility mode, conversation/context/model,
validation environment fingerprint, commands/results, and evidence hash.

## Recovery

- Duplicate Worker: select one authoritative Worker, stop/archive the duplicate, and
  execute each CELL once.
- Lost Worker context: preserve state and use a versioned recovery packet; do not
  silently substitute another Worker inside SLK.
- Worker system error: Checker inspects any immutable usable delivery; if none
  exists, re-dispatch the original CELL as a new Round.
- Contaminated Checker environment: record `CHECKER_ISOLATION_VIOLATION`, discard
  the receipt, and rerun in a clean environment.
- Damaged log: seal it, preserve the incident, create a linked shard, and revalidate
  current artifacts.
- Repeated product defect: issue bounded Worker rework; escalate only a genuine plan
  defect, blocker, or method-boundary failure.
- Silence or timeout: never auto-advance.

## Final Project Composition Audit

Supervisor closes SLK only after:

- every required GO has current `GO_ACCEPTED`;
- all acceptance records bind final artifact/contract identities;
- cross-GO frozen outputs compose correctly;
- `PROJECT_FINAL` checks, safety, and hard brakes pass;
- no unresolved blocker, plan defect, evidence gap, Calabash defect, autonomy or
  isolation violation exists;
- configured `PROJECT_GOAL` is satisfied;
- final handoff, evidence index, and queue exist.

This audit is not a second CELL check and does not replace Checker acceptance.

## Launch Checklist

Before launch, confirm:

- SLK is the sole method and fits one serial Worker domain;
- Full/Minimum Calabash or valid exemption is frozen;
- exact Control/Worker conversations and three `25/25` responsibility receipts;
- current `SIMULATION_PASS`;
- one persistent Worker and one active CELL maximum;
- separate Worker, Supervisor-control, and Checker-validation environments;
- `PROJECT_AUTONOMY_ENVELOPE` covers routine work without Owner confirmation;
- every GO has trace, evidence contract, CELL plan, and tiered detection profile;
- no cross-GO CELL dependency;
- append-only/mutable boundaries, Markdown limits, recovery, and final audit exist.

## Migration From 1.8.3

Version `1.9.0` changes definition grounding, responsibility isolation, product
rework ownership, routes, GO acceptance, and detection execution.

- Active `1.8.3` runs remain bound to `1.8.3` unless formally migrated.
- Do not silently reinterpret historical combined-role, Checker-repair, `REDO`,
  Goal, or acceptance records.
- Migration requires Calabash/exemption, new autonomy envelope, responsibility-mode
  receipts, environment bindings, readiness, simulation, GO traces/contracts, and
  fresh evidence.
- Preserve historical IDs and evidence append-only.
- If unfinished work needs multiple active Workers, blind separate Verification, or
  a GO graph, record `METHOD_BOUNDARY_EXCEEDED` and start a separate CLK or GLK run.

## Version Note

Version `1.9.0` makes Calabash conditionally mandatory, separates Supervisor and
Checker responsibilities inside one Control Conversation, requires Checker
environment isolation, forbids routine Owner confirmation and controller product
self-repair, adds Calabash-traced GO evidence acceptance and GO-boundary independence,
and introduces tiered detection. SLK remains Small Loop Skill with exactly one
Control Conversation and one Worker Conversation.
