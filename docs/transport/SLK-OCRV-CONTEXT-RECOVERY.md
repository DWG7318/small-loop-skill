# Evidence-specific OCRV INCOMPLETE continuation

This is a compatible Tool correction for the existing 4.4.2 `D1_MANAGEMENT_RETURN` route, not a new role, D1, scheduler or universal size gate. Aggregate budget and timeout remain native unlimited. Do not use budget-only recovery for a compression failure.

Native OCRV 1.12.12 `--resume` reuses settled fingerprints and starts fresh conversations for remaining items, but regroups them semantically; neither `--resume` nor `--max-tokens` guarantees smaller groups. SLK therefore reuses the frozen completed checkpoints as evidence and performs fresh serial scoped reviews of only the failed native groups. It does **not** claim a native resume lineage for these fresh subreviews.

## Prepare, without executing a review

Call the installed `slk-transport` entry:

```text
slk-transport prepare-context-review --source-request <original-ocrv-request.json> --source-result <original-ocrv-result.json> --raw-review <original-ocrv-review.json> --session-record <original-native-session.jsonl> --candidate-message-id <original-candidate-message> --source-d1-incomplete-event-id <current-D1-INCOMPLETE> --output <new-plan.json> [--per-file]
```

The closed [plan contract](../contracts/slk-ocrv-context-recovery.schema.json) pins every source hash, candidate, full scope, original criteria, result, manifest and reusable native checkpoint. The preparer never accesses credentials, runs a model, modifies the original evidence or replaces an existing plan. Native zero-finding checkpoints legitimately omit `comments`; an explicit invalid value is rejected.

For the separately demonstrated **normal full-review zero-complete per-call input threshold**, add `--per-call-input-threshold` to the same prepare-only command. This emits closed v2 `PER_CALL_INPUT_THRESHOLD`, not a relabeled compression/partial plan. It requires the original native failed Session, zero completed/reused/findings, the complete immutable single-parent Git selection and matching request/result/source hashes. Every selected item must have one native failed checkpoint with the exact `prompt tokens (N) exceed 80% of max_tokens(M) [round R]` error, `N > 0.8*M`, positive round and `M` equal to the frozen original ceiling. Quota/aggregate-budget/timeout errors, mixed reasons, incomplete or duplicated partitions, scoped child/old partial lineage, superseded source D1 and unknown versions fail closed. Aggregate budget and timeout must remain native unlimited `0`; the existing management adapter retains the **original per-call ceiling**, never raises it to its default. Fresh single-file groups are deterministic; no recursive admission or criterion splitting is allowed when a single file remains too large.

Default refinement halves each observed failed group. `--per-file` instead selects fresh single-file subreviews **only as a response to this demonstrated compression failure**, not as a limit for normal D1. Both retain all original D1 criteria and permit necessary cross-file context; no completed item is removed from the final denominator. A single-file subreview can still fail; no capacity claim or completion is inferred from preparation.

The explicit v2 threshold mode always uses single-file subreviews with all original criteria and necessary cross-file context. Each runs once; a single-file preflight/native failure returns real INCOMPLETE through the original management/same-D1 suffix, not Worker rework, product FAIL or an endless automatic retry. The original plan/sources remain immutable; a later D1 event cannot reuse the old admission. The aggregate exposes reviewed/not-reviewed paths. V2 covers **only this frozen candidate selection**: current delta8 cannot imply original full18 acceptance or discard nine older failed paths. When an early FAIL left original scope unreviewed and the current rework is its direct child, add `--original-scope-plan <frozen-original-v1-plan.json>` alongside `--per-call-input-threshold`. Closed v3 `ORIGINAL_SCOPE_AT_CURRENT_CANDIDATE` preserves the engineering candidate payload/commit while invoking the existing native `--from <original-base> --to <current-commit>` range. The range must equal the original/current path union and the original goal/criteria; all range files are freshly reviewed, with **no old PASS/findings reused**. Source plans/manifests, current threshold checkpoints, background evidence hashes and immutable range identities are bound before startup and rechecked before the same-D1 correction. Native backgrounds contain the original goal, criteria, manifest/plan hashes and unresolved paths; each child's actual range/item/fingerprint/artifact and completed partition must match. Omitted old paths, changed endpoints/background or a commit-mode child fail closed. A remaining single-file failure stops INCOMPLETE; this is not permission for a new Worker candidate, wider goal, larger per-call ceiling or repeat admission.

## Formal Supervisor return to the original Checker

The current Supervisor retains the standard three-field management decision (`action`, `summary`, `evidence_refs`). Include the **prepared plan path** in `decision.evidence_refs`, keep the current incoming Supervisor source message, and choose `MECHANICAL_RECOVERY` or a justified existing management action. A sentence saying “resume” is not an execution parameter. Place the formal `slk.supervisor-result/v1` at the exact incoming native attempt's `supervisor-result.json`, then submit with the registered Host binding and its SHA-256 (not the decision-file hash):

```text
slk-transport submit-supervisor-decision --binding <current-role-host-binding.json> --source-attempt <exact-incoming-Supervisor-native-attempt> --sha256 <role-host-binding-SHA256>
```

The original Checker receives the existing management return. Its adapter validates the plan **before** model startup, previews the frozen commit (v1/v2) or explicitly bound current range (v3), invokes existing serial segment Tools, and checks each actual native manifest against the expected path/item/fingerprint subset. Missing, damaged, duplicated, unknown-version or drifted material is rejected. Only v3 permits fresh range coverage instead of preserving old snapshot conclusions; management summary/evidence text alone never changes the native input.

Final aggregate contains preserved coverage/findings for v1, or exclusively fresh native coverage for v2/v3. PASS requires every selected item and every original criterion to be covered. Another partial result remains INCOMPLETE with retained segment evidence; current findings are not discarded. Existing sealed Checker RoleHost records the single D1 correction under the unchanged engineering candidate/message and owns its normal post-D1 suffix; the native range is separately bound, not substituted into the candidate payload. Supervisor/OW/method maintainer do not run product D1, borrow the Checker credential or turn preparation into PASS.

Initial start receipt remains immutable; the existing native-activity inspector follows the latest proven `review-segments/segment-*/started.json`, rather than treating the exited first subreview as the whole Checker having stopped. A genuine live product continuation is separate acceptance evidence; synthetic tests and a frozen prepared plan do not establish its outcome.

## Consume an already-completed native blocker, without rerunning it

Full-candidate and scoped-review artifact hashes are not interchangeable. For OCRV 1.12.12 commit reviews, validation reconstructs the pinned single-parent Git diff, item IDs and fingerprints, then independently verifies the full and exact-subset artifact hashes. Candidate/base/range, selected identities, provider/model and runtime configuration remain fixed; a scope-dependent rule hash is not mistaken for runtime drift. Unsupported or damaged evidence fails closed.

Only the original registered Checker Host may consume a first completed segment rejected by `OCRV_CONTEXT_RECOVERY_INVALID`, with its existing native start, exact request, terminal manifest, checkpoints and original compression-only plan. The closed entry first supports a read-only readiness check:

```text
slk-transport consume-context-terminal --binding <current-role-host-binding.json> --sha256 <binding-SHA256> --source-attempt <exact-failed-management-return-attempt> --session-record <original-child-native-session.jsonl> --session-sha256 <native-session-SHA256> --prepare-only
```

After readiness, the Supervisor invokes that same sealed entry without `--prepare-only`. It authenticates the registered Checker internally, derives append-only evidence under `role-host/context-terminal`, and uses the normal Checker-owned D1 FAIL correction and Supervisor escalation suffix. It never starts OCRV, resends the management return, alters the original failed receipt, borrows another role's credential or judges a new finding. Native MEDIUM-or-higher blocking findings remain FAIL; the aggregate explicitly retains preserved findings, reused coverage, reviewed paths and **not-reviewed** paths. An early FAIL is not full review completion and cannot become PASS. Repeating the same completed consumption returns its existing receipt; source or identity drift is rejected.
