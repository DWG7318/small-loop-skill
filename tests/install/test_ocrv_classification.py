from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "integrations" / "ocrv" / "slk_checker_adapter.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("slk_checker_adapter_under_test", ADAPTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _complete_review(comments: list[dict[str, object]]) -> dict[str, object]:
    selected = [{"item_id": "criterion-1"}]
    return {
        "status": "complete",
        "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
        "manifest": {
            "terminal_state": "complete",
            "coverage": {
                "selected": selected,
                "completed": selected,
                "failed": [],
                "waived": [],
            },
        },
        "tool_calls": {"failure": 0},
        "comments": comments,
    }


def test_complete_low_severity_observation_is_pass_with_observation() -> None:
    verdict, reasons = _module()._classify(
        _complete_review([{"severity": "LOW", "message": "non-blocking naming observation"}]),
        0,
    )

    assert verdict == "PASS"
    assert reasons == ["OCR_COMPLETE_LOW_SEVERITY_OBSERVATIONS"]


@pytest.mark.parametrize("severity", ["MEDIUM", "HIGH", "BLOCKER", "CRITICAL"])
def test_material_finding_is_fail(severity: str) -> None:
    verdict, reasons = _module()._classify(
        _complete_review([{"severity": severity, "message": "acceptance criterion is violated"}]),
        0,
    )

    assert verdict == "FAIL"
    assert reasons == ["OCR_BLOCKING_FINDINGS_PRESENT"]


def test_unknown_finding_classification_is_incomplete_not_pass() -> None:
    verdict, reasons = _module()._classify(
        _complete_review([{"severity": "MYSTERY", "message": "cannot classify"}]),
        0,
    )

    assert verdict == "INCOMPLETE"
    assert reasons == ["OCR_FINDING_SEVERITY_UNKNOWN"]


def test_incomplete_coverage_never_passes_even_with_low_observation() -> None:
    review = _complete_review([{"severity": "LOW", "message": "minor"}])
    review["manifest"]["coverage"]["completed"] = []  # type: ignore[index]

    verdict, reasons = _module()._classify(review, 0)

    assert verdict == "INCOMPLETE"
    assert "OCR_COVERAGE_INCOMPLETE" in reasons


def test_complete_coverage_counts_native_reused_items() -> None:
    review = _complete_review([{"severity": "MEDIUM", "message": "material finding"}])
    selected = [
        {"item_id": "criterion-1", "path": "src/lib.rs", "fingerprint": "a" * 64},
        {"item_id": "criterion-2", "path": "src/paths.rs", "fingerprint": "b" * 64},
    ]
    review["manifest"]["coverage"] = {  # type: ignore[index]
        "selected": selected,
        "completed": [selected[0]],
        "reused": [selected[1]],
        "failed": [],
        "waived": [],
    }

    verdict, reasons = _module()._classify(review, 0)

    assert verdict == "FAIL"
    assert reasons == ["OCR_BLOCKING_FINDINGS_PRESENT"]
