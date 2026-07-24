from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "small-loop-skill" / "scripts" / "run_slk_readiness_eval.py"


def module():
    spec = importlib.util.spec_from_file_location("slk_eval", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seeded_order_and_exact_grade() -> None:
    mod = module()
    base = ROOT / "small-loop-skill" / "evals"
    bank = json.loads((base / "slk-readiness-questions.json").read_text(encoding="utf-8"))
    key = json.loads((base / "slk-readiness-answer-key.json").read_text(encoding="utf-8"))
    order = mod.emit_questions(bank, 7318)
    submitted = {"question_order": [q["id"] for q in order], "answers": [{"id": q["id"], "answer": key["answers"][q["id"]]} for q in order]}
    passed, results = mod.grade(bank, key, submitted)
    assert passed
    assert len(results) == 25


def test_wrong_answer_fails() -> None:
    mod = module()
    base = ROOT / "small-loop-skill" / "evals"
    bank = json.loads((base / "slk-readiness-questions.json").read_text(encoding="utf-8"))
    key = json.loads((base / "slk-readiness-answer-key.json").read_text(encoding="utf-8"))
    order = mod.emit_questions(bank, 1)
    answers = [{"id": q["id"], "answer": key["answers"][q["id"]]} for q in order]
    answers[0]["answer"] = "wrong"
    passed, _ = mod.grade(bank, key, {"question_order": [q["id"] for q in order], "answers": answers})
    assert not passed
