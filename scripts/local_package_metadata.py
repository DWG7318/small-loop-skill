"""Shared, standard-library-only identity for source and delivered SLK packages."""

from __future__ import annotations

from pathlib import Path


EXPECTED_SKILLS = (
    "small-loop-skill",
    "slk-plan-run",
    "slk-guard-resources",
    "slk-select-models",
    "slk-grill-supervisor",
    "slk-manage-team",
    "slk-replace-member",
    "slk-archive-members",
    "slk-troubleshoot-preflight",
    "slk-troubleshoot-run",
    "slk-overwatch-run",
    "slk-manage-temporal",
    "slk-pause-run",
    "slk-dispatch-cell",
    "slk-execute-cell",
    "slk-check-cell",
    "slk-record-run",
    "slk-rework-cell",
    "slk-adjust-run",
    "slk-recover-communication",
    "slk-close-run",
    "slk-finalize-run",
)
ARTIFACT_NAMES = (
    "slk-bi-desktop.exe",
    "slk-bi-query.exe",
    "slk-cargo.exe",
    "slk-state.exe",
    "slk-transport.pyz",
)
LAUNCHER_NAMES = (
    "slk-transport.cmd", "dsh-slk.cmd", "slk-checker.cmd", "slk-temporal.cmd",
    "slk-temporal-worker.cmd", "slk-temporal-start.cmd", "slk-temporal-admit.cmd",
    "slk-temporal-delivery.cmd", "slk-temporal-recover.cmd",
)
INSTALL_SCRIPT_NAMES = (
    "install_local.ps1",
    "verify_local_install.py",
    "local_package_metadata.py",
    "configure_ocrv.py",
)
MANIFEST_SCHEMA = "slk.install-manifest/v1"
PYTHON_RUNTIME_PATH = "tools/slk/runtime/python"
RUNTIME_PATHS = tuple(f"tools/slk/runtime/{name}" for name in ("python", "node", "dsh", "ocrv", "temporal", "git", "native-probe"))
RUNTIME_REQUIRED_FILES = {
    "node": {"node.exe", "LICENSE"},
    "dsh": {"package.json", "package-lock.json", "node_modules/@deepseek-ai/dsh/lib/bin.js",
            "node_modules/@deepseek-ai/dsh/LICENSE"},
    "ocrv": {"bin/opencodereview.exe", "package.json", "LICENSE"},
    "temporal": {"temporal.exe", "LICENSE"},
    "git": {"cmd/git.exe", "ucrt64/bin/git.exe", "usr/bin/sh.exe", "LICENSE.txt"},
    "native-probe": {"artifacts/windows-amd64/slk-native-probe.exe", "dsh/register.mjs",
                     "dsh/activity.mjs", "dsh/probe.mjs", "LICENSE"},
}
PYTHON_IMPORT_PATHS = (
    ".",
    "../../scripts",
    "../../bin/slk-transport.pyz",
    "../../share/small-loop-skill/integrations/temporal/src",
    "Lib/site-packages",
)


def python_path_contents(stdlib_zip: str) -> str:
    """Keep the embed isolated; all SLK imports are relative to the interpreter."""
    return "\n".join((stdlib_zip, *PYTHON_IMPORT_PATHS)) + "\n"


def read_version() -> str:
    """Read the version owned by this source tree or delivered script directory."""
    scripts = Path(__file__).resolve().parent
    if scripts.parent.name.lower() == "slk" and scripts.parent.parent.name.lower() == "tools":
        version_path = scripts.parent / "share/small-loop-skill/VERSION"
    else:
        version_path = scripts.parent / "VERSION"
    return version_path.read_text(encoding="utf-8").strip()
