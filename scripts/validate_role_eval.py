#!/usr/bin/env python3
"""Validate the closed, low-cost SLK role comprehension Eval."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


PACK_FIELDS = frozenset({"schema_version", "method_version", "cases"})
CASE_FIELDS = frozenset(
    {"case_id", "role", "runtime_critical", "scenario", "choices", "correct_choice", "rule"}
)
RESPONSE_FIELDS = frozenset(
    {"schema_version", "run_id", "project_id", "plan_revision", "role", "case_pack_sha256", "answers"}
)
ANSWER_FIELDS = frozenset({"case_id", "choice"})
ROLES = frozenset({"supervisor", "checker", "worker", "overwatcher"})
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CASE_ID = re.compile(r"^[A-Z][A-Z0-9-]{2,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvalError(ValueError):
    """Raised when the Eval pack or one response fails closed validation."""


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise EvalError(f"{label} must be a JSON object")
    return value


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown or missing:
        raise EvalError(
            f"{label} fields are not closed; unknown={sorted(unknown)} missing={sorted(missing)}"
        )


def _exact_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise EvalError(f"{label} must be exact non-empty text without surrounding whitespace")
    return value


def _identifier(value: Any, label: str) -> str:
    text = _exact_text(value, label)
    if not IDENTIFIER.fullmatch(text):
        raise EvalError(f"{label} has an unsupported identity shape")
    return text


def pack_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_pack(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError("case pack is unreadable JSON") from exc
    pack = _object(value, "case pack")
    _closed(pack, PACK_FIELDS, "case pack")
    if pack["schema_version"] != "slk.role-eval-pack/v1":
        raise EvalError("case pack schema_version is unsupported")
    if pack["method_version"] != "4.2.10":
        raise EvalError("case pack method_version must be 4.2.10")
    raw_cases = pack["cases"]
    if not isinstance(raw_cases, list) or len(raw_cases) < 36:
        raise EvalError("case pack must contain at least 36 cases")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    critical = {role: 0 for role in ROLES}
    counts = {role: 0 for role in ROLES}
    for index, raw_case in enumerate(raw_cases):
        case = _object(raw_case, f"case[{index}]")
        _closed(case, CASE_FIELDS, f"case[{index}]")
        case_id = _exact_text(case["case_id"], f"case[{index}].case_id")
        if not CASE_ID.fullmatch(case_id) or case_id in seen:
            raise EvalError("case_id must be unique canonical uppercase text")
        seen.add(case_id)
        role = _exact_text(case["role"], f"case[{index}].role")
        if role not in ROLES:
            raise EvalError("case role is unsupported")
        runtime_critical = case["runtime_critical"]
        if not isinstance(runtime_critical, bool):
            raise EvalError("runtime_critical must be boolean")
        scenario = _exact_text(case["scenario"], f"case[{index}].scenario")
        rule = _exact_text(case["rule"], f"case[{index}].rule")
        choices = case["choices"]
        if (
            not isinstance(choices, list)
            or len(choices) != 3
            or any(not isinstance(choice, str) or not choice or choice != choice.strip() for choice in choices)
            or len(set(choices)) != 3
        ):
            raise EvalError("each case must have three unique exact choices")
        correct_choice = _exact_text(case["correct_choice"], f"case[{index}].correct_choice")
        if correct_choice not in choices:
            raise EvalError("correct_choice must name one exact choice")
        counts[role] += 1
        if runtime_critical:
            critical[role] += 1
        cases.append(
            {
                "case_id": case_id,
                "role": role,
                "runtime_critical": runtime_critical,
                "scenario": scenario,
                "choices": list(choices),
                "correct_choice": correct_choice,
                "rule": rule,
            }
        )
    if any(counts[role] < 9 for role in ROLES):
        raise EvalError("each role must have at least nine cases")
    if any(critical[role] != 8 for role in ROLES):
        raise EvalError("each role must have exactly eight runtime-critical cases")
    return {
        "schema_version": pack["schema_version"],
        "method_version": pack["method_version"],
        "cases": cases,
    }


def validate_response(
    pack_path: Path | str,
    raw_response: Mapping[str, Any],
    *,
    expected_run_id: str,
    expected_project_id: str,
    expected_plan_revision: int,
    expected_role: str,
) -> dict[str, Any]:
    pack = load_pack(pack_path)
    response = _object(raw_response, "response")
    _closed(response, RESPONSE_FIELDS, "response")
    if response["schema_version"] != "slk.role-eval-response/v1":
        raise EvalError("response schema_version is unsupported")
    run_id = _identifier(response["run_id"], "run_id")
    project_id = _identifier(response["project_id"], "project_id")
    role = _exact_text(response["role"], "role")
    if role not in ROLES or role != expected_role:
        raise EvalError("response role does not match the frozen role")
    if run_id != expected_run_id or project_id != expected_project_id:
        raise EvalError("response identity does not match the frozen Run")
    plan_revision = response["plan_revision"]
    if (
        isinstance(plan_revision, bool)
        or not isinstance(plan_revision, int)
        or plan_revision < 1
        or plan_revision != expected_plan_revision
    ):
        raise EvalError("response plan_revision is stale or invalid")
    digest = _exact_text(response["case_pack_sha256"], "case_pack_sha256")
    if not SHA256.fullmatch(digest) or digest != pack_sha256(pack_path):
        raise EvalError("response case_pack_sha256 does not match exact pack bytes")
    expected_cases = [
        case
        for case in pack["cases"]
        if case["role"] == role and case["runtime_critical"]
    ]
    answers = response["answers"]
    if not isinstance(answers, list) or len(answers) != len(expected_cases):
        raise EvalError("response must contain the exact runtime case count")
    received: dict[str, str] = {}
    for index, raw_answer in enumerate(answers):
        answer = _object(raw_answer, f"answer[{index}]")
        _closed(answer, ANSWER_FIELDS, f"answer[{index}]")
        case_id = _exact_text(answer["case_id"], f"answer[{index}].case_id")
        choice = _exact_text(answer["choice"], f"answer[{index}].choice")
        if case_id in received:
            raise EvalError("response contains a duplicate case_id")
        received[case_id] = choice
    expected = {case["case_id"]: case["correct_choice"] for case in expected_cases}
    if set(received) != set(expected):
        raise EvalError("response case set does not match the frozen runtime subset")
    for case_id, correct_choice in expected.items():
        if received[case_id] != correct_choice:
            raise EvalError(f"incorrect choice for {case_id}")
    return {"status": "PASS", "role": role, "case_count": len(expected_cases)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--response", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--project-id")
    parser.add_argument("--plan-revision", type=int)
    parser.add_argument("--role", choices=sorted(ROLES))
    parser.add_argument("--check-pack", action="store_true")
    args = parser.parse_args()
    try:
        pack = load_pack(args.pack)
        if args.check_pack:
            result = {
                "status": "PASS",
                "case_count": len(pack["cases"]),
                "case_pack_sha256": pack_sha256(args.pack),
            }
        else:
            if not all(
                [args.response, args.run_id, args.project_id, args.plan_revision, args.role]
            ):
                raise EvalError("response validation requires frozen Run, plan, and role inputs")
            try:
                response = json.loads(args.response.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise EvalError("response is unreadable JSON") from exc
            result = validate_response(
                args.pack,
                response,
                expected_run_id=args.run_id,
                expected_project_id=args.project_id,
                expected_plan_revision=args.plan_revision,
                expected_role=args.role,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except EvalError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
