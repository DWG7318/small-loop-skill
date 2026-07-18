#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
QUESTION_PATH = Path("evals/slk-readiness-questions.json")
ANSWER_PATH = Path("evals/slk-readiness-answer-key.json")
QUESTION_COUNT = 25


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_assets(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    questions = json.loads((root / QUESTION_PATH).read_text(encoding="utf-8"))
    key = json.loads((root / ANSWER_PATH).read_text(encoding="utf-8"))
    validate_assets(questions, key)
    return questions, key


def validate_assets(questions: dict[str, Any], key: dict[str, Any]) -> None:
    if questions.get("mode") != "SLK" or key.get("mode") != "SLK":
        raise ValueError("mode_mismatch")
    if questions.get("eval_id") != key.get("eval_id"):
        raise ValueError("eval_id_mismatch")
    entries = questions.get("questions", [])
    answers = key.get("answers", [])
    if questions.get("question_count") != QUESTION_COUNT or len(entries) != QUESTION_COUNT:
        raise ValueError("question_count_mismatch")
    question_ids = [item["id"] for item in entries]
    answer_ids = [item["question_id"] for item in answers]
    if question_ids != [f"SLK-Q{i:02d}" for i in range(1, QUESTION_COUNT + 1)]:
        raise ValueError("question_ids_invalid")
    if len(answer_ids) != QUESTION_COUNT or set(question_ids) != set(answer_ids):
        raise ValueError("answer_coverage_invalid")
    if len(set(answer_ids)) != QUESTION_COUNT:
        raise ValueError("duplicate_answer_id")
    option_ids = {
        item["id"]: {option["id"] for option in item["options"]}
        for item in entries
    }
    for item in answers:
        if not item["answer"] or not set(item["answer"]).issubset(
            option_ids[item["question_id"]]
        ):
            raise ValueError(f"invalid_answer:{item['question_id']}")
        for field in ("rationale", "rule_anchors", "forbidden_interpretations"):
            if not item.get(field):
                raise ValueError(f"missing_{field}:{item['question_id']}")


def question_payload(seed: int, root: Path = ROOT) -> dict[str, Any]:
    questions, _ = load_assets(root)
    rng = random.Random(seed)
    rendered = json.loads(json.dumps(questions["questions"]))
    rng.shuffle(rendered)
    for question in rendered:
        rng.shuffle(question["options"])
    return {
        "schema_version": questions["schema_version"],
        "eval_id": questions["eval_id"],
        "mode": "SLK",
        "seed": seed,
        "question_count": QUESTION_COUNT,
        "questions": rendered,
    }


def source_commit(root: Path = ROOT) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _governed_paths(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
        relative = [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]
        if relative:
            return sorted(relative, key=lambda path: path.as_posix())
    except (OSError, subprocess.CalledProcessError):
        pass
    paths = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not path.is_file():
            continue
        if ".git" in relative.parts or "__pycache__" in relative.parts:
            continue
        if path.suffix == ".pyc":
            continue
        paths.append(relative)
    return sorted(paths, key=lambda path: path.as_posix())


def tracked_content_hash(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for relative in _governed_paths(root):
        path = root / relative
        if not path.exists():
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _metadata_error(metadata: dict[str, Any], seed: int) -> str | None:
    role = metadata.get("candidate_role")
    model = metadata.get("model")
    reasoning = metadata.get("reasoning")
    if role == "supervisor_checker":
        if (model, reasoning) != ("gpt-5.6-sol", "xhigh"):
            return "invalid_role_model"
    elif role == "worker":
        if (model, reasoning) not in {
            ("gpt-5.5", "high"),
            ("gpt-5.6-sol", "high"),
        }:
            return "invalid_role_model"
    else:
        return "invalid_candidate_role"
    if not metadata.get("conversation_id"):
        return "missing_conversation_id"
    if not metadata.get("answer_key_not_opened"):
        return "answer_key_access_not_attested"
    attempt = metadata.get("attempt")
    if not isinstance(attempt, int) or attempt < 1:
        return "invalid_attempt"
    if attempt > 1 and metadata.get("previous_seed") == seed:
        return "retry_seed_reused"
    return None


def _answer_correct(candidate: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(candidate, list) or not all(
        isinstance(item, str) for item in candidate
    ):
        return False
    wanted = expected["answer"]
    if expected["order_sensitive"]:
        return candidate == wanted
    return len(candidate) == len(wanted) and sorted(candidate) == sorted(wanted)


def grade(
    candidate_answers: dict[str, Any],
    metadata: dict[str, Any],
    seed: int,
    root: Path = ROOT,
) -> dict[str, Any]:
    questions, key = load_assets(root)
    expected = {item["question_id"]: item for item in key["answers"]}
    expected_ids = set(expected)
    candidate_ids = set(candidate_answers) if isinstance(candidate_answers, dict) else set()
    results = []
    review_ids = []
    correct_count = 0
    for question_id in sorted(expected):
        correct = _answer_correct(candidate_answers.get(question_id), expected[question_id]) if isinstance(candidate_answers, dict) else False
        results.append({"question_id": question_id, "correct": correct})
        if correct:
            correct_count += 1
        else:
            review_ids.append(question_id)
    extra_ids = sorted(candidate_ids - expected_ids)
    review_ids.extend(extra_ids)
    metadata_error = _metadata_error(metadata, seed)
    answer_set_error = candidate_ids != expected_ids
    passed = correct_count == QUESTION_COUNT and not answer_set_error and metadata_error is None
    failure_reason = None
    if metadata_error:
        failure_reason = metadata_error
    elif answer_set_error:
        failure_reason = "invalid_answer_set"
    elif not passed:
        failure_reason = "incorrect_answers"
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    return {
        "receipt_type": "SLK_READINESS_EVAL_RECEIPT",
        "result": "SLK_READINESS_EVAL_PASS" if passed else "SLK_READINESS_EVAL_FAIL",
        "failure_reason": failure_reason,
        "mode": "SLK",
        "eval_id": questions["eval_id"],
        "skill_version": version,
        "release_tag": f"v{version}",
        "source_commit": source_commit(root),
        "tracked_content_sha256": tracked_content_hash(root),
        "question_bank_sha256": sha256_value(questions),
        "answer_key_sha256": sha256_value(key),
        "candidate_role": metadata.get("candidate_role"),
        "conversation_id": metadata.get("conversation_id"),
        "model": metadata.get("model"),
        "reasoning": metadata.get("reasoning"),
        "answer_key_not_opened": metadata.get("answer_key_not_opened") is True,
        "seed": seed,
        "attempt": metadata.get("attempt"),
        "score": f"{correct_count}/{QUESTION_COUNT}",
        "question_results": results,
        "review_question_ids": sorted(set(review_ids)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def verify_receipt(
    receipt: dict[str, Any],
    metadata: dict[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    questions, key = load_assets(root)
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    checks = {
        "pass_result": receipt.get("result") == "SLK_READINESS_EVAL_PASS",
        "perfect_score": receipt.get("score") == f"{QUESTION_COUNT}/{QUESTION_COUNT}",
        "version": receipt.get("skill_version") == version,
        "release_tag": receipt.get("release_tag") == f"v{version}",
        "tree_hash": receipt.get("tracked_content_sha256") == tracked_content_hash(root),
        "question_hash": receipt.get("question_bank_sha256") == sha256_value(questions),
        "answer_hash": receipt.get("answer_key_sha256") == sha256_value(key),
        "candidate_role": receipt.get("candidate_role") == metadata.get("candidate_role"),
        "conversation_id": receipt.get("conversation_id") == metadata.get("conversation_id"),
        "model": receipt.get("model") == metadata.get("model"),
        "reasoning": receipt.get("reasoning") == metadata.get("reasoning"),
        "answer_key_attestation": receipt.get("answer_key_not_opened") is True,
    }
    current_commit = source_commit(root)
    if current_commit is not None:
        checks["source_commit"] = receipt.get("source_commit") == current_commit
    return {"valid": all(checks.values()), "checks": checks}


def verify_roster(
    receipts: list[dict[str, Any]],
    expected: dict[str, dict[str, Any]],
    root: Path = ROOT,
) -> dict[str, Any]:
    required_roles = {"supervisor_checker", "worker"}
    if set(expected) != required_roles or len(receipts) != 2:
        return {"valid": False, "reason": "missing_roster_receipt"}
    by_role = {receipt.get("candidate_role"): receipt for receipt in receipts}
    if set(by_role) != required_roles:
        return {"valid": False, "reason": "invalid_roster_roles"}
    conversations = [item.get("conversation_id") for item in receipts]
    if len(set(conversations)) != 2:
        return {"valid": False, "reason": "duplicate_conversation"}
    checks = {
        role: verify_receipt(by_role[role], expected[role], root=root)
        for role in sorted(required_roles)
    }
    return {
        "valid": all(item["valid"] for item in checks.values()),
        "reason": None,
        "roles": checks,
    }


def write_receipt(receipt: dict[str, Any], target: Path, root: Path = ROOT) -> None:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if target_resolved == root_resolved or root_resolved in target_resolved.parents:
        raise ValueError("receipt_path_inside_skill_root")
    target_resolved.parent.mkdir(parents=True, exist_ok=True)
    target_resolved.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_candidate_answers(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("answers", payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SLK readiness evaluation.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    questions = subparsers.add_parser("questions")
    questions.add_argument("--seed", type=int, required=True)
    grade_parser = subparsers.add_parser("grade")
    grade_parser.add_argument("--answers", type=Path, required=True)
    grade_parser.add_argument("--candidate-role", required=True)
    grade_parser.add_argument("--conversation-id", required=True)
    grade_parser.add_argument("--model", required=True)
    grade_parser.add_argument("--reasoning", required=True)
    grade_parser.add_argument("--attempt", type=int, required=True)
    grade_parser.add_argument("--seed", type=int, required=True)
    grade_parser.add_argument("--previous-seed", type=int)
    grade_parser.add_argument("--answer-key-not-opened", action="store_true")
    grade_parser.add_argument("--receipt", type=Path)
    verify = subparsers.add_parser("verify-receipt")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--candidate-role", required=True)
    verify.add_argument("--conversation-id", required=True)
    verify.add_argument("--model", required=True)
    verify.add_argument("--reasoning", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "questions":
        print(json.dumps(question_payload(args.seed), ensure_ascii=False, indent=2))
        return 0
    if args.command == "grade":
        meta = {
            "candidate_role": args.candidate_role,
            "conversation_id": args.conversation_id,
            "model": args.model,
            "reasoning": args.reasoning,
            "attempt": args.attempt,
            "previous_seed": args.previous_seed,
            "answer_key_not_opened": args.answer_key_not_opened,
        }
        receipt = grade(_load_candidate_answers(args.answers), meta, args.seed)
        if args.receipt:
            write_receipt(receipt, args.receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if receipt["result"] == "SLK_READINESS_EVAL_PASS" else 1
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    meta = {
        "candidate_role": args.candidate_role,
        "conversation_id": args.conversation_id,
        "model": args.model,
        "reasoning": args.reasoning,
    }
    result = verify_receipt(receipt, meta)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
