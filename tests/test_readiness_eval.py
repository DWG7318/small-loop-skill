import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_slk_readiness_eval.py"


def load_module():
    spec = importlib.util.spec_from_file_location("slk_readiness_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_answers(key):
    return {item["question_id"]: item["answer"] for item in key["answers"]}


def metadata(role="worker", conversation_id="worker-1", attempt=1, **overrides):
    base = {
        "candidate_role": role,
        "conversation_id": conversation_id,
        "model": "gpt-5.5" if role == "worker" else "gpt-5.6-sol",
        "reasoning": "high" if role == "worker" else "xhigh",
        "attempt": attempt,
        "answer_key_not_opened": True,
    }
    base.update(overrides)
    return base


class SlkReadinessEvalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.questions, cls.key = cls.module.load_assets(ROOT)
        cls.answers = canonical_answers(cls.key)

    def test_bank_and_key_are_complete_and_independent(self):
        question_ids = [item["id"] for item in self.questions["questions"]]
        answer_ids = [item["question_id"] for item in self.key["answers"]]
        self.assertEqual(len(question_ids), 24)
        self.assertEqual(len(set(question_ids)), 24)
        self.assertEqual(question_ids, [f"SLK-Q{i:02d}" for i in range(1, 25)])
        self.assertEqual(set(question_ids), set(answer_ids))
        self.assertEqual(self.questions["mode"], "SLK")
        self.assertEqual(self.key["mode"], "SLK")

    def test_question_output_hides_answer_material(self):
        payload = self.module.question_payload(seed=7318, root=ROOT)
        serialized = json.dumps(payload).lower()
        self.assertEqual(len(payload["questions"]), 24)
        self.assertNotIn('"answer"', serialized)
        self.assertNotIn("rationale", serialized)
        self.assertNotIn("forbidden_interpretations", serialized)

    def test_canonical_answers_pass_exactly(self):
        receipt = self.module.grade(self.answers, metadata(), seed=7318, root=ROOT)
        self.assertEqual(receipt["result"], "SLK_READINESS_EVAL_PASS")
        self.assertEqual(receipt["score"], "24/24")
        self.assertEqual(len(receipt["question_results"]), 24)

    def test_one_wrong_answer_fails_entire_attempt(self):
        answers = dict(self.answers)
        answers["SLK-Q17"] = ["WRONG"]
        receipt = self.module.grade(answers, metadata(), seed=7318, root=ROOT)
        self.assertEqual(receipt["result"], "SLK_READINESS_EVAL_FAIL")
        self.assertEqual(receipt["score"], "23/24")
        self.assertEqual(receipt["review_question_ids"], ["SLK-Q17"])

    def test_missing_extra_and_misordered_answers_fail(self):
        missing = dict(self.answers)
        missing.pop("SLK-Q03")
        extra = dict(self.answers)
        extra["SLK-Q99"] = ["A"]
        misordered = dict(self.answers)
        misordered["SLK-Q09"] = list(reversed(misordered["SLK-Q09"]))
        for candidate in (missing, extra, misordered):
            with self.subTest(candidate_count=len(candidate)):
                receipt = self.module.grade(
                    candidate, metadata(), seed=7318, root=ROOT
                )
                self.assertEqual(receipt["result"], "SLK_READINESS_EVAL_FAIL")

    def test_multiselect_order_is_not_significant(self):
        answers = dict(self.answers)
        answers["SLK-Q01"] = list(reversed(answers["SLK-Q01"]))
        receipt = self.module.grade(answers, metadata(), seed=7318, root=ROOT)
        self.assertEqual(receipt["result"], "SLK_READINESS_EVAL_PASS")

    def test_role_model_policy_is_enforced(self):
        bad_controller = metadata(
            role="supervisor_checker", model="gpt-5.5", reasoning="high"
        )
        receipt = self.module.grade(
            self.answers, bad_controller, seed=7318, root=ROOT
        )
        self.assertEqual(receipt["result"], "SLK_READINESS_EVAL_FAIL")
        self.assertEqual(receipt["failure_reason"], "invalid_role_model")

    def test_retry_requires_new_seed_and_full_bank(self):
        retry = metadata(attempt=2, previous_seed=7318)
        receipt = self.module.grade(self.answers, retry, seed=7318, root=ROOT)
        self.assertEqual(receipt["result"], "SLK_READINESS_EVAL_FAIL")
        self.assertEqual(receipt["failure_reason"], "retry_seed_reused")

    def test_receipt_verification_detects_stale_identity(self):
        receipt = self.module.grade(self.answers, metadata(), seed=7318, root=ROOT)
        self.assertTrue(
            self.module.verify_receipt(receipt, metadata(), root=ROOT)["valid"]
        )
        stale_conversation = metadata(conversation_id="worker-replacement")
        self.assertFalse(
            self.module.verify_receipt(receipt, stale_conversation, root=ROOT)[
                "valid"
            ]
        )
        stale_hash = dict(receipt)
        stale_hash["question_bank_sha256"] = "0" * 64
        self.assertFalse(
            self.module.verify_receipt(stale_hash, metadata(), root=ROOT)["valid"]
        )

    def test_exact_two_role_roster_is_required(self):
        controller_meta = metadata(
            role="supervisor_checker", conversation_id="controller-1"
        )
        controller = self.module.grade(
            self.answers, controller_meta, seed=7318, root=ROOT
        )
        worker = self.module.grade(self.answers, metadata(), seed=7319, root=ROOT)
        expected = {
            "supervisor_checker": controller_meta,
            "worker": metadata(),
        }
        self.assertTrue(
            self.module.verify_roster([controller, worker], expected, root=ROOT)[
                "valid"
            ]
        )
        self.assertFalse(
            self.module.verify_roster([controller], expected, root=ROOT)["valid"]
        )

    def test_receipts_cannot_be_written_inside_skill_root(self):
        receipt = self.module.grade(self.answers, metadata(), seed=7318, root=ROOT)
        with self.assertRaises(ValueError):
            self.module.write_receipt(receipt, ROOT / "receipt.json", root=ROOT)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "receipt.json"
            self.module.write_receipt(receipt, target, root=ROOT)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8"))["score"], "24/24"
            )

    def test_git_commit_is_optional_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(self.module.source_commit(Path(directory)))


if __name__ == "__main__":
    unittest.main()
