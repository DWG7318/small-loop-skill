from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.tool_artifacts import ArtifactError, archive_module, restore_module
from scripts import tool_artifacts
from scripts.local_package_metadata import ARTIFACT_NAMES


def test_archives_are_deterministic_and_restore_exact_bytes(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    (prefix / "source.rs").write_text("fn main() {}\n", encoding="utf-8")
    binary = tmp_path / "compiled.exe"
    binary.write_bytes(bytes(range(256)) * 20)
    first = archive_module(prefix, "windows-x86_64", {"bin/tool.exe": binary},
                           tool="tool", product_version="1.0.0", part_bytes=97)
    saved = {p.name: p.read_bytes() for p in first.iterdir()}
    copied = tmp_path / "copy"
    copied.mkdir()
    (copied / "source.rs").write_bytes((prefix / "source.rs").read_bytes())
    second = archive_module(copied, "windows-x86_64", {"bin/tool.exe": binary},
                            tool="tool", product_version="1.0.0", part_bytes=97)
    assert saved == {p.name: p.read_bytes() for p in second.iterdir()}
    output = restore_module(first, tmp_path / "restored")
    assert (output / "bin/tool.exe").read_bytes() == binary.read_bytes()
    metadata = json.loads((first / "ARTIFACTS.json").read_text(encoding="utf-8"))
    assert metadata["source_sha256"].keys() == {"source.rs"}
    assert len(metadata["archive"]["parts"]) > 1


def test_corrupt_archive_is_rejected_before_any_payload_write(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    binary = tmp_path / "compiled.exe"
    binary.write_bytes(b"real generated artifact example")
    archived = archive_module(prefix, "windows-x86_64", {"tool.exe": binary},
                              tool="tool", product_version="1.0.0")
    part = next(archived.glob("*.zip"))
    part.write_bytes(part.read_bytes() + b"corrupt")
    with pytest.raises(ArtifactError, match="archive part"):
        restore_module(archived, tmp_path / "restored")
    assert not (tmp_path / "restored/tool.exe").exists()


def test_restore_preserves_nonempty_destination_without_partial_writes(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    binary = tmp_path / "compiled.exe"
    binary.write_bytes(b"compiled output")
    archived = archive_module(prefix, "windows-x86_64", {"a.exe": binary, "z.exe": binary},
                              tool="tool", product_version="1.0.0")
    output = tmp_path / "owner"
    output.mkdir()
    (output / "z.exe").write_bytes(b"owner data")
    with pytest.raises(ArtifactError, match="absent or empty"):
        restore_module(archived, output)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {"z.exe": b"owner data"}


def test_archive_records_build_provenance_in_portable_lf_index(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    binary = tmp_path / "compiled.exe"
    binary.write_bytes(b"compiled output")
    build = {"command": ["cargo", "build", "--release", "--locked"],
             "toolchain": "rustc 1.94.0", "source_hash_mode": "sha256-raw"}
    archived = archive_module(prefix, "windows-x86_64", {"tool.exe": binary},
                              tool="tool", product_version="1.0.0", build=build)
    raw = (archived / "ARTIFACTS.json").read_bytes()
    assert b"\r" not in raw
    assert json.loads(raw)["build"] == build


@pytest.mark.skipif(shutil.which("git") is None, reason="Git source inventory test")
def test_source_hashes_do_not_read_ignored_developer_data(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    subprocess.run(["git", "init", "--quiet", str(prefix)], check=True)
    (prefix / ".gitignore").write_text("private-cache/\n", encoding="utf-8")
    (prefix / "source.rs").write_text("fn main() {}\n", encoding="utf-8")
    private = prefix / "private-cache"
    private.mkdir()
    (private / "account.json").write_bytes(b"private fixture, not a build input")
    binary = tmp_path / "compiled.exe"
    binary.write_bytes(b"compiled output")
    archived = archive_module(prefix, "windows-x86_64", {"tool.exe": binary},
                              tool="tool", product_version="1.0.0")
    metadata = json.loads((archived / "ARTIFACTS.json").read_text(encoding="utf-8"))
    assert set(metadata["source_sha256"]) == {".gitignore", "source.rs"}


@pytest.mark.parametrize("relative", ["../owner.txt", "C:/owner.txt", "bin/../../owner.txt"])
def test_archive_never_accepts_escape_payload_paths(tmp_path: Path, relative: str) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    binary = tmp_path / "compiled.exe"
    binary.write_bytes(b"artifact")
    with pytest.raises(ArtifactError, match="relative"):
        archive_module(prefix, "windows-x86_64", {relative: binary},
                       tool="tool", product_version="1.0.0")
    assert not (prefix / "artifacts").exists()


def release_source_fixture(root):
    for name, content in {
        "VERSION": "4.5.1\n", "Cargo.toml": "[workspace]\n", "Cargo.lock": "version = 4\n",
        "crates/slk-state-core/src/lib.rs": "pub fn value() {}\n",
        "crates/slk-state-core/migrations/0001.sql": "CREATE TABLE fixture (id);\n",
        "src/slk_transport/__init__.py": "# fixture transport\n",
        "src/slk_overwatch_tools/__init__.py": "# fixture helper\n",
        "apps/slk-bi/src/App.tsx": "export const fixture = 1;\n",
        "apps/slk-bi/src/App.test.tsx": "test-only fixture\n",
        "apps/slk-bi/package.json": "{}\n", "apps/slk-bi/pnpm-lock.yaml": "lockfileVersion: 9\n",
        "apps/slk-bi/src-tauri/tauri.conf.json": "{}\n",
        "docs/release.md": "documentation fixture\n", "tests/test_fixture.py": "# test-only\n",
    }.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def fixture_release_bytes(root):
    """Package inventory fixtures only, never compiled production artifacts."""
    for name in ARTIFACT_NAMES:
        (root / name).write_bytes(("SIMULATED INVENTORY ONLY: " + name).encode())


def test_release_freezes_inputs_before_build_and_rejects_midbuild_source_change(tmp_path):
    repo = release_source_fixture(tmp_path / "repo")
    output = tmp_path / "artifacts"
    evidence = tool_artifacts.begin_release_build(repo, output, build={"commands": ["fixture-only"]})
    captured = evidence.read_bytes()
    fixture_release_bytes(output)
    (repo / "crates/slk-state-core/src/lib.rs").write_text("pub fn changed() {}\n")
    with pytest.raises(ArtifactError, match="build inputs changed"):
        tool_artifacts.seal_release_build(repo, output)
    assert evidence.read_bytes() == captured


@pytest.mark.parametrize("changed", ["docs/release.md", "tests/test_fixture.py", "apps/slk-bi/src/App.test.tsx"])
def test_docs_and_tests_only_do_not_invalidate_compiled_release(tmp_path, changed):
    repo = release_source_fixture(tmp_path / "repo")
    output = tmp_path / "artifacts"
    tool_artifacts.begin_release_build(repo, output, build={"commands": ["fixture-only"]})
    fixture_release_bytes(output)
    (repo / changed).write_text("edited non-build material\n")
    evidence = tool_artifacts.seal_release_build(repo, output)
    result = tool_artifacts.verify_release_build(repo, output)
    assert result == json.loads(evidence.read_text())
    assert {entry["path"] for entry in result["payload"]} == set(ARTIFACT_NAMES)
    assert changed not in result["source_sha256"]


@pytest.mark.parametrize("damage", ["artifact", "source", "added-source", "other-checkout"])
def test_release_rejects_mutated_bytes_or_wrong_current_build_source(tmp_path, damage):
    repo = release_source_fixture(tmp_path / "repo")
    output = tmp_path / "artifacts"
    tool_artifacts.begin_release_build(repo, output, build={"commands": ["fixture-only"]})
    fixture_release_bytes(output)
    tool_artifacts.seal_release_build(repo, output)
    if damage == "artifact":
        (output / "slk-state.exe").write_bytes(b"different simulated inventory")
    elif damage == "source":
        (repo / "src/slk_transport/__init__.py").write_text("# changed compiled input")
    elif damage == "added-source":
        (repo / "src/slk_transport/added.py").write_text("# new compiled input")
    else:
        repo = release_source_fixture(tmp_path / "other")
        (repo / "Cargo.lock").write_text("different dependency graph\n")
    with pytest.raises(ArtifactError, match="(build inputs changed|payload changed)"):
        tool_artifacts.verify_release_build(repo, output)


def test_release_script_captures_before_any_build_and_seals_after_all_five_outputs():
    script = (Path(__file__).parents[2] / "scripts/build_release_artifacts.ps1").read_text()
    assert script.index("begin-release") < script.index("tauri build --no-bundle")
    assert script.index("seal-release") > script.index('"BI release verification"')


def test_release_script_uses_one_explicit_target_for_compile_and_artifact_copy():
    script = (Path(__file__).parents[2] / "scripts/build_release_artifacts.ps1").read_text()
    selection_end = script.index("Push-Location $repo")
    selected = script[:selection_end].splitlines()
    assert selected[-2] == "$env:CARGO_TARGET_DIR = $target"


def test_release_sealing_preserves_an_existing_incomplete_index(tmp_path):
    repo = release_source_fixture(tmp_path / "repo")
    output = tmp_path / "artifacts"
    evidence = tool_artifacts.begin_release_build(repo, output, build={"commands": ["fixture-only"]})
    captured = evidence.read_bytes()
    unfinished = evidence.with_suffix(".json.tmp")
    unfinished.write_bytes(b"preserved unfinished build evidence")
    with pytest.raises(FileExistsError):
        tool_artifacts._save_release_index(evidence, {"fixture": True}, replace=True)
    assert evidence.read_bytes() == captured
    assert unfinished.read_bytes() == b"preserved unfinished build evidence"


@pytest.mark.skipif(shutil.which("git") is None, reason="Git ignore boundary test")
def test_release_inventory_captures_ignored_python_that_zipapp_would_include(tmp_path):
    repo = release_source_fixture(tmp_path / "repo")
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / ".gitignore").write_text("src/slk_transport/ignored_runtime.py\n")
    compiled_input = repo / "src/slk_transport/ignored_runtime.py"
    compiled_input.write_text("# included by the actual zipapp builder\n")
    output = tmp_path / "artifacts"
    evidence = tool_artifacts.begin_release_build(repo, output, build={"commands": ["fixture-only"]})
    assert "src/slk_transport/ignored_runtime.py" in json.loads(evidence.read_text())["source_sha256"]
    fixture_release_bytes(output)
    compiled_input.write_text("# changed runtime code\n")
    with pytest.raises(ArtifactError, match="build inputs changed"):
        tool_artifacts.seal_release_build(repo, output)
