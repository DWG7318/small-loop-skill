"""Retired implicit review recovery must be an inert, explicit rejection."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize("operation", ["--slk-worker-recovery", "--slk-resume-incomplete",
    "--slk-existing-terminal", "--slk-committed-terminal", "--slk-terminal-budget"])
def test_retired_launcher_cannot_resume_review_or_mutate_history(tmp_path, operation):
    source = tmp_path/"original.json"
    source.write_bytes(b'original non-JSON report\r\n')
    output = tmp_path/"result.json"
    result = subprocess.run([sys.executable, "-B",
        str(ROOT/"integrations/ocrv/slk_checker_recovery.py"), operation,
        "--request", str(source), "--output", str(output)],
        capture_output=True, text=True, check=False)
    assert result.returncode == 64
    assert json.loads(result.stdout)["error_code"] == "OUTPUT_REVIEW_RECOVERY_RETIRED"
    assert source.read_bytes() == b'original non-JSON report\r\n'
    assert not output.exists()
