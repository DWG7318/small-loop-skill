"""Tiny static inventories, not executable/runtime readiness evidence."""
from pathlib import Path
import os
import shutil


ROOT = Path(__file__).resolve().parents[2]


def prepared_runtimes(root: Path, *, runnable_registration: bool = False) -> dict[str, Path]:
    layouts = {
        "node": ("node.exe", "LICENSE"),
        "dsh": ("package.json", "package-lock.json", "node_modules/@deepseek-ai/dsh/lib/bin.js",
                "node_modules/@deepseek-ai/dsh/LICENSE"),
        "ocrv": ("bin/opencodereview.exe", "package.json", "LICENSE"),
        "temporal": ("temporal.exe", "LICENSE"),
        "git": ("cmd/git.exe", "ucrt64/bin/git.exe", "usr/bin/sh.exe", "LICENSE.txt",
                "usr/share/licenses/fixture/LICENSE"),
        "native-probe": ("artifacts/windows-amd64/slk-native-probe.exe", "dsh/register.mjs",
                         "dsh/activity.mjs", "dsh/probe.mjs", "LICENSE"),
    }
    result = {}
    for name, files in layouts.items():
        directory = root / name
        for relative in files:
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"simulated inventory, not an executable\n")
        result[name.replace("-", "_") + "_runtime"] = directory
    if runnable_registration:
        registration_fixture(root)
    return result


def registration_fixture(root: Path) -> None:
    """Real Node/register transaction with a deliberately fake native parser.

    This tests installer plumbing/rollback only, not native DSH activation or
    its real YAML dialect. The separate native-probe tests use the official host.
    """
    node = os.environ.get("SLK_TEST_NODE_EXE") or shutil.which("node")
    if not node or not Path(node).is_file():
        raise RuntimeError("real Node is required for the registration transaction fixture")
    shutil.copy2(node, root / "node/node.exe")
    (root / "dsh/package.json").write_text('{"name":"slk-registration-contract-fixture","private":true}', encoding="utf-8")
    probe = root / "native-probe"
    (probe / "dsh").mkdir(parents=True, exist_ok=True)
    executable = probe / "artifacts/windows-amd64/slk-native-probe.exe"
    if not executable.is_file():
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b"registration-only inventory, never executed\n")
    for name in ("register.mjs", "activity.mjs", "probe.mjs"):
        shutil.copy2(ROOT / "integrations/native-probe/dsh" / name, probe / "dsh" / name)
    boot = root / "dsh/node_modules/@deepseek-ai/dsh-app-boot"
    boot.mkdir(parents=True, exist_ok=True)
    (boot / "package.json").write_text('{"type":"module","main":"index.mjs"}', encoding="utf-8")
    (boot / "index.mjs").write_text(
        'import {readFileSync} from "node:fs";\n'
        'export function loadOptionalPatches(label,path){'
        'const text=readFileSync(path,"utf8");'
        'if(text.includes("INVALID_YAML_FIXTURE"))throw Error("fixture parser rejection");'
        'return [];}\n'
        'export const loadOverlayPatches=loadOptionalPatches;\n', encoding="utf-8")
