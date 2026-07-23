# SLK Control Operations

## Manual start

`SLK START` authorizes the frozen method, Calabash/exemption, one Worker, ordered GO
plan, autonomy envelope, isolated environment bindings, and first CELL preparation.
It does not request Owner approval for every CELL, GO, rework, or validation.

## Responsibility transition

Every transition inside the Control Conversation records old/new
`RESPONSIBILITY_MODE`, reason, authoritative inputs, and expected next action. The
conversation never sends a message to itself or waits for itself.

## Dispatch

Checker validates continuation conditions, writes the formal task as its final
online action, and enters `OFFLINE_WAITING_WORKER_SIGNAL`. Supervisor safeguard
patrol does not run Checker acceptance concurrently.

## Rework

A product defect inside the frozen CELL objective routes `CELL_REWORK` to the same
Worker with a new Round. A change to objective, scope, architecture, dependency, or
acceptance routes `PLAN_DEFECT` to Supervisor mode for versioned revision and delta
simulation.

## GO boundary

After all CELLs pass, Checker creates a fresh isolated GO-boundary environment,
executes `GO_EVIDENCE_CONTRACT`, records a signed acceptance result, and freezes
outputs only after `GO_ACCEPTED`.

## Safe pause and resume

Pause only at a safe CELL or GO-acceptance boundary. A pause is not acceptance.
Supervisor records `RESUME_AUTHORIZED`; Checker revalidates all conditions before
new dispatch. Routine resume needs no Owner authorization.

## Safeguard patrol

Supervisor may inspect control state, repair provisioning/authorization, prepare a
versioned plan correction, and restore progress. It must not implement Worker work,
issue a CELL/GO verdict, or ask Owner for routine confirmation.

## Owner assistance

Only Supervisor may emit `OWNER_ASSISTANCE_REQUIRED` for one proven Owner-exclusive
item. Generic confirmation is `AUTONOMY_VIOLATION`.

## Control receipts

Every control action records an idempotent receipt with Calabash/plan version,
responsibility mode, GO/CELL/Round, role/environment IDs, old/new state, evidence,
and result.
