#!/usr/bin/env python3
"""Reject an LE BI release executable that still points at Vite development assets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


DEV_MARKERS = (
    "@vite/client",
    "/src/main.tsx",
    "react-refresh",
)


class BiReleaseError(RuntimeError):
    """Raised when an executable is not a self-contained LE BI release."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def embedded_dev_markers(data: bytes) -> list[str]:
    hits: list[str] = []
    for marker in DEV_MARKERS:
        if marker.encode("utf-8") in data or marker.encode("utf-16le") in data:
            hits.append(marker)
    return hits


def production_fingerprint(fingerprint_root: Path | str) -> Path:
    root = Path(fingerprint_root).resolve()
    matches: list[Path] = []
    for path in root.glob("slk-bi-desktop-*/bin-slk-bi-desktop.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if "custom-protocol" in value.get("features", []) and "custom-protocol" in value.get(
            "declared_features", []
        ):
            matches.append(path)
    if len(matches) != 1:
        raise BiReleaseError(
            f"expected one custom-protocol BI release fingerprint, found {len(matches)}"
        )
    return matches[0]


def verify_bi_release(
    executable: Path | str,
    *,
    require_pe: bool = True,
    fingerprint_root: Path | str | None = None,
) -> dict[str, object]:
    path = Path(executable).resolve()
    if not path.is_file():
        raise BiReleaseError(f"BI executable is missing: {path}")
    data = path.read_bytes()
    if require_pe and (not data.startswith(b"MZ") or len(data) < 1_000_000):
        raise BiReleaseError("BI release must be a nontrivial Windows PE executable")
    hits = embedded_dev_markers(data)
    if hits:
        raise BiReleaseError(f"BI release contains development asset markers: {hits}")
    fingerprint = production_fingerprint(fingerprint_root) if fingerprint_root else None
    return {
        "path": str(path),
        "sha256": sha256(data),
        "size": len(data),
        "production_fingerprint": str(fingerprint) if fingerprint else None,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--fingerprint-root", type=Path)
    args = parser.parse_args()
    try:
        result = verify_bi_release(args.executable, fingerprint_root=args.fingerprint_root)
    except BiReleaseError as exc:
        print(f"FAIL SLK_BI_RELEASE: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
