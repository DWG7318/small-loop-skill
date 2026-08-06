# Role and Environment Isolation

SLK has exactly two formal engineering conversations: Control and Worker. Control
contains three non-interchangeable responsibility modes. Only one mode is active for
a formal decision. SLK 2.6.0 additionally has exactly one visible Run Patrol
safeguard conversation/heartbeat; Patrol is not a technical role and owns no D0-D3,
product, routing, acceptance, or progress authority.

Worker uses its mutable implementation workspace. Checker evaluates immutable CELL
candidates in a clean D1 environment. Verifier evaluates immutable GO and Run
candidates in fresh D2/D3 environments and issues separate receipts.

Sharing the Control Conversation means these modes are not blind to conversation
history. Independence is established by frozen authority, mode declarations,
immutable candidates, clean environments, and independently reproduced evidence.

SLK 2.6.0 binds each role instance separately in `MODEL_BINDING_TRACE`. Supervisor,
Checker, Verifier, Worker, and Patrol may use the same Terra-class actual model, but
they never share a binding ID or authority. A model or effort switch creates a new
scope-bound version and reruns readiness, isolation, and verification; model
sameness or change never substitutes for candidate/environment separation.

Within one Run, each role retains exactly one stable `role_instance_id` across all
scope bindings and version history; no two roles may share that identity. For the
known GPT reference models, the actual model, reference model, and capability class
must match exactly. Capability-equivalence evidence may substitute only a
non-reference provider/model and cannot relabel Terra, Luna, or Sol.
