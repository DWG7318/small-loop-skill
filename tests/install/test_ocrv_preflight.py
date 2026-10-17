from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "integrations" / "ocrv" / "slk_checker_adapter.py"


def _sha(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _request(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "a.py").write_text("A = 1\n", encoding="utf-8")
    (repository / "b.py").write_text("B = 2\n", encoding="utf-8")
    evidence = tmp_path / "worker-result.json"
    evidence.write_text(
        json.dumps({"status": "WORKER_SELF_REPORTED_COMPLETE", "test_status": "WORKER_SELF_REPORTED_PASS",
                    "next_payload": {"changed_paths": ["a.py", "b.py"],
                                     "d0": {"conclusion": "WORKER_SELF_REPORTED_D0"}}}),
        encoding="utf-8",
    )
    scope = {
        "include_paths": ["a.py"],
        "exclude_paths": ["b.py"],
        "criterion_ids": ["D1-001"],
    }
    scope["scope_sha256"] = _sha(scope)
    request = {
        "schema_version": "slk.ocrv-d1-request/v2",
        "run_id": "RUN-PREFLIGHT-A",
        "cell_id": "CELL-001",
        "repository": str(repository),
        "candidate": {"kind": "workspace"},
        "cell_goal": "Review only the declared path.",
        "d1_criteria": ["The declared path is correct."],
        "evidence_files": [str(evidence)],
        "review_scope": scope,
        "capacity": {
            "max_background_characters": 8_000,
            "max_background_bytes": 12_000,
            "max_changed_lines": 800,
            "max_segment_paths": 2,
            "max_tokens": 200_000,
            "max_tokens_budget": 500_000,
            "timeout_minutes": 15,
        },
    }
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "preflight.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    return request_path, output_path, repository


def _fake_ocr(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "ocr-args.json"
    script = tmp_path / "fake_ocr.py"
    script.write_text(
        """from __future__ import annotations
import json, os, re, sys, time, unicodedata
from pathlib import Path
args = sys.argv[1:]
Path(os.environ['FAKE_OCR_LOG']).write_text(json.dumps(args), encoding='utf-8')
# Mirror pinned OCRV loadBackgroundFile, not the adapter's advisory capacity.
# The optional receipt handshake lets the real adapter publish its native start.
if '--preview' not in args and os.environ.get('SLK_NATIVE_START_RECEIPT'):
    source = Path(os.environ['SLK_NATIVE_START_RECEIPT']).with_name('ocrv-native-source.json')
    deadline = time.monotonic() + 5
    while not source.exists() and time.monotonic() < deadline:
        time.sleep(.01)
raw = Path(args[args.index('--background-file') + 1]).read_bytes()
cleaned = ''.join(char for char in raw.decode('utf-8') if char in '\\n\\t' or
                  (ord(char) > 31 and not 127 <= ord(char) <= 159 and unicodedata.category(char) != 'Cf'))
cleaned = re.sub(r'\\n{3,}', '\\n\\n', cleaned).strip()
if len(raw) > 1024 * 1024 or len(cleaned) > 8000:
    print('native background hard limit exceeded', file=sys.stderr)
    sys.exit(4)
output = Path(args[args.index('--output') + 1])
excluded = set(args[args.index('--exclude') + 1].split(',')) if '--exclude' in args else set()
files = [
    {'path': path, 'status': 'modified', 'insertions': 1, 'deletions': 0,
     'will_review': path not in excluded, 'exclude_reason': 'cli_exclude' if path in excluded else None}
    for path in ('a.py', 'b.py')
]
output.write_text(json.dumps({'files': files, 'total_insertions': 2, 'total_deletions': 0,
                              'total_files': 2, 'reviewable_count': 1, 'excluded_count': 1}), encoding='utf-8')
""",
        encoding="utf-8",
    )
    return script, log


def _run(request: Path, output: Path, runtime: Path, fake: Path, log: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["OCRV_SLK_COMMAND_JSON"] = json.dumps([sys.executable, str(fake)])
    environment["OCRV_SLK_RUNTIME_ROOT"] = str(runtime)
    environment["FAKE_OCR_LOG"] = str(log)
    return subprocess.run(
        [sys.executable, str(ADAPTER), "--preflight", "--request", str(request), "--output", str(output)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )


def test_checker_background_decision_is_whole_candidate_not_native_file_group(tmp_path: Path) -> None:
    request, output, _repository = _request(tmp_path)
    fake, log = _fake_ocr(tmp_path)
    assert _run(request, output, tmp_path / "runtime", fake, log).returncode == 0
    arguments = json.loads(log.read_text(encoding="utf-8"))
    background = Path(arguments[arguments.index("--background-file") + 1]).read_text(encoding="utf-8")
    for marker in ("entire frozen candidate", "not the current file or native group",
                   "file_find", "file_read_diff", "Do not submit one decision per group",
                   "cannot establish all CELL goals", "do not claim whole-CELL PASS"):
        assert marker in background


def test_current_request_capacity_omits_retired_advisories_but_legacy_request_still_reads(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('capacity_adapter', ADAPTER)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    request, _, _ = _request(tmp_path)
    value = json.loads(request.read_text())
    legacy = adapter._validate_request(value)
    value['capacity'] = {name: value['capacity'][name] for name in ('max_tokens', 'max_tokens_budget', 'timeout_minutes')}
    current = adapter._validate_request(value)
    assert adapter._background(current) == adapter._background(legacy)


def test_installed_adapter_preflight_uses_exact_exclude_scope_without_model(tmp_path: Path) -> None:
    request, output, _repository = _request(tmp_path)
    evidence = tmp_path / "worker-result.json"
    original_evidence = evidence.read_bytes()
    fake, log = _fake_ocr(tmp_path)
    runtime = tmp_path / "runtime"

    completed = _run(request, output, runtime, fake, log)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "READY"
    assert result["preview"]["selected_paths"] == ["a.py"]
    arguments = json.loads(log.read_text(encoding="utf-8"))
    assert "--preview" in arguments
    assert arguments[arguments.index("--max-tools") + 1] == "0"
    assert arguments[arguments.index("--exclude") + 1] == "b.py"
    assert arguments[arguments.index("--concurrency") + 1] == "1"
    background = next(runtime.rglob("d1-background.md")).read_text(encoding="utf-8")
    assert 'slk_read_evidence(0)' in background
    assert 'slk_read_evidence(1)' in background
    assert request.read_text(encoding="utf-8") not in background
    assert '"b.py"' not in background
    assert "WORKER_SELF_REPORTED" not in background
    assert '"test_status"' not in background
    assert "before reading relevant Worker D0 originals" in background
    assert "select relevant indexed originals" in background
    assert evidence.read_bytes() == original_evidence


@pytest.mark.parametrize('material', ['goal', 'criteria', 'locators', 'management', 'bytes'])
def test_native_gate_accepts_bootstrap_without_limiting_original_material(tmp_path, material):
    request, output, _ = _request(tmp_path)
    value = json.loads(request.read_text(encoding='utf-8'))
    long_text = '完整原文🙂' * (70_000 if material == 'bytes' else 1800) + 'END-OF-MATERIAL'
    if material in {'goal', 'bytes'}:
        value['cell_goal'] = long_text
    elif material == 'criteria':
        value['d1_criteria'] = [long_text]
    elif material == 'management':
        value['management_context'] = {'management_action': 'SUPPLY_EVIDENCE',
            'management_summary': long_text, 'management_evidence_refs': value['evidence_files']}
    else:
        value['evidence_refs'] = [{'path': str(tmp_path / f'original-{i}-END-OF-MATERIAL.log'),
                                   'sha256': 'a' * 64} for i in range(120)]
    request.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\r\n')
    original = request.read_bytes()
    if material == 'bytes':
        assert len(original) > 1024 * 1024
    fake, log = _fake_ocr(tmp_path)

    completed = _run(request, output, tmp_path / 'runtime', fake, log)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['status'] == 'READY'
    arguments = json.loads(log.read_text(encoding='utf-8'))
    background_path = Path(arguments[arguments.index('--background-file') + 1])
    background = background_path.read_text(encoding='utf-8')
    assert len(background) < 8000
    assert 'END-OF-MATERIAL' not in background
    assert request.read_bytes() == original
    index = json.loads(background_path.with_name('evidence-index.json').read_text(encoding='utf-8'))
    assert index['evidence'][0]['path'] == str(request.resolve())
    assert index['evidence'][0]['sha256'] == hashlib.sha256(original).hexdigest()


def test_installed_adapter_records_oversized_background_as_advisory(tmp_path: Path) -> None:
    request, output, _repository = _request(tmp_path)
    value = json.loads(request.read_text(encoding="utf-8"))
    value["capacity"]["max_background_characters"] = 10
    request.write_text(json.dumps(value), encoding="utf-8")
    fake, log = _fake_ocr(tmp_path)

    completed = _run(request, output, tmp_path / "runtime", fake, log)

    assert completed.returncode == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "READY"
    assert result["background"]["characters"] > value["capacity"]["max_background_characters"]
    arguments = json.loads(log.read_text(encoding="utf-8"))
    assert "--preview" in arguments
