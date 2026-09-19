import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
BI_ROOT = ROOT / "apps" / "slk-bi"


def test_bi_is_a_read_only_tauri_surface():
    package = json.loads((BI_ROOT / "package.json").read_text(encoding="utf-8"))
    capability = json.loads(
        (BI_ROOT / "src-tauri" / "capabilities" / "default.json").read_text(
            encoding="utf-8"
        )
    )

    assert package["name"] == "slk-bi"
    assert capability["permissions"] == ["core:default"]

    inspected = [
        BI_ROOT / "package.json",
        BI_ROOT / "src-tauri" / "Cargo.toml",
        BI_ROOT / "src-tauri" / "tauri.conf.json",
        BI_ROOT / "src-tauri" / "capabilities" / "default.json",
    ]
    for directory in (BI_ROOT / "src", BI_ROOT / "src-tauri" / "src"):
        inspected.extend(path for path in directory.rglob("*") if path.is_file())
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in inspected
    ).lower()
    for forbidden in (
        "shell:allow",
        "plugin-shell",
        "plugin-http",
        "plugin-updater",
        "allow-write-file",
    ):
        assert forbidden not in source


def test_desktop_and_agent_read_surfaces_share_all_projection_methods():
    commands = (BI_ROOT / "src-tauri" / "src" / "commands.rs").read_text(
        encoding="utf-8"
    )
    query_cli = (ROOT / "crates" / "slk-bi-query" / "src" / "main.rs").read_text(
        encoding="utf-8"
    )
    core = (ROOT / "crates" / "slk-state-core" / "src" / "query.rs").read_text(
        encoding="utf-8"
    )

    views = {
        "projects": "projects_view",
        "runs": "runs_view",
        "run": "run_view",
        "graph": "graph_view",
        "roles": "roles_view",
        "plans": "plans_view",
        "events": "events_view",
        "evidence": "evidence_view",
    }
    for command, method in views.items():
        assert f'"{command}"' in commands
        assert method in commands
        assert method in query_cli
        assert f"pub fn {method}" in core

    combined = f"{commands}\n{query_cli}".lower()
    for secret in ("credential_sha256", "role_credential", "native_address_json"):
        assert secret not in combined
