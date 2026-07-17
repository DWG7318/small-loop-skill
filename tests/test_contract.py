from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
PROMPT = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
ALL_TEXT = "\n".join((SKILL, README, PROMPT))


class SmallLoopContractTest(unittest.TestCase):
    def test_mode_is_strictly_exclusive(self):
        self.assertIn("invoke SLK exactly once", SKILL)
        self.assertIn("do not borrow MSLK role topology", SKILL)
        self.assertIn("Shared rules never transfer role ownership", SKILL)
        self.assertIn("current run never converts itself into MSLK", SKILL)
        self.assertIn("Never load, borrow, combine, or switch to MSLK", PROMPT)

    def test_topology_and_role_ownership(self):
        self.assertIn("one combined Supervisor/Checker", SKILL)
        self.assertIn("one Worker", SKILL)
        self.assertIn("Do not create a separate Checker", SKILL)
        self.assertIn(
            "GO/CELL plan, and GO revision | Supervisor responsibility", SKILL
        )
        self.assertIn("Worker-result repair | Supervisor responsibility", SKILL)
        self.assertIn(
            "CELL assignment, validation, and routing | Checker responsibility",
            SKILL,
        )
        self.assertIn("Use exactly one visible combined Supervisor/Checker", PROMPT)

    def test_shared_rules_remain_inside_slk(self):
        required = (
            "Never use a subagent",
            "SIMULATION_PASS",
            "Archive it immediately",
            "GO_REVISION_SIMULATION_PASS",
            "must not send a repair task back to the Worker",
            "`gpt-5.5` with `high` reasoning as the minimum",
            "`gpt-5.6-sol` with `high` reasoning as the maximum",
            "GO scope follows project need and must not be reduced for device capacity",
            "CELL size must be kept modest enough for the current computer",
            "正在完成 GO-03：35/231",
            "全部完成：231/231",
        )
        for rule in required:
            with self.subTest(rule=rule):
                self.assertIn(rule, ALL_TEXT)

        self.assertNotIn("Formal rework:", ALL_TEXT)
        self.assertNotIn("planner", ALL_TEXT.lower())


if __name__ == "__main__":
    unittest.main()
