# SLK 3.0.2 Loop Engineering Identity Design

## 1. Problem

SLK 3.0.1 clarified that members do not stay online to watch one another, but it still allowed the platform's message lifecycle to be mistaken for the method itself. A project therefore described SLK as "message-woken round execution" and treated a receipt such as `已收到` as the end of the Worker's construction activity.

That interpretation reverses the authority order. Conversation activation is a transport mechanism. The engineering Loop is the method.

## 2. Canonical identity

SLK is the linear form of Loop Engineering for a small or medium engineering scope, or a relatively independent small or medium scope inside a larger project.

One SLK owns one Run. Its GO and CELL path is linear. The Run advances through a repeated engineering feedback Loop:

```text
Checker dispatches CELL
        ↓
Worker implements + minimum D0
        ↓
Worker delivers immutable candidate
        ↓
Checker performs isolated D1
        ├─ FAIL → same CELL rework Loop
        └─ PASS → next planned CELL
                         ↓
             all CELLs resolved → Supervisor D2 → Run result
```

The CELL feedback Loop is repeated along the linear path. D2 closes the complete Run after the planned CELL outcomes have been handled.

## 3. Roles serve the Loop

- Worker owns the construction node and minimum D0.
- Checker owns CELL dispatch, isolated D1, PASS routing, and focused rework routing.
- Supervisor owns startup understanding, exceptional assistance, exemptions, and final D2 boundaries.

These responsibilities are not conversation-presence states. A sleeping, idle, active, or reactivated task does not by itself advance, pause, pass, fail, or close a CELL.

## 4. Communication semantics

Messages transport Loop work and Loop results; they are not the Loop.

- A receipt confirms that a message reached the intended member.
- A receipt does not finish the recipient's assigned Loop node. In particular, a Worker may acknowledge a CELL and continue its construction activity.
- Checker ends its current activity after dispatch because its dispatch node is complete. It resumes D1 only when the Worker candidate is delivered through a real activation.
- Worker ends its current construction activity after delivering the candidate or handing back a concrete condition requiring another member's action; acknowledging receipt alone is not that boundary.
- Members do not watch peer construction state or use `wait_threads` as a substitute for the next real handoff.

Communication recovery exists only to restore a failed handoff. It does not create an alternative engineering state machine.

## 5. Change boundary

The 3.0.2 patch will:

1. put Loop Engineering identity first in the SLK main Skill;
2. describe the CELL feedback Loop and Run-level D2 closure;
3. clarify receipt versus completion in the smallest directly affected child Skills;
4. replace ambiguous wording instead of adding another control layer;
5. preserve the current roles, D0/D1/D2 ownership, linear topology, record model, communication recovery, and child-Skill set;
6. preserve or reduce existing Skill line counts.

The patch will not add Patrol, online monitoring, a new role, a new inspection layer, or a message-round state machine.

## 6. Verification

Repository tests will mechanically prove that:

- SLK identifies itself as a linear Loop Engineering form;
- the canonical dispatch/execute/D0/D1/PASS-or-rework/D2 Loop is present;
- receipt is not construction completion;
- Checker does not watch Worker construction;
- `wait_threads` is not used as Loop execution;
- all existing role and inspection ownership remains unchanged;
- Skill line counts do not grow.
