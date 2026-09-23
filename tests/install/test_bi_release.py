from __future__ import annotations

import re
import json
import tomllib
from pathlib import Path

import pytest

from scripts.verify_bi_release import BiReleaseError, verify_bi_release


ROOT = Path(__file__).resolve().parents[2]


def test_bi_release_declares_custom_protocol_as_the_default() -> None:
    cargo = tomllib.loads(
        (ROOT / "apps/slk-bi/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    )

    assert cargo["features"]["default"] == ["custom-protocol"]
    assert cargo["features"]["custom-protocol"] == ["tauri/custom-protocol"]


def test_release_artifact_builder_uses_tauri_not_plain_cargo_for_bi() -> None:
    script = (ROOT / "scripts/build_release_artifacts.ps1").read_text(encoding="utf-8")
    config = json.loads(
        (ROOT / "apps/slk-bi/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )

    assert config["build"]["beforeBuildCommand"] == "pnpm build:ui"
    assert re.search(r"tauri\s+build\s+--no-bundle", script)
    assert not re.search(r"cargo.+build.+slk-bi-desktop", script, re.IGNORECASE)
    assert ".cargo\\bin\\cargo.exe" in script
    assert '$env:PATH = "$(Split-Path -Parent $cargo);$env:PATH"' in script


def test_release_verifier_rejects_vite_development_assets(tmp_path: Path) -> None:
    executable = tmp_path / "slk-bi-desktop.exe"
    executable.write_bytes(b"MZ" + b"x" * 1_000_000 + b"@vite/client/src/main.tsx")

    with pytest.raises(BiReleaseError, match="development asset markers"):
        verify_bi_release(executable)


def test_release_verifier_requires_a_custom_protocol_fingerprint(tmp_path: Path) -> None:
    executable = tmp_path / "slk-bi-desktop.exe"
    executable.write_bytes(b"MZ" + b"x" * 1_000_000 + b"http://localhost:1430")
    fingerprint = tmp_path / "fingerprints/slk-bi-desktop-release"
    fingerprint.mkdir(parents=True)
    record = fingerprint / "bin-slk-bi-desktop.json"
    record.write_text(
        json.dumps(
            {
                "features": ["custom-protocol", "default"],
                "declared_features": ["custom-protocol", "default"],
            }
        ),
        encoding="utf-8",
    )

    result = verify_bi_release(
        executable, fingerprint_root=tmp_path / "fingerprints"
    )
    assert result["status"] == "PASS"
    assert result["production_fingerprint"] == str(record.resolve())

    record.write_text(
        json.dumps({"features": [], "declared_features": ["custom-protocol", "default"]}),
        encoding="utf-8",
    )
    with pytest.raises(BiReleaseError, match="custom-protocol"):
        verify_bi_release(executable, fingerprint_root=tmp_path / "fingerprints")
