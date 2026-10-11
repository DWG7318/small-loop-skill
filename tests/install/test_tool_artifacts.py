from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.tool_artifacts import ArtifactError, archive_module, restore_module


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
