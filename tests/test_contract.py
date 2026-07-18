from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
PROMPT = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
DETECTION_REFERENCE = (ROOT / "references" / "checker-detection-catalog.md").read_text(
    encoding="utf-8"
)
CONTROL_REFERENCE = (ROOT / "references" / "slk-control-operations.md").read_text(
    encoding="utf-8"
)
CONTROL_CONTRACT = json.loads(
    (ROOT / "contracts" / "slk-control-kernel.json").read_text(encoding="utf-8")
)
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
ALL_TEXT = "\n".join((SKILL, README, PROMPT, DETECTION_REFERENCE))
NORMALIZED_SKILL = " ".join(SKILL.split())
NORMALIZED_DETECTION = " ".join((SKILL + "\n" + DETECTION_REFERENCE).split())


class SmallLoopContractTest(unittest.TestCase):
    def test_required_operational_links_are_explicit(self):
        required = (
            "(scripts/run_slk_readiness_eval.py)",
            "(contracts/slk-control-kernel.json)",
            "(references/slk-control-operations.md)",
            "(references/checker-detection-catalog.md)",
        )
        for link in required:
            with self.subTest(link=link):
                self.assertIn(link, SKILL)

    def test_markdown_reference_graph_is_closed_and_bounded(self):
        link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        queue = [ROOT / "SKILL.md"]
        visited = set()
        while queue:
            source = queue.pop()
            if source in visited:
                continue
            visited.add(source)
            text = source.read_text(encoding="utf-8")
            for raw_target in link_pattern.findall(text):
                target_text = raw_target.split("#", 1)[0]
                if not target_text or "://" in target_text:
                    continue
                target = (source.parent / target_text).resolve()
                self.assertTrue(target.is_relative_to(ROOT.resolve()), raw_target)
                self.assertTrue(target.is_file(), raw_target)
                if target.suffix.lower() == ".md":
                    queue.append(target)

        for reference in CONTROL_CONTRACT["references"]:
            target = (ROOT / reference).resolve()
            self.assertTrue(target.is_relative_to(ROOT.resolve()), reference)
            self.assertTrue(target.is_file(), reference)
            queue.append(target)

        reference_files = set((ROOT / "references").glob("*.md"))
        self.assertTrue(reference_files.issubset(visited | set(queue)))
        for path in ROOT.rglob("*.md"):
            self.assertLessEqual(
                len(path.read_text(encoding="utf-8").splitlines()), 1000, path
            )
        self.assertLess(len(SKILL.splitlines()), 900)

    def test_canonical_identity_and_release_version(self):
        required = (
            "## Canonical Identity",
            "https://github.com/DWG7318/small-loop-skill",
            "1295599218",
            "Default branch: `main`",
            "Version source: repository `VERSION` file and matching `v*` tag",
        )
        for item in required:
            with self.subTest(item=item):
                self.assertIn(item, SKILL)
        self.assertEqual(VERSION, "1.8.1")
        self.assertIn("Current version: `1.8.1`", README)
        self.assertNotIn("all nine rules", README.lower())

    def test_readiness_eval_precedes_simulation_and_manual_start(self):
        self.assertIn("## Mandatory Readiness Eval", SKILL)
        self.assertIn("SLK_READINESS_EVAL_PASS", SKILL)
        self.assertIn("exactly `25/25`", SKILL)
        self.assertIn("exact two-role roster", SKILL)
        self.assertLess(
            SKILL.index("## Mandatory Readiness Eval"),
            SKILL.index("## Mandatory Simulation Gate"),
        )
        self.assertIn("SLK START", SKILL)
        self.assertIn("manual only", CONTROL_REFERENCE)
        self.assertNotIn("SCHEDULED_START", SKILL)
        self.assertNotIn("start/resume", SKILL.lower())
        self.assertEqual(CONTROL_CONTRACT["initial_start"], "SLK START")

    def test_continuation_index_is_bounded_current_state(self):
        self.assertIn("bounded mutable current-state pointer", NORMALIZED_SKILL)
        self.assertIn("below 200 physical lines", NORMALIZED_SKILL)
        self.assertIn(
            "Historical detail remains in linked semantic shards", NORMALIZED_SKILL
        )

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

    def test_optional_goal_gate_stays_in_supervisor_responsibility(self):
        required = (
            "## Optional Goal Gate",
            "The Owner may define one optional Goal",
            "Checker completion is provisional",
            "Supervisor responsibility must independently validate the Goal",
            "GOAL_SATISFIED",
            "GOAL_GAP",
            "must not declare project completion",
            "Supervisor responsibility designs the next PLAN/GO/CELL continuation",
            "If no Goal is configured",
            "Accepted CELLs with an untested Goal or `GOAL_GAP` remain unfinished Supervisor work",
        )
        for rule in required:
            with self.subTest(rule=rule):
                self.assertIn(rule, NORMALIZED_SKILL)

    def test_continuation_condition_gate_uses_combined_role_responsibilities(self):
        required = (
            "## Continuation Condition Gate",
            "Checker responsibility must stop dispatching formal tasks",
            "CONDITION_BLOCKED",
            "Supervisor responsibility decides whether Owner assistance is required",
            "OWNER_ASSISTANCE_REQUIRED",
            "OWNER_ASSISTANCE_RECEIVED",
            "SUPERVISOR_RESOLVED",
            "RESUME_AUTHORIZED",
            "resume the Checker responsibility inside the same combined conversation",
            "must revalidate every blocked condition before dispatching",
        )
        for rule in required:
            with self.subTest(rule=rule):
                self.assertIn(rule, NORMALIZED_SKILL)

    def test_control_commands_only_pause_and_resume_existing_loop_safely(self):
        required = (
            "## SLK Control Commands",
            "`SLK START` is manual only",
            "SLK PAUSE AFTER <accepted-cell-count>",
            "SLK PAUSE AT <RFC3339-time>",
            "SLK RESUME AT <RFC3339-time>",
            "accepted CELL threshold",
            "`SLK_CONTROL_RECEIPT`",
            "must not interrupt an active CELL",
            "same Worker",
            "A paused SLK is not complete",
        )
        for rule in required:
            with self.subTest(rule=rule):
                self.assertIn(rule, NORMALIZED_SKILL)
        self.assertNotIn("SCHEDULED_START", SKILL)

    def test_dispatch_is_final_action_and_combined_role_goes_offline(self):
        required = (
            "## Dispatch-Then-Offline Boundary",
            "The formal Worker assignment is the final action",
            "OFFLINE_WAITING_WORKER_SIGNAL",
            "must immediately end its turn and go offline",
            "must not poll, inspect, run status, perform oversight, or do more project work",
            "WORKER_COMPLETION_RECEIPT",
            "WORKER_BLOCKER_RECEIPT",
            "WORKER_EXECUTION_FAILURE",
        )
        for rule in required:
            with self.subTest(rule=rule):
                self.assertIn(rule, NORMALIZED_SKILL)

        boundary = CONTROL_CONTRACT["dispatch_boundary"]
        self.assertEqual(boundary["controller"], "Supervisor/Checker")
        self.assertTrue(boundary["assignment_is_final_action"])
        self.assertEqual(boundary["post_dispatch_state"], "OFFLINE_WAITING_WORKER_SIGNAL")
        self.assertEqual(
            boundary["wake_signals"],
            [
                "WORKER_COMPLETION_RECEIPT",
                "WORKER_BLOCKER_RECEIPT",
                "WORKER_EXECUTION_FAILURE",
            ],
        )
        self.assertFalse(boundary["periodic_worker_inspection"])

    def test_checker_detection_system_and_supervisor_capability_supply(self):
        required = (
            "## Checker Detection System",
            "Checker responsibility must maintain one evolving detection system",
            "Supervisor responsibility must provision the Checker responsibility",
            "DETECTION_CAPABILITY_MANIFEST",
            "mature detection skills",
            "`superpowers:verification-before-completion`",
            "`superpowers:systematic-debugging`",
            "`superpowers:test-driven-development`",
            "`security-best-practices`",
            "`playwright`",
            "skill source, version, and compatibility",
            "Any skill that requires subagents is incompatible",
            "CodeGraph is mandatory for code or repository work",
            "layered detection stack",
            "Semgrep or CodeQL",
            "Gitleaks",
            "OSV-Scanner or Trivy",
            "Playwright",
            "coverage and mutation testing",
            "API or schema contract",
            "tool version, configuration, and omission rationale",
            "split or serialize the detection commands",
            "not acceptance quality",
            "structural and dependency baseline",
            "acceptance matrix",
            "false-positive",
            "REGRESSION_EVIDENCE",
            "CONDITION_BLOCKED",
            "must not accept a CELL from Worker self-report alone",
            "update the next CELL, GO revision, or supplementary GO",
        )
        for rule in required:
            with self.subTest(rule=rule):
                self.assertIn(rule, NORMALIZED_DETECTION)

    def test_go_detection_profile_is_planned_and_executed_for_every_cell(self):
        required = (
            "Every GO plan must declare one `GO_DETECTION_PROFILE`",
            "skills and tools are assigned to the GO, never ad hoc to a CELL",
            "Supervisor responsibility owns provisioning and approval of the profile",
            "Checker responsibility is the sole routine user of the assigned detection bundle",
            "Every CELL in that GO must execute every required skill and tool",
            "CELL_DETECTION_RECEIPT",
            "No required GO-level capability may be skipped",
            "Worker-run checks do not satisfy this Checker obligation",
            "If a capability is irrelevant to any CELL, redesign or split the GO",
            "Changing the bundle requires a versioned GO plan revision",
            "before the next CELL is dispatched",
            "arguments and affected paths may narrow per CELL, but capability membership may not",
        )
        for rule in required:
            with self.subTest(rule=rule):
                self.assertIn(rule, NORMALIZED_SKILL)
        self.assertNotIn("Not every optional layer runs for every CELL", SKILL)

    def test_markdown_context_boundary_is_hard_and_semantic(self):
        required = (
            "## Markdown Context Boundary",
            "Every Markdown file governed by the loop has a hard maximum of 1000 physical lines",
            "This is a Codex context-readability limit, not a device-capacity limit",
            "A stronger computer, model, or context window does not waive it",
            "WORK_CONTINUATION_INDEX",
            "MD_LINE_BUDGET_PASS",
            "split at a semantic work-continuation boundary",
            "must not hard-cut a requirement, table, code block, acceptance record, or evidence chain",
            "before the next append would exceed 1000 lines",
            "Every CELL acceptance checks all created or materially expanded Markdown files",
            "After context compaction or a shard transition",
            "read-only source or third-party Markdown",
            "markdown-line-budget",
        )
        for rule in required:
            with self.subTest(rule=rule):
                self.assertIn(rule, NORMALIZED_SKILL)
        self.assertNotIn("999 lines", SKILL)
        for path in ROOT.rglob("*.md"):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), 1000)

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
