# Validation Reports

Current maintenance implementation: [SLK 3.1.1 verification](docs/3.1.1-verification.md). This records local test-first evidence and explicitly separates pending independent behavior/BI integration acceptance. Earlier reports below remain historical evidence, not a 3.1.1 live-Run claim.

## Historical validation — SLK 3.0.9

Date: 2026-10-14

## Source and delivery boundary

- Exact baseline: `v3.0.8` / `870b0e517c7a1cd9b2592e9e4a9115b54a312160`.
- Independent branch: `maintenance/3.0.9`; do not merge this maintenance line into 4.x main.
- Still 13 Skills / 15 Skill payload files; no OW, daemon, runtime, database, timers or transport component.
- Project-scoped adoption only where Owner authorizes it. Preserve global 4.x, other active Runs, original project records and provenance.
- This report uses generic method scenarios only; private project source, original logs and retrospectives are not repository payloads.

## Changes tied to demonstrated problems

| Problem | Minimum correction | Preserved boundary |
|---|---|---|
| Delivered node ends at ACK/read/partial implementation | Supervisor stays active; native waits, compact facts, onsite same-node recovery | No duplicate CELL, token takeover or artificial D1 failure |
| Candidate-preceding incomplete work/capacity termination | Capability/resource review before a candidate; distinguish requested vs effective model | Owner choices and authorization scope; no universal retry threshold |
| Multiple stale current headings | One current summary with timestamp/author; retain prior states as history | Existing shared Markdown, no extra service or per-command audit |
| D0/self-evaluation enters initial D1 input | Reinforce original clean handoff, retain complete objective target/scope | Checker independent D1; full D0 remains available after initial judgment |
| Platform effects appear only at final integration | Minimal affected-platform compile/lint planning | No full D2 per CELL or inspection-only CELL |
| Necessary private bridge missing from planned paths | Precise callchain/visibility/entrypoint reading before dispatch | Existing engineering authority, no blanket permission expansion |

## Before/after behavior exercises

The unmodified baseline passed repository validation and 61 tests before editing. A separate read-only agent exercised the old protocol. It could infer original-node recovery from general rules but expressly declined continued observation under the old main Skill; candidate-preceding recovery, actual model effectiveness and unique-current-summary treatment were not explicit. Its platform plan covered the Linux consumer but omitted the shared declaration's other-platform compile boundary. Clean D1 input already worked and is reinforced, not presented as a new architecture.

A fresh independent agent then used only the revised local collection:

| Scenario | Observed decision |
|---|---|
| ACK-only then read-only completed turn | Recover current original token/node, remain online; do not record D1 FAIL |
| Useful partial edits plus capacity termination | Preserve edits; distinguish resource vs capability; no fabricated candidate |
| Old model active, replacement request queued | Record request only; wait for actual new-turn configuration; honor remaining-Run authorization |
| Peer requests D0 PASS and focus hints in delivery | Omit judgment; keep original target/scope and objective candidate facts |
| Repaired D2_READY beside stale historical headings | Update the single current summary; keep earlier failure/input history |
| Shared declaration and private writer bridge | Include necessary paths and affected Windows/Linux checks, not full preflight |
| Long active test with no new output | Native waiting/compact observation; no forced retry or failure threshold |
| Late token after CLOSED | Keep closure; no pointer rollback or reopened construction |

These are reasoning simulations, not live platform or product acceptance. The actual evaluator model/reasoning metadata was unavailable and is not guessed.

## Independent consistency review

The reviewer found two recovery ambiguities; both were corrected and rechecked:

1. Checker and Supervisor could both retry the same failed handoff before a turn became active. The existing actors now select one recovery sender; handing recovery to Supervisor ends the original sender's retries, with existing sent/queued messages reconciled first.
2. A Supervisor stopped during observation owns no engineering token. The original conversation now restores observation without replaying a historical token or taking the Worker's current token; actual Supervisor-owned adjustment/D2 recovery remains separate.

The recheck found no remaining concrete logic defect in these cases. This does not prove that every future agent will comply.

## Local verification

- `python -X utf8 scripts/validate_repository.py`: PASS.
- `python -X utf8 scripts/quick_validate.py skills`: 13/13 PASS.
- Skill Creator `quick_validate.py`: 13/13 PASS.
- `python -X utf8 -m pytest -q`: 61 passed.
- `git diff --check`: PASS.
- Existing static wording assertions were updated only where the approved behavior changed. Fixed per-Skill line quotas were removed; size diagnostics remain advisory. Static tests do not replace the behavior exercises.
- Skills: 594 combined lines, 30–64 per Skill (baseline 579). These are observations, not limits.
- The Manifest is regenerated from final repository bytes. CI and remote push identity are checked separately after commit.

## Not claimed

No live message recovery, model switch, archive operation, project deployment or new engineering Run is proved by these local checks. The authorized project agent verifies its own installed payload and then starts the next Run; the method maintainer does not impersonate project acceptance. No tag or GitHub Release is implied by pushing this maintenance branch.
