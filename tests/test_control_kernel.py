import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "slk-control-kernel.json"


def command_for(contract, command):
    for item in contract["commands"]:
        pattern = re.escape(item["syntax"])
        pattern = pattern.replace(re.escape("<accepted-cell-count>"), r"[1-9][0-9]*")
        pattern = pattern.replace(re.escape("<RFC3339-time>"), r"\S+")
        if re.fullmatch(pattern, command):
            return item
    return None


def apply_command(
    contract,
    command,
    state,
    *,
    active_cell=False,
    prerequisites=True,
    duplicate=False,
):
    if duplicate:
        return "ALREADY_APPLIED"
    item = command_for(contract, command)
    if item is None:
        return "INVALID_COMMAND"
    if item.get("read_only"):
        return state
    if state not in item["allowed_from"]:
        return "INVALID_STATE"
    if not prerequisites:
        return "PRECONDITION_FAILED"
    if active_cell and item.get("safe_boundary"):
        return "PAUSE_PENDING"
    return item.get("to_by_state", {}).get(state, item["to"])


class SlkControlKernelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_public_command_surface_is_exact(self):
        expected = {
            "SLK START",
            "SLK STATUS",
            "SLK PAUSE NOW",
            "SLK PAUSE AFTER <accepted-cell-count>",
            "SLK PAUSE AT <RFC3339-time>",
            "SLK RESUME NOW",
            "SLK RESUME AT <RFC3339-time>",
            "SLK CANCEL SCHEDULE",
        }
        self.assertEqual(
            {item["syntax"] for item in self.contract["commands"]}, expected
        )

    def test_only_manual_initial_start_is_valid(self):
        serialized = json.dumps(self.contract, sort_keys=True)
        self.assertEqual(self.contract["initial_start"], "SLK START")
        self.assertNotIn("START AT", serialized)
        self.assertNotIn("START AFTER", serialized)
        self.assertEqual(
            apply_command(self.contract, "SLK START", "NOT_STARTED"), "RUNNING"
        )

    def test_start_requires_current_readiness_and_simulation(self):
        start = command_for(self.contract, "SLK START")
        self.assertEqual(
            start["requires"],
            [
                "SLK_READINESS_EVAL_PASS_EXACT_ROSTER",
                "PLAN_APPROVED",
                "SIMULATION_PASS",
                "GO_DETECTION_PROFILES_APPROVED",
                "CONTINUATION_CONDITIONS_PASS",
            ],
        )
        self.assertEqual(
            apply_command(
                self.contract, "SLK START", "NOT_STARTED", prerequisites=False
            ),
            "PRECONDITION_FAILED",
        )

    def test_pause_does_not_interrupt_active_cell(self):
        self.assertEqual(
            apply_command(
                self.contract, "SLK PAUSE NOW", "RUNNING", active_cell=True
            ),
            "PAUSE_PENDING",
        )

    def test_pause_threshold_is_absolute_project_count(self):
        pause = command_for(self.contract, "SLK PAUSE AFTER 35")
        self.assertEqual(pause["threshold_scope"], "project_accepted_absolute")
        self.assertEqual(pause["to"], "PAUSE_SCHEDULED")

    def test_resume_requires_same_prepared_worker(self):
        resume = command_for(self.contract, "SLK RESUME NOW")
        self.assertTrue(resume["same_worker"])
        self.assertTrue(resume["revalidate"])
        self.assertEqual(
            apply_command(self.contract, "SLK RESUME NOW", "NOT_STARTED"),
            "INVALID_STATE",
        )
        self.assertEqual(
            apply_command(self.contract, "SLK RESUME NOW", "PAUSED"), "RUNNING"
        )

    def test_status_is_read_only_in_every_state(self):
        for state in self.contract["states"]:
            with self.subTest(state=state):
                self.assertEqual(
                    apply_command(self.contract, "SLK STATUS", state), state
                )

    def test_cancel_restores_state_without_dispatch(self):
        cancel = command_for(self.contract, "SLK CANCEL SCHEDULE")
        self.assertFalse(cancel["dispatch"])
        self.assertEqual(
            apply_command(
                self.contract, "SLK CANCEL SCHEDULE", "PAUSE_SCHEDULED"
            ),
            "RUNNING",
        )
        self.assertEqual(
            apply_command(
                self.contract, "SLK CANCEL SCHEDULE", "RESUME_SCHEDULED"
            ),
            "PAUSED",
        )

    def test_duplicate_and_foreign_commands_do_not_dispatch(self):
        self.assertEqual(
            apply_command(
                self.contract, "SLK PAUSE NOW", "RUNNING", duplicate=True
            ),
            "ALREADY_APPLIED",
        )
        for command in (
            "MSLK START",
            "LOOP START",
            "SLK START AT 2030-01-01T00:00:00Z",
            "SLK PAUSE PAIR A NOW",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    apply_command(self.contract, command, "RUNNING"),
                    "INVALID_COMMAND",
                )

    def test_complete_cannot_be_reopened(self):
        for command in ("SLK START", "SLK RESUME NOW", "SLK PAUSE NOW"):
            with self.subTest(command=command):
                self.assertEqual(
                    apply_command(self.contract, command, "COMPLETE"),
                    "INVALID_STATE",
                )

    def test_receipt_and_errors_are_fail_closed(self):
        self.assertEqual(
            set(self.contract["errors"]),
            {
                "INVALID_COMMAND",
                "INVALID_STATE",
                "PRECONDITION_FAILED",
                "SCHEDULE_CONFLICT",
                "ALREADY_APPLIED",
            },
        )
        self.assertIn("command_id", self.contract["receipt_fields"])
        self.assertIn("progress_snapshot", self.contract["receipt_fields"])
        for error in self.contract["errors"].values():
            self.assertFalse(error["state_change"])
            self.assertFalse(error["dispatch"])


if __name__ == "__main__":
    unittest.main()
