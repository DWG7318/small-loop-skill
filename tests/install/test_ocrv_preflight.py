from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


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
        json.dumps({"status": "completed", "next_payload": {"changed_paths": ["a.py", "b.py"]}}),
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
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
Path(os.environ['FAKE_OCR_LOG']).write_text(json.dumps(args), encoding='utf-8')
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


def test_installed_adapter_preflight_uses_exact_exclude_scope_without_model(tmp_path: Path) -> None:
    request, output, _repository = _request(tmp_path)
    fake, log = _fake_ocr(tmp_path)
    runtime = tmp_path / "runtime"

    completed = _run(request, output, runtime, fake, log)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "READY"
    assert result["preview"]["selected_paths"] == ["a.py"]
    arguments = json.loads(log.read_text(encoding="utf-8"))
    assert "--preview" in arguments
    assert arguments[arguments.index("--exclude") + 1] == "b.py"
    assert arguments[arguments.index("--concurrency") + 1] == "1"
    background = next(runtime.rglob("d1-background.md")).read_text(encoding="utf-8")
    assert '"changed_paths": ["a.py"]' in background
    assert '"b.py"' not in background


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
