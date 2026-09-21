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
    assert set(capability["permissions"]) == {
        "core:default",
        "core:window:allow-start-dragging",
        "core:window:allow-minimize",
        "core:window:allow-close",
        "core:window:allow-set-always-on-top",
        "core:window:allow-set-size",
    }

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


def test_bi_window_is_compact_and_not_maximizable():
    config = json.loads(
        (BI_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    window = config["app"]["windows"][0]

    assert window["width"] <= 960
    assert window["maximizable"] is False
    assert window["minimizable"] is True
    assert window["closable"] is True
    assert window["decorations"] is False
    assert window["title"] == "LE BI"


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
