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
