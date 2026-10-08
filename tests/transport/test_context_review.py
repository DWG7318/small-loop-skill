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
