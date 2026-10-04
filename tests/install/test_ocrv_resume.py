from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from test_ocrv_preflight import ROOT, _request


RECOVERY = ROOT / "integrations" / "ocrv" / "slk_checker_recovery.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_recovery(
    tmp_path: Path,
    *,
    show_payload: object,
    show_exit: int = 0,
    new_session_id: str = "ocrv-session-1",
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], dict[str, object], Path, Path, Path]:
    original, _output, repository = _request(tmp_path)
    original_value = json.loads(original.read_text(encoding="utf-8"))
    original_value["candidate"] = {"kind": "commit", "commit": "b" * 40}
    source = tmp_path / "source-attempt"
    source.mkdir()
    original = source / "ocrv-request.json"
    original.write_text(json.dumps(original_value), encoding="utf-8")
    background = tmp_path / "d1-background.md"
    background.write_text("preserved scope and criteria\n", encoding="utf-8")
    recovery_root = source / "resume-incomplete-checker" / "recovery-1"
    output = recovery_root / "result.json"
    fake_transport = tmp_path / "fake_transport.py"
    fake_transport.write_text(
        "import hashlib,json,sys\nassert sys.argv[1]=='checker-record-committed-terminal'\n"
        "r=json.load(open(sys.argv[sys.argv.index('--request')+1],encoding='utf-8'))\n"
        "assert hashlib.sha256(open(sys.argv[sys.argv.index('--request')+1],'rb').read()).hexdigest()==sys.argv[sys.argv.index('--sha256')+1]\n"
        "assert r['recovery_terminal']['resume_request_sha256']\n"
        "print(json.dumps({'schema_version':'slk.ocrv-committed-terminal-result/v1',"
        "'status':'CHECKER_D1_RECORDED','run_id':r['run_id'],"
        "'checker_role_instance_id':r['checker_role_instance_id'],"
        "'request_sha256':sys.argv[sys.argv.index('--sha256')+1]}))\n",
        encoding="utf-8",
    )
    request = {
        "schema_version": "slk.ocrv-incomplete-checker-resume-request/v1",
        "method_version": "4.4.0", "recovery_invocation_id": "recovery-1",
        "run_id": original_value["run_id"], "go_id": "GO-001", "cell_id": original_value["cell_id"],
        "attempt": 1, "plan_revision": 1, "runtime_revision": 1, "token_sequence": 1,
        "worker_role_instance_id": "worker-1", "checker_role_instance_id": "checker-1",
        "checker_endpoint_version": 1, "checker_endpoint": {"role": "checker"},
        "runtime_projection_path": "unused", "runtime_projection_sha256": "0" * 64,
        "candidate_repository": str(repository), "candidate_commit": "b" * 40,
        "candidate_parent": "a" * 40, "candidate_message_id": "message-1", "payload_sha256": "1" * 64,
        "candidate_submitted_event_id": "candidate-1", "transport_started_event_id": "transport-1",
        "commit_request_path": "unused", "commit_request_sha256": "2" * 64,
        "native_attempt_path": str(source), "checker_credential_path": "unused",
        "state_command": ["unused"], "transport_command": [sys.executable, str(fake_transport)],
        "immutable_sha256": {name: "3" * 64 for name in (
            "endpoint.json", "envelope.json", "started.json", "ocrv-request.json",
        )},
        "result_path": str(output), "background_path": str(background), "recovery_root": str(recovery_root),
        "ocrv_session": {"session_id": "ocrv-session-1", "repo_dir": str(repository.resolve()).replace("\\", "/"),
            "diff_commit": "b" * 40, "model": "qwen3.8-max", "review_mode": "commit",
            "start_time": "2026-10-02T07:21:32Z", "aborted": True, "selected_files": 0, "completed_files": 0},
    }
    request_path = tmp_path / "resume.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    log = tmp_path / "calls.jsonl"
    fake_ocr = tmp_path / "fake_ocr.py"
    fake_ocr.write_text(
        "import json,os,sys\nfrom pathlib import Path\nargs=sys.argv[1:]\n"
        "with Path(os.environ['FAKE_LOG']).open('a',encoding='utf-8') as f:f.write(json.dumps(args)+'\\n')\n"
        "if args[:2]==['session','list']:\n print(json.dumps([{'session_id':'ocrv-session-1','repo_dir':os.environ['FAKE_REPO'].replace('\\\\','/'),"
        "'diff_commit':'" + "b" * 40 + "','model':'qwen3.8-max','review_mode':'commit',"
        "'start_time':'2026-10-02T07:21:32Z','aborted':True,'selected_files':0,'completed_files':0}]))\n sys.exit(0)\n"
        "if args[:2]==['session','show']:\n print(os.environ['FAKE_SHOW_JSON'])\n sys.exit(int(os.environ['FAKE_SHOW_EXIT']))\n"
        "out=Path(args[args.index('--output')+1]);out.write_text(json.dumps({'status':'complete',"
        "'session_id':os.environ['FAKE_NEW_SESSION'],'llm':{'provider':'dashscope-tokenplan','model':'qwen3.8-max'},"
        "'manifest':{'terminal_state':'complete','coverage':{'selected':[{'item_id':'a'}],"
        "'completed':[{'item_id':'a'}],'failed':[],'waived':[]}},'tool_calls':{'failure':0},'comments':[]}),encoding='utf-8')\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update({
        "OCRV_SLK_COMMAND_JSON": json.dumps([sys.executable, str(fake_ocr)]),
        "FAKE_LOG": str(log), "FAKE_REPO": str(repository.resolve()),
        "FAKE_SHOW_JSON": json.dumps(show_payload), "FAKE_SHOW_EXIT": str(show_exit),
        "FAKE_NEW_SESSION": new_session_id,
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID": "checker-1", "SLK_OCRV_RECOVERY_INVOCATION_ID": "recovery-1",
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION": "1",
    })
    completed = subprocess.run(
        [sys.executable, str(RECOVERY), "--slk-resume-incomplete-checker", "--request", str(request_path),
         "--output", str(output)],
        cwd=repository, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False, env=environment,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return completed, calls, request, request_path, background, recovery_root


def _recoverable_show_payload() -> dict[str, object]:
    return {
        "summary": {
            "session_id": "ocrv-session-1",
            "run_manifest": {"terminal_state": "running", "coverage": {"selected": [{"item_id": "a"}]}},
        },
        "items": [{"item_id": "a", "type": "pending"}],
    }


def test_recoverable_session_resumes_same_session_then_delegates_to_committed_terminal(tmp_path: Path) -> None:
    completed, calls, _request_value, request_path, background, recovery_root = _run_recovery(
        tmp_path, show_payload=_recoverable_show_payload()
    )

    assert completed.returncode == 0, completed.stderr
    assert calls[1][:2] == ["session", "show"]
    assert calls[2][calls[2].index("--resume") + 1] == "ocrv-session-1"
    assert calls[2][calls[2].index("--background-file") + 1] == str(background)
    assert (recovery_root / "committed-terminal.json").is_file()
    assert json.loads((recovery_root / "result.json").read_text(encoding="utf-8"))["request_sha256"] == sha256(request_path)


def test_session_without_manifest_or_items_starts_fresh_from_the_frozen_original_input(tmp_path: Path) -> None:
    completed, calls, request, _request_path, background, recovery_root = _run_recovery(
        tmp_path,
        show_payload={"summary": {"session_id": "ocrv-session-1", "run_manifest": None}, "items": None},
        new_session_id="ocrv-session-fresh",
    )

    assert completed.returncode == 0, completed.stderr
    review = calls[2]
    assert "--resume" not in review
    assert review[review.index("--commit") + 1] == request["candidate_commit"]
    assert review[review.index("--background-file") + 1] == str(background)
    assert review[review.index("--provider") + 1] == "dashscope-tokenplan"
    assert review[review.index("--model") + 1] == "qwen3.8-max"
    assert review[review.index("--effort") + 1] == "medium"
    native_attempt = recovery_root / "native-attempt"
    terminal = json.loads((native_attempt / "completed.json").read_text(encoding="utf-8"))
    result = json.loads((native_attempt / "ocrv-result.json").read_text(encoding="utf-8"))
    assert terminal["native_identity"]["review_invocation_id"] == result["review_invocation_id"]
    assert terminal["native_identity"]["review_invocation_id"] != "ocrv-session-1"
    assert terminal["native_identity"]["session_id"] == "ocrv-session-fresh"


def test_session_show_error_does_not_consume_the_one_shot_marker(tmp_path: Path) -> None:
    completed, calls, _request_value, _request_path, _background, recovery_root = _run_recovery(
        tmp_path, show_payload={}, show_exit=9
    )

    assert completed.returncode == 5
    assert calls[1][:2] == ["session", "show"]
    assert len(calls) == 2
    assert not (recovery_root / "resume-consumed.json").exists()
    assert not (recovery_root / "native-attempt").exists()
