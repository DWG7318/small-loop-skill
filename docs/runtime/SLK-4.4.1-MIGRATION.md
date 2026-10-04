# SLK 4.4.1 local compatibility and admission

This compatible patch corrects original-role handoffs, saved credential consumers, immutable INCOMPLETE recovery, truthful readiness and native Supervisor notices. BI/WebBI stays 1.1.0. It does not authorize publishing, reopening a product Run, changing its model or replaying accepted work.

## Existing 4.4.0 Runs

- Installed tools are 4.4.1; an existing Run stays 4.4.0 until its authorized version adoption. Request, Run summary and snapshot must agree. Only 4.4.0/4.4.1 are admitted by these consumers; arbitrary historical versions remain rejected.
- Preserve original endpoints, Sessions, candidates, logical messages, sealed credentials and failed attempts. Repair only the exact remaining suffix. Never relabel null-candidate INCOMPLETE as completed or start another Worker/Checker.
- Desktop-owned endpoints pin their genuinely inherited App Tools entry and requested model/effort. No second App Server writer, caller impersonation or CLI takeover. Missing capability blocks dispatch. A model request is not actual-model attestation.
- Recheck native activity and central TOKEN. Accepted, native-started, committed and completed are different facts. When native work started, finish only its proven remaining commit; uncertain delivery never permits blind resend.
- New Runs use `slk.role-host/v1` plus same-Run `slk.communication-rehearsal/v2`. An in-flight migration instead uses `preflight-admission`: one different isolated Run supplies recomputable complete v2 normal-chain conformance, while the target Run separately proves its current host binding and four sealed consumers. No isolated candidate, verdict, TOKEN event or product failure becomes a target-Run fact; echo v1 remains blocked.
- Correct an old Supervisor binding only with `revise-role-model`: same role instance, Session and credential; canonical `gpt-6.1-sol`; Owner-selected `high` or `xhigh`; hash-valid Owner evidence; append-only `MODEL_CHANGED`. Use `supervisor-admin` to consume the saved Supervisor credential internally for this, method adoption, exact endpoint rebind or OW turn resume. The OW itself uses `overwatcher-admin` for cycle/status writes; Supervisor never borrows that permission.
- A verified null-candidate Worker INCOMPLETE may re-enter only through `resume-role-host`; it consumes `incomplete-handoff/evidence.json`, preserves the original result/failed terminal and executes the original Worker-owned suffix once. `reload-temporal-worker` replaces only the exact worker process chain and must re-query the same Start/Run workflow IDs, native run IDs and startup fingerprint.

## Normal roles and assurance

Supervisor freezes actual host/endpoint/credential consumers and the complete serial plan before first dispatch. The owning adapter persists the engineering terminal then performs its role's authenticated suffix. Initial Supervisor→Checker; Checker→Worker→Checker; D1 FAIL→Supervisor decision→same Worker→Checker; final Checker→Supervisor D2. Judgments stay with their original roles; normal delivery never depends on OW relaying it.

Subsequent CELLs use the existing closed six-field payload: cell_id, cell_ordinal, required_cell_count, task, d1_criteria, root_record_path. Candidate goals/criteria come from the frozen task, not Worker replacements. Supervisor's rework/D2 result never replaces Checker D1. Preparation Goal cannot take over an unrelated Goal or complete based on BI/high accepted counts.

OW reports facts/unknowns; receipt is not takeover. After a proven Supervisor decision/takeover it suspends only that Run's patrol until restoration is confirmed; other bound Runs stay observed. Owning host/Temporal produces independent exit evidence, not OW's final message. No heartbeat, scheduled task, new role or monitoring database is added.

Temporal preserves histories with patch markers. Timer/recovery waits stay bounded and guarded. New notifications require exact native start, original event and registered Supervisor identity. Failure retains a runtime guard and cannot authorize the next CELL. Old history replays under its existing branch, never rewritten. Production adapters must supply native-notice capability before admission.

## Package and rollback

Active packages contain current instructions/contracts/integrations and this guide. Historical CHANGELOG/MIGRATION and maintenance audits stay in the source repository/Git, not installed current instructions. Retired auxiliary switches are not admitted as ON or OFF aliases; project additions remain explicitly registered required Skills/tools.

Use the existing hash-bound builder/installer, then verify manifest, actual loaded versions and native wrapper paths. Back up only managed SLK roots. Never roll back product databases, credentials or Workflow histories with files. Reconcile external actions before file rollback; use a bounded forward repair when compatibility is unproved.
