from __future__ import annotations

import hashlib
import json
import copy
import subprocess
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.contracts import Envelope, canonical_json_sha256
from slk_transport.evidence import AttemptStore
from test_ocrv_adapter import candidate_envelope, checker_endpoint
from context_native_fixture import native_input


def write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def context_fixture(tmp_path: Path):
    original = candidate_envelope(tmp_path)
    paths = [f"file-{i:02d}.rs" for i in range(18)]
    repository = Path(original.payload['repository'])
    def git(*args):
        return subprocess.run(['git', '-C', str(repository), *args], capture_output=True,
                              check=True).stdout.decode().strip()
    git('init', '-q'); git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'user.name', 'fixture'); git('config', 'core.autocrlf', 'false')
    for path in paths:
        (repository / path).write_text('fn before() {}\n', encoding='utf-8')
    git('add', '.'); git('commit', '-qm', 'base')
    for path in paths:
        (repository / path).write_text('fn after() {}\n', encoding='utf-8')
    git('add', '.'); git('commit', '-qm', 'candidate')
    commit = git('rev-parse', 'HEAD')
    input_value, identities = native_input(repository, commit, paths)
    evidence = write(tmp_path / "evidence.json", {"next_payload": {"changed_paths": paths}})
    payload = {**original.payload, "candidate": {"kind": "commit", "commit": commit},
               "evidence_files": [str(evidence)]}
    original = Envelope.from_dict({**original.__dict__, "payload": payload,
                                   "payload_sha256": canonical_json_sha256(payload)})
    request = OcrvAdapter()._candidate_request(original)
    manifest = {"schema_version": "ocr.run-manifest/v1", "operation": "review",
                "run_id": "parent-session", "parent_run_id": None, "terminal_state": "partial",
                "input": input_value, "repository": {},
                "execution": {"ocr_version": "v1.12.12", "provider": "dashscope-tokenplan",
                              "model": "qwen3.8-max", "configured_concurrency": 1,
                              "rule_config_sha256": "c" * 64, "runtime_config_sha256": "d" * 64},
                "coverage": {"selected": identities, "completed": identities[11:], "reused": [],
                             "failed": [{**x, "classification": "unknown", "reason":
                                         "stopped because context compression exceeded its threshold"}
                                        for x in identities[:11]], "waived": []}}
    raw = {"status": "partial", "session_id": "parent-session", "manifest": manifest,
           "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
           "comments": [{"severity": "LOW", "message": "preserve this observation"}],
           "groups": [{"label": "failed-seven", "files": paths[:7]},
                      {"label": "failed-four", "files": paths[7:11]},
                      {"label": "done-two", "files": paths[11:13]},
                      {"label": "done-five", "files": paths[13:]}]}
    source = tmp_path / "source"
    source_request = write(source / "ocrv-request.json", request)
    source_raw = write(source / "ocrv-review.json", raw)
    source_result = write(source / "ocrv-result.json", {
        "schema_version": "slk.ocrv-d1-result/v1", "run_id": original.run_id,
        "cell_id": original.cell_id, "verdict": "INCOMPLETE", "review_invocation_id": "original",
        "request_sha256": ref(source_request)["sha256"],
        "review": {"status": "partial", "session_id": "parent-session",
                   "provider": "dashscope-tokenplan", "model": "qwen3.8-max", "exit_code": 0},
        "reason_codes": ["OCR_COVERAGE_INCOMPLETE"], "findings": raw["comments"],
        "evidence": [], "artifacts": {"raw_review": str(source_raw)}})
    session = source / "parent-session.jsonl"
    records = [{"type": "review_item_done", "sessionId": "parent-session", "filePath": x["path"],
                "fingerprint": x["fingerprint"], "comments": []} for x in identities[11:]]
    records.append({"type": "session_end", "session_id": "parent-session", "run_manifest": manifest})
    session.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    plan = {"schema_version": "slk.ocrv-context-recovery-plan/v1", "run_id": original.run_id,
            "cell_id": original.cell_id, "candidate_message_id": original.message_id,
            "source_d1_incomplete_event_id": "d1-incomplete-001",
            "sources": {"request": ref(source_request), "result": ref(source_result),
                        "raw_review": ref(source_raw), "session_record": ref(session)},
            "groups": [paths[:4], paths[4:7], paths[7:9], paths[9:11]]}
    plan_path = write(tmp_path / "context-plan.json", plan)
    returned_payload = {
        "source_d1_incomplete_event_id": plan["source_d1_incomplete_event_id"],
        "candidate_message_id": original.message_id, "candidate_payload": payload,
        "candidate_payload_sha256": original.payload_sha256, "management_action": "MECHANICAL_RECOVERY",
        "management_summary": "Reuse seven checkpoints; split only the two compression-failed groups.",
        "management_evidence_refs": [str(plan_path)],
        "review_policy": {"profile": "NORMAL_D1_DEFAULT", "aggregate_budget": "NATIVE_UNLIMITED",
                          "review_timeout": "NATIVE_UNLIMITED", "tool_rounds": "TEMPLATE_DEFAULT"}}
    returned = Envelope.from_dict({**original.__dict__, "message_id": "77777777-7777-4777-8777-777777777777",
                                  "sender_role": "supervisor", "sender_role_instance_id": "RUN-A-supervisor-001",
                                  "payload_type": "D1_MANAGEMENT_RETURN", "payload": returned_payload,
                                  "payload_sha256": canonical_json_sha256(returned_payload)})
    return returned, plan_path, plan, identities


def test_management_context_recovery_reviews_only_failed_groups_and_preserves_full_scope(tmp_path):
    returned, plan_path, plan, identities = context_fixture(tmp_path)
    endpoint = checker_endpoint(tmp_path, "context-recovery")
    attempt = AttemptStore(tmp_path / "attempts").create(returned)
    result = OcrvAdapter().deliver(endpoint, returned, attempt)
    invocations = [json.loads(x) for x in (Path(returned.payload["candidate_payload"]["repository"])
                                           / ".fake-ocrv-invocations.jsonl").read_text().splitlines()]
    actual = [json.loads(Path(x["request"]).read_text())["review_scope"]["include_paths"]
              for x in invocations if not x["preflight"]]
    assert actual == plan["groups"]
    assert result.status == "completed" and result.native_identity["verdict"] == "PASS"
    aggregate = json.loads((attempt.root / "ocrv-aggregate.json").read_text())
    assert aggregate["context_recovery"]["plan_sha256"] == ref(plan_path)["sha256"]
    assert aggregate["context_recovery"]["reused"] == identities[11:]
    formal = json.loads((attempt.root / "ocrv-result.json").read_text())
    assert any(x.get("message") == "preserve this observation" for x in formal["findings"])
    full_request = json.loads((attempt.root / "ocrv-request.json").read_text())
    assert full_request["review_scope"]["include_paths"] == [x["path"] for x in identities]
    assert full_request["d1_criteria"] == returned.payload["candidate_payload"]["d1_criteria"]


@pytest.mark.parametrize("damage", ["hash", "candidate", "scope", "checkpoint", "groups", "duplicate",
                                    "missing", "invalid-json", "unknown-version", "mixed-failure"])
def test_context_recovery_rejects_drift_before_native_review(tmp_path, damage):
    returned, plan_path, plan, _identities = context_fixture(tmp_path)
    if damage == "hash":
        Path(plan["sources"]["raw_review"]["path"]).write_text("{}", encoding="utf-8")
    elif damage == "candidate":
        p = Path(plan["sources"]["request"]["path"])
        value = json.loads(p.read_text()); value["candidate"]["commit"] = "a" * 40
        write(p, value); plan["sources"]["request"] = ref(p)
    elif damage == "scope":
        p = Path(plan["sources"]["raw_review"]["path"])
        value = json.loads(p.read_text()); value["manifest"]["coverage"]["selected"].pop()
        write(p, value); plan["sources"]["raw_review"] = ref(p)
    elif damage == "checkpoint":
        p = Path(plan["sources"]["session_record"]["path"])
        p.write_text("\n".join(p.read_text().splitlines()[1:]) + "\n", encoding="utf-8")
        plan["sources"]["session_record"] = ref(p)
    elif damage == "groups":
        plan["groups"] = [sum(plan["groups"], [])]
    elif damage == "duplicate":
        plan["groups"][0].append(plan["groups"][0][0])
    elif damage == "missing":
        plan_path.unlink()
    elif damage == "invalid-json":
        plan_path.write_text("{", encoding="utf-8")
    elif damage == "unknown-version":
        plan["schema_version"] = "slk.ocrv-context-recovery-plan/v999"
    elif damage == "mixed-failure":
        p = Path(plan["sources"]["raw_review"]["path"])
        value = json.loads(p.read_text()); value["manifest"]["coverage"]["failed"][0]["reason"] = "quota exhausted"
        write(p, value); plan["sources"]["raw_review"] = ref(p)
    if damage not in {"missing", "invalid-json"}:
        write(plan_path, plan)
    endpoint = checker_endpoint(tmp_path, "context-recovery")
    attempt = AttemptStore(tmp_path / "attempts").create(returned)
    with pytest.raises(AdapterError, match="context|Context|checkpoint|scope|candidate|source"):
        OcrvAdapter().deliver(endpoint, returned, attempt)
    assert not (Path(returned.payload["candidate_payload"]["repository"])
                / ".fake-ocrv-invocations.jsonl").exists()


@pytest.mark.parametrize("mode", ["context-partial", "context-scope-leak"])
def test_context_child_cannot_turn_missing_coverage_into_pass(tmp_path, mode):
    returned, _path, _plan, _identities = context_fixture(tmp_path)
    endpoint = checker_endpoint(tmp_path, mode)
    attempt = AttemptStore(tmp_path / "attempts").create(returned)
    if mode == "context-scope-leak":
        with pytest.raises(AdapterError, match="context segment"):
            OcrvAdapter().deliver(endpoint, returned, attempt)
        assert not (attempt.root / "ocrv-result.json").exists()
    else:
        result = OcrvAdapter().deliver(endpoint, returned, attempt)
        assert result.native_identity["verdict"] == "INCOMPLETE"
        formal = json.loads((attempt.root / "ocrv-result.json").read_text())
        assert formal["review"]["status"] == "partial"
        aggregate = json.loads((attempt.root / "ocrv-aggregate.json").read_text())
        assert aggregate["completed_segment_count"] == 1
        assert aggregate["planned_segment_count"] == 4


def test_context_preparer_only_writes_a_frozen_plan_and_rejects_overwrite(tmp_path):
    from slk_transport.cli import main
    returned, _path, plan, _identities = context_fixture(tmp_path)
    output = tmp_path / "prepared" / "plan.json"
    args = ["prepare-context-review", "--candidate-message-id", plan["candidate_message_id"],
            "--source-d1-incomplete-event-id", plan["source_d1_incomplete_event_id"], "--output", str(output)]
    for key, option in {"request": "source-request", "result": "source-result",
                        "raw_review": "raw-review", "session_record": "session-record"}.items():
        args.extend(["--" + option, plan["sources"][key]["path"]])
    assert main(args) == 0
    assert json.loads(output.read_text()) == plan
    with pytest.raises(RuntimeError, match="evidence already exists"):
        main(args)
    assert not (Path(returned.payload["candidate_payload"]["repository"])
                / ".fake-ocrv-invocations.jsonl").exists()


def test_native_zero_finding_checkpoint_omits_comments_but_is_still_reusable(tmp_path):
    from slk_transport.context_review import validate
    returned, plan_path, plan, _identities = context_fixture(tmp_path)
    p = Path(plan["sources"]["session_record"]["path"])
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    for row in rows:
        if row["type"] == "review_item_done":
            row.pop("comments")
    p.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
    plan["sources"]["session_record"] = ref(p)
    write(plan_path, plan)
    basis = validate(plan, OcrvAdapter()._candidate_request(returned), returned.payload)
    assert len(basis["reused"]) == 7


def test_preparer_can_choose_per_file_recovery_only_for_observed_failed_groups(tmp_path):
    from slk_transport.cli import main
    from slk_transport.context_review import validate
    returned, _path, plan, _identities = context_fixture(tmp_path)
    output = tmp_path / "prepared" / "per-file.json"
    args = ["prepare-context-review", "--per-file", "--candidate-message-id", plan["candidate_message_id"],
            "--source-d1-incomplete-event-id", plan["source_d1_incomplete_event_id"], "--output", str(output)]
    for key, option in {"request": "source-request", "result": "source-result",
                        "raw_review": "raw-review", "session_record": "session-record"}.items():
        args.extend(["--" + option, plan["sources"][key]["path"]])
    assert main(args) == 0
    generated = json.loads(output.read_text())
    assert generated["groups"] == [[f"file-{i:02d}.rs"] for i in range(11)]
    validate(generated, OcrvAdapter()._candidate_request(returned), returned.payload)


def test_context_native_blocking_finding_cannot_be_hidden_by_formal_pass(tmp_path):
    returned, _path, _plan, _identities = context_fixture(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(returned)
    with pytest.raises(AdapterError, match="context segment"):
        OcrvAdapter().deliver(checker_endpoint(tmp_path, "context-verdict-leak"), returned, attempt)
    assert not (attempt.root / "ocrv-result.json").exists()


def test_context_partial_keeps_incomplete_even_with_preserved_blocking_finding(tmp_path):
    returned, plan_path, plan, _identities = context_fixture(tmp_path)
    raw_path = Path(plan["sources"]["raw_review"]["path"])
    raw = json.loads(raw_path.read_text())
    raw["comments"][0]["severity"] = "HIGH"
    write(raw_path, raw)
    plan["sources"]["raw_review"] = ref(raw_path)
    write(plan_path, plan)
    attempt = AttemptStore(tmp_path / "attempts").create(returned)
    result = OcrvAdapter().deliver(checker_endpoint(tmp_path, "context-partial"), returned, attempt)
    assert result.native_identity["verdict"] == "INCOMPLETE"
    assert json.loads((attempt.root / "ocrv-result.json").read_text())["findings"][0]["severity"] == "HIGH"


def segment_fixture(tmp_path):
    from slk_transport.context_review import validate
    returned, _path, plan, selected = context_fixture(tmp_path)
    basis = validate(plan, OcrvAdapter()._candidate_request(returned), returned.payload)
    raw = copy.deepcopy(basis['raw'])
    raw.update(status='complete', session_id='child-session', comments=[])
    manifest = raw['manifest']
    manifest.update(run_id='child-session', terminal_state='complete')
    scope = plan['groups'][0]
    manifest['input'], items = native_input(
        returned.payload['candidate_payload']['repository'],
        returned.payload['candidate_payload']['candidate']['commit'], scope)
    manifest['coverage'].update(selected=items, completed=items, failed=[], reused=[])
    path = write(tmp_path / 'child-raw.json', raw)
    value = {'artifacts': {'raw_review': str(path)}, 'review': {'session_id': 'child-session'}, 'verdict': 'PASS'}
    return basis, value, scope, path, raw


def test_subset_artifact_is_recomputed_from_exact_native_diff_not_parent_hash(tmp_path):
    from slk_transport.context_review import validate_segment
    basis, value, scope, _path, raw = segment_fixture(tmp_path)
    assert raw['manifest']['input']['source_artifact_sha256'] != basis['raw']['manifest']['input']['source_artifact_sha256']
    validate_segment(basis, value, scope)


@pytest.mark.parametrize('damage', ['artifact', 'parent-artifact', 'runtime', 'version', 'concurrency',
                                    'candidate', 'range', 'path', 'fingerprint', 'repository', 'missing-hash'])
def test_subset_rejects_forged_source_or_execution_identity(tmp_path, damage):
    from slk_transport.context_review import validate_segment
    basis, value, scope, path, raw = segment_fixture(tmp_path)
    manifest = raw['manifest']
    if damage == 'artifact': manifest['input']['source_artifact_sha256'] = 'f' * 64
    elif damage == 'parent-artifact': manifest['input']['source_artifact_sha256'] = basis['raw']['manifest']['input']['source_artifact_sha256']
    elif damage == 'runtime': manifest['execution']['runtime_config_sha256'] = 'f' * 64
    elif damage == 'version': manifest['execution']['ocr_version'] = 'v0.1'
    elif damage == 'concurrency': manifest['execution']['configured_concurrency'] = 2
    elif damage == 'candidate': manifest['input']['resolved_head'] = 'f' * 40
    elif damage == 'range': manifest['input']['exact_range'] = 'unrelated'
    elif damage == 'path': manifest['coverage']['selected'][0]['path'] = 'unrelated.rs'
    elif damage == 'fingerprint': manifest['coverage']['selected'][0]['fingerprint'] = 'f' * 64
    elif damage == 'repository': manifest['repository'] = {'identity_sha256': 'f' * 64}
    else: manifest['input'].pop('source_artifact_sha256')
    write(path, raw)
    with pytest.raises(ValueError):
        validate_segment(basis, value, scope)


def test_parent_forged_fingerprint_does_not_validate_even_when_child_and_artifact_agree(tmp_path):
    from slk_transport.context_review import validate_segment
    basis, value, scope, path, raw = segment_fixture(tmp_path)
    identity = raw['manifest']['coverage']['selected'][0]
    identity['fingerprint'] = 'f' * 64
    basis['selected'][identity['path']]['fingerprint'] = 'f' * 64
    write(path, raw)
    with pytest.raises(ValueError):
        validate_segment(basis, value, scope)


def threshold_fixture(tmp_path):
    """Native zero-complete full review; no compression/partial lineage."""
    returned, plan_path, plan, items = context_fixture(tmp_path)
    candidate = {**returned.payload['candidate_payload'], 'd1_criteria': ['criterion one', 'criterion two', 'criterion three']}
    payload = {**returned.payload, 'candidate_payload': candidate, 'candidate_payload_sha256': canonical_json_sha256(candidate)}
    returned = Envelope.from_dict({**returned.__dict__, 'payload': payload, 'payload_sha256': canonical_json_sha256(payload)})
    request_path = Path(plan['sources']['request']['path'])
    request = json.loads(request_path.read_text())
    request['d1_criteria'] = candidate['d1_criteria']
    request['review_scope']['criterion_ids'] = ['D1-001', 'D1-002', 'D1-003']
    request['review_scope']['scope_sha256'] = canonical_json_sha256({k: v for k, v in request['review_scope'].items() if k != 'scope_sha256'})
    request['capacity']['max_tokens'] = 32000
    write(request_path, request)
    raw_path = Path(plan['sources']['raw_review']['path'])
    raw = json.loads(raw_path.read_text())
    raw.update(status='failed', comments=[], groups=[{'files': [x['path'] for x in items]}])
    manifest = raw['manifest']
    manifest['terminal_state'] = 'failed'
    manifest['coverage'].update(completed=[], reused=[], failed=[{**x,
        'classification': 'budget', 'reason': 'prompt exceeded the configured token budget'} for x in items])
    write(raw_path, raw)
    result_path = Path(plan['sources']['result']['path'])
    result = json.loads(result_path.read_text())
    result.update(request_sha256=ref(request_path)['sha256'], findings=[],
        reason_codes=['OCR_EXIT_1', 'OCR_STATUS_NOT_COMPLETE', 'OCR_COVERAGE_INCOMPLETE'])
    result['review'].update(status='failed', exit_code=1)
    write(result_path, result)
    rows = [{'type': 'session_start', 'sessionId': 'parent-session', 'parentUuid': None,
        'diffCommit': request['candidate']['commit'], 'cwd': request['repository'],
        'reviewMode': 'commit', 'model': 'qwen3.8-max', 'llmSource': 'provider:dashscope-tokenplan'}]
    rows += [{'type': 'review_item_failed', 'sessionId': 'parent-session', 'filePath': x['path'],
        'fingerprint': x['fingerprint'], 'model': 'qwen3.8-max',
        'error': 'prompt tokens (26017) exceed 80% of max_tokens(32000) [round 1]'} for x in items]
    rows.append({'type': 'session_end', 'sessionId': 'parent-session', 'run_manifest': manifest})
    session = Path(plan['sources']['session_record']['path'])
    session.write_text(''.join(json.dumps(x) + '\n' for x in rows), encoding='utf-8')
    plan.update(schema_version='slk.ocrv-context-recovery-plan/v2',
        failure_kind='PER_CALL_INPUT_THRESHOLD', groups=[[x['path']] for x in items])
    for key, source in plan['sources'].items():
        plan['sources'][key] = ref(Path(source['path']))
    write(plan_path, plan)
    return returned, plan_path, plan, items, request, raw, rows


@pytest.mark.parametrize('mode', ['context-recovery', 'context-partial'])
def test_zero_complete_threshold_uses_existing_serial_route_once_without_capacity_upgrade(tmp_path, mode):
    returned, plan_path, plan, items, request, _raw, _rows = threshold_fixture(tmp_path)
    before = {k: ref(Path(v['path'])) for k, v in plan['sources'].items()}
    attempt = AttemptStore(tmp_path / 'attempts').create(returned)
    result = OcrvAdapter().deliver(checker_endpoint(tmp_path, mode), returned, attempt)
    aggregate = json.loads((attempt.root / 'ocrv-aggregate.json').read_text())
    assert result.native_identity['verdict'] == ('INCOMPLETE' if mode == 'context-partial' else 'PASS')
    assert aggregate['planned_segment_count'] == len(items)
    assert aggregate['completed_segment_count'] == (1 if mode == 'context-partial' else len(items))
    assert aggregate['context_recovery']['selected'] == items
    assert aggregate['context_recovery']['reused'] == []
    assert aggregate['context_recovery']['plan_sha256'] == ref(plan_path)['sha256']
    reviewed = [json.loads(x.read_text()) for x in sorted((attempt.root / 'review-segments').glob('*/request.json'))]
    assert [x['review_scope']['include_paths'] for x in reviewed] == plan['groups'][:len(reviewed)]
    assert all(x['capacity'] == request['capacity'] and x['d1_criteria'] == request['d1_criteria'] for x in reviewed)
    assert {k: ref(Path(v['path'])) for k, v in plan['sources'].items()} == before


def test_threshold_preparer_is_explicit_prepare_only_closed_schema_and_no_overwrite(tmp_path):
    import jsonschema
    from slk_transport.cli import main
    returned, _path, plan, _items, _request, _raw, _rows = threshold_fixture(tmp_path)
    output = tmp_path / 'prepared/threshold.json'
    args = ['prepare-context-review', '--per-call-input-threshold',
        '--candidate-message-id', plan['candidate_message_id'],
        '--source-d1-incomplete-event-id', plan['source_d1_incomplete_event_id'], '--output', str(output)]
    for key, option in {'request': 'source-request', 'result': 'source-result',
                       'raw_review': 'raw-review', 'session_record': 'session-record'}.items():
        args.extend(['--' + option, plan['sources'][key]['path']])
    assert main(args) == 0
    assert json.loads(output.read_text()) == plan
    schema = json.loads((Path(__file__).resolve().parents[2] / 'docs/contracts/slk-ocrv-context-recovery.schema.json').read_text())
    jsonschema.validate(plan, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**plan, 'failure_kind': 'budget'}, schema)
    with pytest.raises(RuntimeError, match='evidence already exists'):
        main(args)
    assert not (Path(returned.payload['candidate_payload']['repository']) / '.fake-ocrv-invocations.jsonl').exists()


def test_threshold_single_file_preflight_failure_cannot_split_or_drop_original_criteria(tmp_path, monkeypatch):
    returned, _path, _plan, _items, _request, _raw, _rows = threshold_fixture(tmp_path)
    original = OcrvAdapter._preflight_fits
    monkeypatch.setattr(OcrvAdapter, '_preflight_fits', lambda self, request, preflight:
        False if request['review_scope']['include_paths'] else original(request, preflight))
    attempt = AttemptStore(tmp_path / 'attempts').create(returned)
    result = OcrvAdapter().deliver(checker_endpoint(tmp_path, 'context-recovery'), returned, attempt)
    assert result.status == 'failed' and result.error_code == 'OCRV_REVIEW_INCOMPLETE'
    invocations = Path(returned.payload['candidate_payload']['repository']) / '.fake-ocrv-invocations.jsonl'
    calls = [json.loads(x) for x in invocations.read_text().splitlines()]
    assert len(calls) == 2 and all(x['preflight'] for x in calls)
    assert not (attempt.root / 'ocrv-result.json').exists()


@pytest.mark.parametrize('damage', ['error-missing', 'quota', 'below-threshold', 'wrong-max', 'wrong-round',
    'mixed-reason', 'duplicate-checkpoint', 'missing-checkpoint', 'wrong-session', 'wrong-start', 'checkpoint-done',
    'completed', 'missing-selected', 'fingerprint', 'native-parent', 'scoped-child', 'aggregate-budget',
    'timeout', 'boolean-budget', 'boolean-timeout', 'single-file-source', 'result-hash', 'source-hash',
    'groups', 'kind', 'superseded-event', 'old-label'])
def test_threshold_admission_rejects_unproven_or_repeated_scope_before_any_native_call(tmp_path, damage):
    from slk_transport.context_review import validate
    returned, _path, plan, items, request, raw, rows = threshold_fixture(tmp_path)
    current = copy.deepcopy(request)
    payload = dict(returned.payload)
    if damage == 'error-missing': rows[1].pop('error')
    elif damage == 'quota': rows[1]['error'] = 'account quota exhausted'
    elif damage == 'below-threshold': rows[1]['error'] = 'prompt tokens (25000) exceed 80% of max_tokens(32000) [round 1]'
    elif damage == 'wrong-max': rows[1]['error'] = 'prompt tokens (26017) exceed 80% of max_tokens(16000) [round 1]'
    elif damage == 'wrong-round': rows[1]['error'] = 'prompt tokens (26017) exceed 80% of max_tokens(32000) [round 0]'
    elif damage == 'mixed-reason': raw['manifest']['coverage']['failed'][0]['reason'] = 'quota exhausted'
    elif damage == 'duplicate-checkpoint': rows.insert(1, copy.deepcopy(rows[1]))
    elif damage == 'missing-checkpoint': rows.pop(1)
    elif damage == 'wrong-session': rows[1]['sessionId'] = 'other-session'
    elif damage == 'wrong-start': rows[0]['diffCommit'] = 'a' * 40
    elif damage == 'checkpoint-done': rows[1]['type'] = 'review_item_done'
    elif damage == 'completed': raw['manifest']['coverage']['completed'] = [items[0]]
    elif damage == 'missing-selected':
        raw['manifest']['coverage']['selected'].pop(); raw['manifest']['coverage']['failed'].pop()
        raw['groups'][0]['files'].pop(); plan['groups'].pop(); rows.pop(-2)
        from slk_transport.context_review import artifact_digest, identities
        raw['manifest']['input']['source_artifact_sha256'] = artifact_digest(identities(raw['manifest']['coverage']['selected']))
    elif damage == 'fingerprint':
        raw['manifest']['coverage']['selected'][0]['fingerprint'] = 'f' * 64
        raw['manifest']['coverage']['failed'][0]['fingerprint'] = 'f' * 64
        rows[1]['fingerprint'] = 'f' * 64
    elif damage == 'native-parent': raw['manifest']['parent_run_id'] = 'previous-partial'
    elif damage == 'scoped-child': request['review_scope']['include_paths'] = [items[0]['path']]
    elif damage == 'aggregate-budget': request['capacity']['max_tokens_budget'] = 80000
    elif damage == 'timeout': request['capacity']['timeout_minutes'] = 90
    elif damage == 'boolean-budget': request['capacity']['max_tokens_budget'] = False
    elif damage == 'boolean-timeout': request['capacity']['timeout_minutes'] = False
    elif damage == 'single-file-source': raw['groups'] = [{'files': [x['path']]} for x in items]
    elif damage == 'groups': plan['groups'] = [sum(plan['groups'], [])]
    elif damage == 'kind': plan['failure_kind'] = 'budget'
    elif damage == 'superseded-event': payload['source_d1_incomplete_event_id'] = 'second-incomplete'
    elif damage == 'old-label': plan['schema_version'] = 'slk.ocrv-context-recovery-plan/v1'
    write(Path(plan['sources']['request']['path']), request)
    write(Path(plan['sources']['raw_review']['path']), raw)
    rows[-1]['run_manifest'] = raw['manifest']
    session = Path(plan['sources']['session_record']['path'])
    session.write_text(''.join(json.dumps(x) + '\n' for x in rows), encoding='utf-8')
    for key, source in plan['sources'].items():
        plan['sources'][key] = ref(Path(source['path']))
    if damage == 'source-hash': plan['sources']['raw_review']['sha256'] = 'a' * 64
    if damage == 'result-hash':
        result_path = Path(plan['sources']['result']['path'])
        value = json.loads(result_path.read_text()); value['request_sha256'] = 'f' * 64
        write(result_path, value); plan['sources']['result'] = ref(result_path)
    # Rebind the request hash for capacity/scope cases so the narrow checks, not stale hashes, reject them.
    if damage != 'result-hash':
        result_path = Path(plan['sources']['result']['path'])
        value = json.loads(result_path.read_text()); value['request_sha256'] = plan['sources']['request']['sha256']
        write(result_path, value); plan['sources']['result'] = ref(result_path)
    with pytest.raises(ValueError):
        validate(plan, current, payload)


def original_scope_fixture(tmp_path):
    """Original partial18 followed by a real rework commit touching only8."""
    original, original_path, old_plan, old_items = context_fixture(tmp_path)
    repository = Path(original.payload['candidate_payload']['repository'])
    old_request = json.loads(Path(old_plan['sources']['request']['path']).read_text())
    old_raw = json.loads(Path(old_plan['sources']['raw_review']['path']).read_text())
    paths = [x['path'] for x in old_items[:8]]
    for path in paths:
        (repository / path).write_text('fn corrected() {}\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(repository), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repository), 'commit', '-qm', 'rework'], check=True, capture_output=True)
    head = subprocess.run(['git', '-C', str(repository), 'rev-parse', 'HEAD'], check=True, capture_output=True).stdout.decode().strip()
    payload = {**original.payload['candidate_payload'], 'candidate': {'kind': 'commit', 'commit': head},
        'evidence_files': [str(write(tmp_path / 'current-evidence.json', {'next_payload': {'changed_paths': paths}}))]}
    returned_payload = {**original.payload, 'candidate_payload': payload,
        'candidate_payload_sha256': canonical_json_sha256(payload), 'candidate_message_id': 'current-candidate',
        'source_d1_incomplete_event_id': 'current-incomplete'}
    returned = Envelope.from_dict({**original.__dict__, 'payload': returned_payload,
        'payload_sha256': canonical_json_sha256(returned_payload)})
    request = OcrvAdapter()._candidate_request(returned)
    request['capacity']['max_tokens'] = 32000
    input_value, items = native_input(repository, head, paths)
    raw = copy.deepcopy(old_raw)
    raw.update(status='failed', session_id='current-session', comments=[], groups=[{'files': paths}])
    raw['manifest'].update(run_id='current-session', terminal_state='failed', input=input_value)
    raw['manifest']['coverage'].update(selected=items, completed=[], reused=[], failed=[{**x,
        'classification': 'budget', 'reason': 'prompt exceeded the configured token budget'} for x in items])
    root = tmp_path / 'current-source'
    source_request = write(root / 'ocrv-request.json', request)
    source_raw = write(root / 'ocrv-review.json', raw)
    result = json.loads(Path(old_plan['sources']['result']['path']).read_text())
    result.update(request_sha256=ref(source_request)['sha256'], findings=[],
        reason_codes=['OCR_EXIT_1', 'OCR_STATUS_NOT_COMPLETE', 'OCR_COVERAGE_INCOMPLETE'],
        artifacts={'raw_review': str(source_raw)})
    result['review'].update(status='failed', session_id='current-session', exit_code=1)
    source_result = write(root / 'ocrv-result.json', result)
    rows = [{'type': 'session_start', 'sessionId': 'current-session', 'parentUuid': None, 'diffCommit': head,
        'cwd': str(repository), 'reviewMode': 'commit', 'model': 'qwen3.8-max', 'llmSource': 'provider:dashscope-tokenplan'}]
    rows += [{'type': 'review_item_failed', 'sessionId': 'current-session', 'filePath': x['path'],
        'fingerprint': x['fingerprint'], 'model': 'qwen3.8-max',
        'error': 'prompt tokens (26017) exceed 80% of max_tokens(32000) [round 1]'} for x in items]
    rows.append({'type': 'session_end', 'sessionId': 'current-session', 'run_manifest': raw['manifest']})
    session = root / 'current-session.jsonl'
    session.write_text(''.join(json.dumps(x) + '\n' for x in rows), encoding='utf-8')
    full_input, full_items = native_input(repository, head, [x['path'] for x in old_items],
        old_raw['manifest']['input']['resolved_base'])
    plan = {'schema_version': 'slk.ocrv-context-recovery-plan/v3', 'failure_kind': 'ORIGINAL_SCOPE_AT_CURRENT_CANDIDATE',
        'run_id': returned.run_id, 'cell_id': returned.cell_id,
        'candidate_message_id': returned_payload['candidate_message_id'],
        'source_d1_incomplete_event_id': returned_payload['source_d1_incomplete_event_id'],
        'sources': {k: ref(p) for k, p in {'request': source_request, 'result': source_result,
            'raw_review': source_raw, 'session_record': session}.items()},
        'original_plan': ref(original_path), 'review_input': full_input,
        'background_evidence': [ref(Path(p)) for p in dict.fromkeys(old_request['evidence_files'] + request['evidence_files'])],
        'groups': [[x['path']] for x in full_items]}
    plan_path = write(tmp_path / 'current-plan.json', plan)
    returned_payload['management_evidence_refs'] = [str(plan_path)]
    returned = Envelope.from_dict({**returned.__dict__, 'payload': returned_payload,
        'payload_sha256': canonical_json_sha256(returned_payload)})
    return returned, plan_path, plan, request, full_items, old_plan


def test_original_scope_native_range_identity_keeps_current_head(tmp_path):
    from slk_transport.context_review import git_identities
    _env, _path, plan, request, items, _old = original_scope_fixture(tmp_path)
    review_request = {**request, 'candidate': {'kind': 'range', 'from': plan['review_input']['requested_from'],
        'to': request['candidate']['commit']}}
    assert git_identities(review_request, plan['review_input'], None) == {x['path']: x for x in items}


def test_original_scope_is_actually_fresh_reviewed_not_just_in_management_text(tmp_path):
    returned, plan_path, plan, request, items, _old = original_scope_fixture(tmp_path)
    original_candidate = copy.deepcopy(returned.payload['candidate_payload'])
    attempt = AttemptStore(tmp_path / 'attempts').create(returned)
    result = OcrvAdapter().deliver(checker_endpoint(tmp_path, 'context-recovery'), returned, attempt)
    assert result.native_identity['verdict'] == 'PASS'
    children = [json.loads(p.read_text()) for p in sorted((attempt.root / 'review-segments').glob('*/request.json'))]
    assert [x['review_scope']['include_paths'] for x in children] == plan['groups']
    assert len(children) == 18 and len(items) == 18
    assert all(x['candidate'] == {'kind': 'range', 'from': plan['review_input']['requested_from'],
        'to': request['candidate']['commit']} and x['capacity'] == request['capacity']
        and x['d1_criteria'] == request['d1_criteria'] for x in children)
    assert all(plan['original_plan']['sha256'] in x['cell_goal'] and 'file-10.rs' in x['cell_goal'] for x in children)
    aggregate = json.loads((attempt.root / 'ocrv-aggregate.json').read_text())['context_recovery']
    assert aggregate['reused'] == [] and aggregate['not_reviewed_paths'] == []
    assert set(aggregate['reviewed_paths']) == {x['path'] for x in items}
    assert returned.payload['candidate_payload'] == original_candidate
    assert ref(plan_path)['sha256'] == aggregate['plan_sha256']
    from integrations.ocrv.slk_checker_adapter import _validate_request, _background, _review_args
    for child in children:
        native_request = _validate_request(child)
        background = _background(native_request, {'invocations': []})
        assert plan['original_plan']['sha256'] in background and 'file-10.rs' in background
        assert request['cell_goal'] in background and all(x in background for x in request['d1_criteria'])
        args = _review_args(native_request, tmp_path / 'background.md', tmp_path / 'native.json')
        assert args[args.index('--from') + 1] == plan['review_input']['requested_from']
        assert args[args.index('--to') + 1] == request['candidate']['commit']
        assert args[args.index('--max-tokens') + 1] == '32000'


@pytest.mark.parametrize('damage', ['omit-old-path', 'old-head', 'base', 'artifact', 'capacity-source',
    'origin-hash', 'origin-goal', 'origin-manifest', 'background-hash', 'unknown-field'])
def test_original_scope_rejects_drift_before_any_native_call(tmp_path, damage):
    returned, plan_path, plan, _request, _items, old = original_scope_fixture(tmp_path)
    if damage == 'omit-old-path': plan['groups'].pop()
    elif damage == 'old-head': plan['review_input']['resolved_head'] = 'a' * 40
    elif damage == 'base': plan['review_input']['requested_from'] = plan['review_input']['resolved_head']
    elif damage == 'artifact': plan['review_input']['source_artifact_sha256'] = 'a' * 64
    elif damage == 'capacity-source': plan['sources']['request']['sha256'] = 'a' * 64
    elif damage == 'origin-hash': plan['original_plan']['sha256'] = 'a' * 64
    elif damage == 'origin-goal':
        p = Path(old['sources']['request']['path']); value = json.loads(p.read_text()); value['cell_goal'] = 'other CELL'
        write(p, value)
        old['sources']['request'] = ref(p)
        r = Path(old['sources']['result']['path']); result = json.loads(r.read_text())
        result['request_sha256'] = ref(p)['sha256']; write(r, result); old['sources']['result'] = ref(r)
        write(Path(plan['original_plan']['path']), old)
        plan['original_plan'] = ref(Path(plan['original_plan']['path']))
    elif damage == 'origin-manifest':
        p = Path(old['sources']['raw_review']['path']); value = json.loads(p.read_text()); value['manifest']['coverage']['selected'].pop()
        write(p, value)
    elif damage == 'background-hash': plan['background_evidence'][0]['sha256'] = 'a' * 64
    elif damage == 'unknown-field': plan['reuse_old_pass'] = True
    write(plan_path, plan)
    attempt = AttemptStore(tmp_path / 'attempts').create(returned)
    with pytest.raises(AdapterError):
        OcrvAdapter().deliver(checker_endpoint(tmp_path, 'context-recovery'), returned, attempt)
    assert not (Path(returned.payload['candidate_payload']['repository']) / '.fake-ocrv-invocations.jsonl').exists()


@pytest.mark.parametrize('mode', ['context-partial', 'context-scope-leak', 'context-commit-instead'])
def test_original_scope_cannot_pass_missing_or_old_commit_native_coverage(tmp_path, mode):
    returned, _path, _plan, _request, _items, _old = original_scope_fixture(tmp_path)
    attempt = AttemptStore(tmp_path / 'attempts').create(returned)
    if mode == 'context-partial':
        result = OcrvAdapter().deliver(checker_endpoint(tmp_path, mode), returned, attempt)
        assert result.native_identity['verdict'] == 'INCOMPLETE'
        assert len(json.loads((attempt.root / 'ocrv-aggregate.json').read_text())['context_recovery']['not_reviewed_paths']) == 18
    else:
        with pytest.raises(AdapterError):
            OcrvAdapter().deliver(checker_endpoint(tmp_path, mode), returned, attempt)


def test_original_scope_preparer_is_frozen_schema_valid_and_prepare_only(tmp_path, capsys):
    import jsonschema
    from slk_transport.cli import main
    returned, _path, plan, _request, _items, _old = original_scope_fixture(tmp_path)
    output = tmp_path / 'prepared/range.json'
    args = ['prepare-context-review', '--per-call-input-threshold', '--original-scope-plan', plan['original_plan']['path'],
        '--candidate-message-id', plan['candidate_message_id'], '--source-d1-incomplete-event-id',
        plan['source_d1_incomplete_event_id'], '--output', str(output)]
    for key, option in {'request': 'source-request', 'result': 'source-result', 'raw_review': 'raw-review',
        'session_record': 'session-record'}.items():
        args.extend(['--' + option, plan['sources'][key]['path']])
    assert main(args) == 0 and json.loads(output.read_text()) == plan
    assert json.loads(capsys.readouterr().out)['groups'] == plan['groups']
    schema = json.loads((Path(__file__).resolve().parents[2] / 'docs/contracts/slk-ocrv-context-recovery.schema.json').read_text())
    jsonschema.validate(plan, schema)
    for damage in ({**plan, 'failure_kind': 'PER_CALL_INPUT_THRESHOLD'}, {k: v for k, v in plan.items() if k != 'original_plan'}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(damage, schema)
    with pytest.raises(RuntimeError, match='evidence already exists'):
        main(args)
    assert main([x for x in args if x != '--per-call-input-threshold']) == 2
    assert not (Path(returned.payload['candidate_payload']['repository']) / '.fake-ocrv-invocations.jsonl').exists()


@pytest.mark.parametrize('mode,verdict', [('context-recovery', 'PASS'), ('context-blocking', 'FAIL'), ('context-partial', 'INCOMPLETE')])
def test_original_scope_real_role_host_consumes_range_as_same_candidate_d1(tmp_path, monkeypatch, mode, verdict):
    from dataclasses import asdict
    from slk_transport import worker_completion as wc, checker_completion, checker_escalation, checker_management
    from slk_transport.role_host import RoleHost
    from slk_transport.dispatcher import dispatch_once
    from test_role_host import prepared_host, host_boundary
    returned, _plan_path, _plan, request, _items, _old = original_scope_fixture(tmp_path)
    endpoint = checker_endpoint(tmp_path, mode)
    (tmp_path / 'host').mkdir()
    host, _source, _incoming = prepared_host(tmp_path / 'host')
    role = host.binding['roles']['checker']
    write(Path(role['endpoint_path']), asdict(endpoint)); role['endpoint_sha256'] = ref(Path(role['endpoint_path']))['sha256']
    host.binding['cells'] = [{'go_id': returned.go_id, 'cell_id': returned.cell_id,
        'payload': {'cell_goal': request['cell_goal'], 'd1_criteria': request['d1_criteria']}}]
    host = RoleHost(host.binding, 'a' * 64)
    terminal = dispatch_once(asdict(endpoint), asdict(returned), tmp_path / 'attempts', adapters={'ocrv-checker': OcrvAdapter()})
    assert terminal.native_identity['verdict'] == verdict
    source = tmp_path / 'attempts' / returned.run_id / returned.message_id
    projection = host_boundary(host, returned)
    projection['runtime_snapshot'].update(runtime_revision=10, token_sequence=returned.token_sequence,
        token_holder_role_instance_id=returned.receiver_role_instance_id, latest_message_id=returned.message_id)
    projection['go_nodes'] = [{'go_id': returned.go_id, 'ordinal': 1, 'cell_nodes': [
        {'cell_id': returned.cell_id, 'ordinal': 1, 'state': 'd1_started', 'attempt': 1}]}]
    event_scope = {'go_id': returned.go_id, 'cell_id': returned.cell_id, 'attempt': 1, 'plan_revision': 1}
    projection['events'] = [
        {**event_scope, 'event_id': 'candidate-start', 'event_type': 'TRANSPORT_STARTED',
            'author_role_instance_id': host.endpoint('worker')['role_instance_id'],
            'details_json': json.dumps({'message_id': returned.payload['candidate_message_id']})},
        {**event_scope, 'event_id': returned.payload['source_d1_incomplete_event_id'], 'event_type': 'D1_INCOMPLETE',
            'author_role_instance_id': returned.receiver_role_instance_id, 'corrects_event_id': None,
            'details_json': json.dumps({'candidate_message_id': returned.payload['candidate_message_id'], 'verdict': 'INCOMPLETE'})},
        {**event_scope, 'event_id': 'management-start', 'event_type': 'TRANSPORT_STARTED',
            'author_role_instance_id': returned.sender_role_instance_id,
            'details_json': json.dumps({'message_id': returned.message_id})}]
    writes, suffixes = [], []
    def state_write(_command, args, *, credential):
        assert credential == 'slk_' + 'c' * 64 and args[0] == 'write'
        event = json.loads(Path(args[args.index('--request') + 1]).read_text()); writes.append(event)
        projection['events'].append({**event, 'author_role_instance_id': event['role_instance_id'],
            'details_json': json.dumps(event['details'])})
        projection['runtime_snapshot'].update(runtime_revision=11, latest_event_id=event['event_id'])
        projection['go_nodes'][0]['cell_nodes'][0]['state'] = 'd1_passed' if verdict == 'PASS' else 'd1_failed'
        return {'status': 'recorded', 'run_id': returned.run_id}
    monkeypatch.setattr(wc, '_run_json_command', state_write)
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _path: 'slk_' + 'c' * 64)
    monkeypatch.setattr(host, 'projection', lambda: projection)
    def suffix(payload, **_kwargs):
        suffixes.append(payload)
        if verdict == 'PASS':
            checker_completion._validate_boundary(payload)
            assert payload['payload']['final_candidate_message_id'] == returned.payload['candidate_message_id']
        elif verdict == 'FAIL':
            checker_escalation._validate_failure(payload)
        else:
            checker_management._validate_incomplete(payload)
        return {'status': 'CHECKER_TEST_SUFFIX_VALIDATED'}
    monkeypatch.setattr(checker_completion, 'execute_checker_completion', suffix)
    monkeypatch.setattr(checker_escalation, 'execute_checker_escalation', suffix)
    monkeypatch.setattr(checker_management, 'execute_checker_management', suffix)
    result = host.complete(source)
    assert result['status'] == 'CHECKER_TEST_SUFFIX_VALIDATED' and host.complete(source) == result
    assert len(writes) == len(suffixes) == 1
    assert writes[0]['event_type'] == {'PASS': 'D1_PASSED', 'FAIL': 'D1_FAILED', 'INCOMPLETE': 'D1_INCOMPLETE'}[verdict]
    assert writes[0]['corrects_event_id'] == returned.payload['source_d1_incomplete_event_id']
    assert writes[0]['details']['candidate_message_id'] == returned.payload['candidate_message_id']
    assert writes[0]['details']['native_message_id'] == returned.message_id
    assert returned.payload['candidate_payload']['candidate'] == request['candidate']
