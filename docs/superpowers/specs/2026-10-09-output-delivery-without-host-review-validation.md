# Output delivery simplification — local candidate evidence

Date: 2026-10-09–10, Asia/Shanghai. Status: local implementation and behavioral verification complete; final package/isolated-mirror and committed-identity evidence is recorded in the local freeze receipt below; NOT deployed or independently accepted.

## Authority and scope

- Source: `C:/Users/DWG/.config/superpowers/worktrees/SLK/slk-4-4-2-runtime-recovery`; branch `feature/slk-4.4.2-runtime-recovery`; bounded baseline `5f1ced7bdc230f9bb90bf638e841a896f7ad65b4`.
- Version: SLK/tools 4.4.2, BI/WebBI 1.1.0. [Approved design](2026-10-09-output-delivery-without-host-review-design.md). Independent acceptance: `01a0bed1-af60-7ac0-8003-d3d6f9d30124` (`RC08｜Supervisor｜GUI Windows Stability`).
- Only local method source, integration, docs, offline fixtures, disposable test databases, local packages and explicitly isolated test-install homes changed. No product Run/history/TOKEN/database, existing/global installed runtime, real Agent/Temporal dispatch, paid review, deployment, remote action or release was performed by this patch.

## Implemented behavior

- DSH/OCRV preserve arbitrary original bytes, partial/non-JSON/missing-field output and actual native exits. Body parsing, severity, coverage, missing output and native failure do not synthesize D0/D1/PASS/FAIL/INCOMPLETE.
- Original Worker records WORK_STARTED/D0_COMPLETED/CANDIDATE_SUBMITTED through native-bound `submit-worker-action`; `--details` is its JSON action FILE. The immutable action and central event, not the final report body, supply the candidate. Free-text output travels through the same standard message to original Checker, with real receive/start and atomic TOKEN handoff. Without that candidate, the existing Checker interface reports the actual limitation to Supervisor; no workspace candidate or review is invented.
- Original OCRV Checker has one stdio MCP action `slk_checker_decide(verdict, message?)`, without selectable source/role/credential or arbitrary executor. Same-call standard routing handles FAIL/INCOMPLETE to Supervisor and PASS to the exact next Required CELL or final D2_READY. Its own native start and explicit decision suffice; future final output is not a prerequisite. Findings/steps are not fabricated to fill fields.
- MCP setup uses absolute Python, installed bridge and required `--transport <absolute slk-transport.pyz>`. Real packaged subprocess initialize/discovery/unbound rejection works without source PYTHONPATH. Install and rollback enumerate the bridge. This does not claim a real model invoked it correctly.
- Supervisor actions retain exact identity/authority/intent and successor proof, but not fixed prose/evidence/severity/action-mode review. Second-FAIL investigation/splitting remains a role obligation, not host re-judgment; older frozen method semantics remain unchanged.
- Report delivery is independent of TOKEN/ACK/Temporal engineering dispatch guards. Job distinguishes native_result/output_delivery/handoff; delivery or handoff failure returns failed/exit 5 without rewriting native terminal bytes. Send ACK means NATIVE_RECEIVE_START_ONLY. Inspect reads later job evidence or UNOBSERVED; it never sends or waits.
- Exact ordinary/retry/Desktop evidence is read without new IDs or duplicate sends. Temporal registration references the already-delivered exact report; original native bytes remain unchanged and endpoint/envelope drift rejects. OW observes native/delivery facts, not report validity.
- Role authority, scope, candidate/attempt, immutable history, deduplication, sealed credentials, real start, current plan and atomic TOKEN protections remain active.

## Retirement → current test mapping

| Retired behavior/tests | Current evidence |
| --- | --- |
| Strict DSH result contract, invalid-result/pre-D0 supplements | `test_output_delivery.py`: arbitrary bytes/exits/missing fields, no fabricated candidate; actual Worker action/free-text handoff in `test_checker_action_compatibility.py` |
| Context/partial/budget/fresh-terminal auto-consumption and severity verdict synthesis | Output-delivery, OCRV adapter/classification/resume and CLI tests: no host verdict, retired commands reject before side effects, original partial/error facts retained |
| Host-parsed post-D1/committed-terminal completion | `test_checker_decision_tool.py` and action-compatibility tests: original authenticated action before future output; raw report remains independent |
| Body-reviewed Supervisor/second-FAIL veto | Explicit Supervisor format/evidence-independent action tests and Rust `slk_442_second_d1_failure_records_supervisor_action_without_host_plan_judgment`; historical-version protections retained |
| Stale Skill wording/sandbox references | Semantic assertions retain role ownership, INCOMPLETE != FAIL, real activation, exact attempt/identity, no waits/duplicate sends; sandbox invokes current action/output cases |

Deleted obsolete test modules: committed_checker_terminal; context_review/context_terminal; independent_checker_fail; incomplete_checker_resume/incomplete_handoff; partial_checker_resume/existing_partial_consumption; pre_d0_blocked_recovery; terminal_budget_resume/fresh_review/fresh_partial. They asserted retired behavior; remaining authority/identity/dedup guards are covered by the above plus existing recovery/Temporal/RoleHost tests. Historical schemas/reports remain archived, not active instructions.

## RED and intermediate evidence

All Python checks use local `src`, `PYTHONDONTWRITEBYTECODE=1` and `python -B`, not installed transport.

- Genuine REDs before fixes: native success hid delivery errors (3); OW body rejection (5); later job visibility missing (2); old receipt resent under new ID (2); explicit Checker decision waited for future output (6); management-return attempt reset (1); actual Worker explicit candidate/free-text report lacked handoff (1); packaged MCP import failed (2). Fixture mistakes/invalid diagnostic paths are not genuine REDs.
- Transitional whole suite: 940 passed / 34 failed / 10 skipped, traced to stale Skill/contracts and sandbox calls of retired functions. NOT final passing evidence.
- Intermediate focused group: 206 passed. Optimized action/output/MCP/CLI: 124 passed, expected pytest optimization warning; final Temporal cases were added afterwards.
- Before the final native-group instruction correction: whole repository 976 passed / 10 skipped; optimized action/output/MCP/CLI/Temporal 139 passed with the expected warning; schemas 42 valid; BI frontend 92 passed and typecheck passed. These are pre-correction results, not final evidence.
- Disposable real-state chain: FAIL → explicit Supervisor rework → same Worker attempt 2 with own D0/candidate and free-text output → original Checker INCOMPLETE → Supervisor management return → original Checker PASS → D2_READY; same candidate/attempt retained. Separate nonfinal PASS delivers only next Required CELL, attempt 1.
- Offline Rust workspace suites all pass. Local production artifact build, including BI fingerprint verification, succeeds. No existing/global installation follows; package copying is tested only in isolated homes under this source's ignored temporary directory.

## Final gates and local package

Final behavior after the native-group correction: `python -B -m pytest -q --tb=short` passes 978 / skips 10 (269.74s), including the disposable sandbox. Optimized output/action/MCP/CLI/Temporal/preflight passes 143 (62.45s), one expected pytest optimization warning. Rust workspace passes 144; BI frontend passes 92 plus typecheck; all 42 schemas validate; repository/Manifest and 16 Skills pass. Bounded scope, sensitive-pattern and full baseline-to-working diff checks pass. Final doc-only deployment clarification and the test-only fixture correction below are followed by repository/install/Skill regression: 173 passed (22.74s). The 978/143 behavior runs precede those documentation/fixture-only edits; no production behavior changed afterwards, and no additional model invocation is claimed.

Standalone install-test collection exposed a fixture import that previously depended on collecting transport tests. `test_ocrv_classification.py` now constructs its own valid envelope, with no cross-directory fixture import; its 25 ordinary and 25 optimized checks pass. This was a test-collection dependency, not a production regression or a new engineering RED.

Logs/artifacts stay under this source's `.codex/.tmp/output-delivery-*`. The preliminary standard package and isolated test installation both verify all 179 managed files. The final standard package is `C:/Users/DWG/.codex/.tmp/slk-output-delivery-20261010-package`; its isolated test home is this source's `.codex/.tmp/output-delivery-isolated-home`. No Desktop outputs or global deployment. The local [freeze receipt](../../../.codex/.tmp/output-delivery-handoff.json) records the exact final commit, repository/install Manifest hashes, artifact hashes, package/isolated-mirror verification and clean-state outcome after this report is finalized. That receipt is ignored local evidence to avoid embedding a self-referential commit/hash in tracked release material.

## Native grouping review and bounded correction

Upstream `fabbdb29` [agent dispatch](https://github.com/alibaba/open-code-review/blob/fabbdb29/internal/agent/agent.go) gives each native group a plan/main conversation and shared tool definitions; [grouping](https://github.com/alibaba/open-code-review/blob/fabbdb29/internal/agent/grouping.go) may bundle or partition/fall back per file. Concurrency 1 only serializes groups. The pre-group diff map supports cross-file inspection. Same native review ID proves invocation identity, not whole-candidate assessment.

With Root agreement, only existing background/tool description/Checker instructions now say: one decision for the entire frozen candidate and every CELL criterion, not current file/group; use cross-file tools and indexed originals; do not decide per group or repeat; unverified goals cannot become whole-CELL PASS. No grouping override, coverage/severity gate, extra approval round, state machine or Agent was added. Ordinary and optimized instruction tests both first failed 2/2; after correction, affected normal group passed 111 and optimized group passed 18 (expected warning). These test instruction presence and plumbing, not real model compliance. Product native group count and actual model behavior were not inspected or exercised; no single-group or full-model-acceptance claim is made.

## Migration and limitations

Supervisor independently accepts the frozen candidate/package, then separately deploys before product recovery. Install matching transport, Skills, integration and OCRV MCP configuration atomically; retain original Run/role/Session/candidate/attempt/history, verify real capability and identity, and keep readiness blocked on failure. Do not replay old reports through retired consumers or rewrite historical FAIL.

Root independently found that real `D:/OCRV/ocr-slk.ps1` forces `slk/slk-d1-rule.json`, referencing old `SLK-D1-REVIEW.md` automatic-classification prose. The accepted minimal deployment step is documented in the existing [OCRV configuration guide](../../../integrations/ocrv/OCRV-SLK-CONFIGURATION.md): preserve include/test-file scope and unrelated config, back up then remove only the obsolete SLK rule override, retain the old file as history, and use current background/tool descriptions without a second rule copy. Root must apply and read back this real configuration, preview and discover tools after acceptance. No runtime was edited or falsely claimed connected by the maintainer.

Offline receivers/disposable Rust state prove transport/action behavior, not model competence or product D1/D2. No real OCRV/DSH/OW/Temporal run or paid review occurred. The old 2.x Serial Plan script is absent from this 4.x source; current serial successor/attempt and frozen-plan tests are used. No product acceptance or deployment claim.
