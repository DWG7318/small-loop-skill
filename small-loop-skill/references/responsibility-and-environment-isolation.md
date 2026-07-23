# SLK Responsibility and Environment Isolation

## One conversation, two responsibilities

SLK intentionally uses one Control Conversation containing Supervisor and Checker
responsibilities. This preserves compact coordination, but the responsibilities are
not interchangeable.

Every formal record declares one active mode. Supervisor mode owns definition,
planning, provisioning, Owner-exclusive escalation, and final audit. Checker mode
owns CELL validation/routing and GO evidence acceptance.

The Control Conversation never waits for itself. A mode transition is immediate and
recorded.

## Isolation model

A separate title is not isolation. Record:

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

For each CELL receipt also record immutable candidate, contract, Round, validation
environment, environment fingerprint, commands, results, and evidence hash.

## Worker environment

Worker owns the only mutable product implementation workspace. It cannot write
Supervisor control or Checker validation artifacts except through formal receipts.

## Supervisor environment

Supervisor owns plans, Calabash baseline, autonomy envelope, control board, and
coordination state. It does not perform ordinary product implementation in the
Worker checkout.

## Checker environment

Checker validates an immutable commit/tree/archive hash in a clean disposable
worktree or sandbox. It never accepts by looking only at Worker mutable state.

Separate when relevant:

- environment files and secrets scope;
- database/schema/fixture namespace;
- service ports and processes;
- temp directories and browser profiles;
- cache-write paths;
- logs, generated files, and evidence directories.

Read-only/content-addressed caches may be shared. Mutable success markers may not.

## Cognitive-isolation limit

Because Supervisor and Checker share a conversation and model context, SLK does not
claim blind cognitive independence between them. It compensates with frozen
Calabash authority, explicit responsibility modes, immutable candidates, clean
runtime environments, and independent reproduction from Worker.

A project requiring a separate blind GO-verdict context belongs in CLK or GLK.

## Violations

```text
CHECKER_ENVIRONMENT_BLOCKED
CHECKER_ISOLATION_VIOLATION
CANDIDATE_IDENTITY_MISMATCH
RESPONSIBILITY_SUBSTITUTION
```

Any violation invalidates the affected receipt. Fail closed and rerun from a clean,
correctly bound environment.
