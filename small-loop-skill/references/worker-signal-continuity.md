# Worker Signal Continuity

## Purpose

The fixed two-conversation topology requires a durable control-plane handoff. A
Worker can finish correctly while Control has not yet ingested the terminal signal;
that state is `COMPLETED_UNREAD`, not silence and not permission to redispatch.

## Signal stream

Every formal CELL dispatch creates one `dispatch_id` and one ordered stream bound to
the Run, persistent Worker conversation, GO, CELL, Round, and formal task.

Allowed event types are:

```text
ACK → zero or more PROGRESS → exactly one BLOCKED or FINAL
```

- `ACK` proves the bound Worker received the task.
- `PROGRESS` is informative and never grants acceptance.
- `BLOCKED` carries one required route and wakes Control.
- `FINAL` carries an immutable Candidate or an explicit no-Candidate route and
  wakes Control.

Events use contiguous sequence numbers and unique IDs/hashes. Nothing may follow a
terminal event. Replayed events are deduplicated by signal identity.

## Control states

```text
OFFLINE_WAITING_WORKER_SIGNAL
ACTIVE_WORKER_ACKNOWLEDGED
BLOCKED_UNREAD
COMPLETED_UNREAD
BLOCKED_INGESTED
FINAL_INGESTED
CONTROL_DISCONNECTED
```

`OFFLINE_WAITING_WORKER_SIGNAL` forbids Control-side product pair work and blind
polling. The platform or orchestration layer maintains the wake subscription.
`BLOCKED` and `FINAL` wake Control; `PROGRESS` does not change formal authority.

## No duplicate Worker or dispatch

Missing commentary, elapsed time, a stale sidebar title, unavailable UI state, or
an unread terminal signal never proves non-delivery. Redispatch is allowed only
after a delivery receipt proves `TASK_NOT_DELIVERED_PROVEN`. Redispatch always uses
the same persistent Worker and records its authority. `COMPLETED_UNREAD` and
`BLOCKED_UNREAD` are hard duplicate-dispatch brakes.

## Atomic ingestion

Control consumes a terminal signal exactly once and records one
`CONTROL_SIGNAL_INGESTION` receipt. The transaction authenticates bindings and
signal identity, selects the permitted route, updates Run status and visible
progress, and emits one Owner-visible status. Partial synchronization leaves the
terminal signal unread; it never silently advances progress.

## Disconnect recovery

Thread-not-found, unknown-conversation, IPC failure, or app-server disconnect sets
`CONTROL_DISCONNECTED`. Recovery rebinds the original Control and Worker, then
authenticates the dispatch and latest durable signal. It never provisions a second
Worker or reruns accepted work merely because the UI stalled.

Validate a completed or in-flight stream with:

```text
python scripts/validate_worker_signal_stream.py <stream.yaml|json>
```
