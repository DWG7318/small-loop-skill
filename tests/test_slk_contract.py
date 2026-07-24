from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "small-loop-skill"


def contract() -> dict:
    return json.loads((SKILL / "contracts" / "slk-control-kernel.json").read_text(encoding="utf-8"))


def test_version_and_identity() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version == "1.9.0"
    assert f"Current version: **{version}**" in (ROOT / "README.md").read_text(encoding="utf-8")
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "# Small Loop Skill (SLK)" in text
    assert f"Current specification version: `{version}`." in text


def test_topology_and_authority() -> None:
    c = contract()
    assert c["visible_conversations"] == ["CONTROL", "WORKER"]
    assert c["control_responsibilities"] == ["SUPERVISOR_RESPONSIBILITY", "CHECKER_RESPONSIBILITY"]
    assert c["worker_count"] == 1
    assert c["active_cell_count"] == 1
    assert c["product_write_authority"] == ["WORKER"]
    assert c["cell_acceptance_authority"] == ["CHECKER_RESPONSIBILITY"]
    assert c["go_acceptance_authority"] == ["CHECKER_RESPONSIBILITY"]


def test_calabash_gate() -> None:
    gate = contract()["calabash_gate"]
    assert gate["product_affecting_required"] is True
    assert gate["minimum_layers"] == ["GRANDPA", "PRODUCT_ARCHITECTURE", "ONTOLOGY"]
    assert gate["narrow_technical_exemption"] is True
    assert gate["go_trace_required"] is True


def test_isolation_rework_and_method_boundaries() -> None:
    c = contract()
    assert c["checker_environment_isolation_required"] is True
    assert c["separate_blind_verification_conversation"] is False
    assert "REDO" not in c["cell_routes"]
    assert "CELL_REWORK" in c["cell_routes"]
    assert c["method_boundaries"] == {"parallel_fixed_chains": "CLK", "free_go_graph": "GLK"}


def test_go_boundary_and_detection() -> None:
    c = contract()
    assert c["cross_go_rule"]["cell_to_cell_dependency_allowed"] is False
    assert c["cross_go_rule"]["required_predecessor_state"] == "GO_ACCEPTED"
    assert c["detection_tiers"] == ["CELL_ALWAYS", "CELL_TRIGGERED", "GO_BOUNDARY", "PROJECT_FINAL"]


def test_line_budgets() -> None:
    paths = [ROOT / "README.md", ROOT / "CHANGELOG.md", SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]
    for path in paths:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 1000, path


def test_readiness_count() -> None:
    q = json.loads((SKILL / "evals" / "slk-readiness-questions.json").read_text(encoding="utf-8"))
    a = json.loads((SKILL / "evals" / "slk-readiness-answer-key.json").read_text(encoding="utf-8"))
    assert len(q["questions"]) == 25
    assert len(a["answers"]) == 25
    assert {x["id"] for x in q["questions"]} == set(a["answers"])
