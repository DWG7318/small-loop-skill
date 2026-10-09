"""Offline MCP protocol tests; no OCRV model or production state is started."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def bridge():
    path = Path(__file__).resolve().parents[2] / 'integrations/ocrv/slk_checker_decision.py'
    spec = importlib.util.spec_from_file_location('checker_decision_bridge', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(params):
    return {'jsonrpc':'2.0', 'id':3, 'method':'tools/call', 'params':params}


def test_tool_explains_whole_candidate_authority_not_group_completion(bridge):
    description = bridge.TOOL['description']
    for marker in ('entire frozen candidate', 'not a file/group verdict',
                   'Do not submit once per group', 'do not claim whole-CELL PASS'):
        assert marker in description


def test_discovery_and_notifications_do_not_decide_d1(bridge):
    no_action = lambda *_: pytest.fail('no explicit action')
    assert bridge.respond({'id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26'}}, no_action)['result']['capabilities'] == {'tools':{}}
    tools = bridge.respond({'id':2,'method':'tools/list'}, no_action)['result']['tools']
    assert [tool['name'] for tool in tools] == ['slk_checker_decide']
    assert bridge.respond({'method':'notifications/initialized'}, no_action) is None


@pytest.mark.parametrize('verdict', ['PASS','FAIL','INCOMPLETE'])
def test_only_explicit_decision_reaches_existing_action(bridge, verdict):
    actions = []
    def record(value):
        actions.append(value)
        return {'status':'CHECKER_D1_RECORDED','verdict':value}
    result = bridge.respond(call({'name':'slk_checker_decide','arguments':{'verdict':verdict}}), record)
    assert actions == [verdict]
    assert json.loads(result['result']['content'][0]['text'])['verdict'] == verdict


@pytest.mark.parametrize('params', [
    {'name':'shell','arguments':{'command':'anything'}},
    {'name':'slk_checker_decide','arguments':{}},
    {'name':'slk_checker_decide','arguments':{'verdict':'PASS','source':'other'}},
    {'name':'slk_checker_decide','arguments':{'verdict':'maybe'}},
])
def test_no_generic_executor_or_implicit_decision(bridge, params):
    result = bridge.respond(call(params), lambda *_: pytest.fail('invalid action'))
    assert result['result']['isError'] is True


def test_tool_failure_is_not_reported_as_recorded_verdict(bridge):
    def fail(_):
        raise ValueError('ROLE_HOST_AUTHORITY_INVALID')
    result = bridge.respond(call({'name':'slk_checker_decide','arguments':{'verdict':'PASS'}}), fail)
    assert result['result']['isError'] is True
    assert 'CHECKER_D1_RECORDED' not in json.dumps(result)


def test_unbound_invocation_cannot_write_state(bridge, monkeypatch):
    monkeypatch.delenv('SLK_NATIVE_START_RECEIPT', raising=False)
    with pytest.raises(ValueError, match='CALLER_UNPROVEN'):
        bridge.record('PASS')


@pytest.mark.parametrize('method', ['initialize', 'tools/call'])
def test_invalid_protocol_params_do_not_crash_or_call_action(bridge, method):
    result = bridge.respond({'jsonrpc':'2.0','id':4,'method':method,'params':[]},
                            lambda *_: pytest.fail('invalid protocol called action'))
    assert result['error']['code'] == -32602


@pytest.mark.parametrize('receipt', ['', 'not-an-invocation.json'])
def test_stdio_imports_packaged_transport_without_source_pythonpath(tmp_path, receipt):
    from scripts.build_transport_zipapp import build_zipapp
    package = build_zipapp(tmp_path / 'slk-transport.pyz')
    script = Path(__file__).resolve().parents[2] / 'integrations/ocrv/slk_checker_decision.py'
    environment = os.environ.copy()
    for key in ('PYTHONPATH', 'SLK_NATIVE_START_RECEIPT', 'SLK_TRANSPORT_ROLE_HOST',
                'SLK_TRANSPORT_ROLE_HOST_SHA256', 'SLK_CONFIG_PATH', 'SLK_ROLE_CREDENTIAL'):
        environment.pop(key, None)
    if receipt:
        environment['SLK_NATIVE_START_RECEIPT'] = str(tmp_path / receipt)
    messages = [{'jsonrpc':'2.0','id':1,'method':'initialize',
                 'params':{'protocolVersion':'2025-03-26'}},
                {'jsonrpc':'2.0','method':'notifications/initialized'},
                {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                call({'name':'slk_checker_decide','arguments':{'verdict':'FAIL'}})]
    completed = subprocess.run([sys.executable, '-B', str(script), '--transport', str(package)],
        input=''.join(json.dumps(value)+'\n' for value in messages), cwd=tmp_path,
        env=environment, text=True, encoding='utf-8', capture_output=True, check=False,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
    assert completed.returncode == 0, completed.stderr
    replies = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [value['id'] for value in replies] == [1,2,3]
    assert replies[1]['result']['tools'][0]['name'] == 'slk_checker_decide'
    assert replies[2]['result']['isError'] is True
    assert 'CHECKER_DECISION_CALLER_UNPROVEN' in replies[2]['result']['content'][0]['text']
    assert not list(tmp_path.rglob('checker-decision.json'))
