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


def test_seeded_order_and_choice_id_grade() -> None:
    mod = module()
    base = ROOT / "small-loop-skill" / "evals"
    bank = json.loads((base / "slk-readiness-questions.json").read_text(encoding="utf-8"))
    key = json.loads((base / "slk-readiness-answer-key.json").read_text(encoding="utf-8"))
    order = mod.emit_questions(bank, 7318)
    submitted = {
        "question_order": [q["id"] for q in order],
        "answers": [
            {
                "id": q["id"],
                "choice_id": mod.correct_choice_id(key, q["id"]),
            }
            for q in order
        ],
    }
    passed, results = mod.grade(bank, key, submitted)
    assert passed
    assert len(results) == 25
    assert all([choice["id"] for choice in q["choices"]] == ["A", "B", "C", "D"] for q in order)
    assert all(len({choice["text"] for choice in q["choices"]}) == 4 for q in order)


def test_wrong_answer_fails() -> None:
    mod = module()
    base = ROOT / "small-loop-skill" / "evals"
    bank = json.loads((base / "slk-readiness-questions.json").read_text(encoding="utf-8"))
    key = json.loads((base / "slk-readiness-answer-key.json").read_text(encoding="utf-8"))
    order = mod.emit_questions(bank, 1)
    answers = [
        {"id": q["id"], "choice_id": mod.correct_choice_id(key, q["id"])}
        for q in order
    ]
    answers[0]["choice_id"] = next(
        choice["id"]
        for choice in order[0]["choices"]
        if choice["id"] != answers[0]["choice_id"]
    )
    passed, _ = mod.grade(bank, key, {"question_order": [q["id"] for q in order], "answers": answers})
    assert not passed


def test_legacy_free_text_answer_is_rejected() -> None:
    mod = module()
    base = ROOT / "small-loop-skill" / "evals"
    bank = json.loads((base / "slk-readiness-questions.json").read_text(encoding="utf-8"))
    key = json.loads((base / "slk-readiness-answer-key.json").read_text(encoding="utf-8"))
    order = mod.emit_questions(bank, 19)
    answers = [
        {"id": q["id"], "choice_id": mod.correct_choice_id(key, q["id"])}
        for q in order
    ]
    answers[0] = {"id": order[0]["id"], "answer": key["answers"][order[0]["id"]]}
    try:
        mod.grade(bank, key, {"question_order": [q["id"] for q in order], "answers": answers})
    except SystemExit as exc:
        assert "choice_id" in str(exc)
    else:
        raise AssertionError("legacy free-text readiness answers must fail closed")


def test_public_bank_contains_every_option_and_key_contains_only_choice_ids() -> None:
    base = ROOT / "small-loop-skill" / "evals"
    bank = json.loads((base / "slk-readiness-questions.json").read_text(encoding="utf-8"))
    key = json.loads((base / "slk-readiness-answer-key.json").read_text(encoding="utf-8"))
    assert len(bank["questions"]) == 25
    for question in bank["questions"]:
        choices = question.get("choices")
        assert isinstance(choices, list), question["id"]
        assert [choice["id"] for choice in choices] == ["A", "B", "C", "D"], question["id"]
        assert len({choice["text"] for choice in choices}) == 4, question["id"]
        assert key["answers"][question["id"]] in {"A", "B", "C", "D"}
