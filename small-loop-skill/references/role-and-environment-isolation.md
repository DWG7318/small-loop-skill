# Role and Environment Isolation

SLK has exactly two formal engineering conversations: Control and Worker. Control
contains three non-interchangeable responsibility modes. Only one mode is active for
a formal decision. SLK 2.5.0 additionally has exactly one visible Run Patrol
safeguard conversation/heartbeat; Patrol is not a technical role and owns no D0-D3,
product, routing, acceptance, or progress authority.

Worker uses its mutable implementation workspace. Checker evaluates immutable CELL
candidates in a clean D1 environment. Verifier evaluates immutable GO and Run
candidates in fresh D2/D3 environments and issues separate receipts.

Sharing the Control Conversation means these modes are not blind to conversation
history. Independence is established by frozen authority, mode declarations,
immutable candidates, clean environments, and independently reproduced evidence.
