from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_direct_core_import_and_version_work_when_temporal_is_unavailable() -> None:
    script = """
import builtins
real_import = builtins.__import__
def blocked_import(name, *args, **kwargs):
    if name == 'temporalio' or name.startswith('temporalio.'):
        raise ModuleNotFoundError('temporalio intentionally unavailable')
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked_import
from slk_transport.cli import VERSION
if VERSION != '4.3.3':
    raise SystemExit(f'wrong direct-mode version: {VERSION}')
print('DIRECT_MODE_OK')
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "DIRECT_MODE_OK"
