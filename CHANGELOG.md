# Changelog

## 1.9.1

- Replaced brittle exact free-text readiness grading with deterministic public
  multiple-choice packets and stable `choice_id` submissions.
- Preserved the 25/25 threshold, hidden answer-key boundary, seeded question order,
  and fail-closed receipt behavior.

## 1.9.0

- Added mandatory Full/Minimum Calabash for product-affecting runs and a narrow
  technical exemption.
- Defined Supervisor and Checker as non-interchangeable responsibilities inside one
  Control Conversation.
- Required independent Checker worktree/sandbox and runtime-state isolation.
- Restored Worker ownership of product rework; deprecated ambiguous `REDO`.
- Added `PROJECT_AUTONOMY_ENVELOPE` and prohibited routine Owner confirmation.
- Added `GO_CALABASH_TRACE`, `GO_EVIDENCE_CONTRACT`, GO-boundary acceptance, and
  cross-GO CELL dependency prohibition.
- Added tiered detection and clarified final composition audit.
- Updated method boundaries to Chain Loop Skill (CLK) and Graph Loop Skill (GLK).
