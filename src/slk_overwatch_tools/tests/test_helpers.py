"""Independent deterministic helper tests; native records below are simulations."""
from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


class HelperCase(unittest.TestCase):
    def helpers(self):
        self.assertIsNotNone(importlib.util.find_spec("slk_overwatch_tools"),
                             "the independent OW helper package is not implemented")
        module = importlib.import_module("slk_overwatch_tools")
        for name in ("inspect_cadence", "read_codex_subagent_snapshot", "native_object",
                     "OverwatcherContinuityError", "OverwatcherSubagentError"):
            self.assertTrue(hasattr(module, name), f"independent helper API {name} is not implemented")
        return module


class CadenceTests(HelperCase):
    def projection(self):
        return {"summary": {"run_id": "run-a", "slk_version": "caller-owned-version"},
                "roles": [{"role": "overwatcher", "lifecycle": "active", "role_instance_id": "ow-a",
                           "session_id": "/root/ow", "foreground_turn_id": "activation-a"}],
                "overwatch_cycles": [{"cycle_id": "cycle-a", "cycle_sequence": 1,
                    "overwatcher_role_instance_id": "ow-a", "run_id": "run-a", "session_id": "/root/ow",
                    "foreground_turn_id": "activation-a", "cadence_seconds": 600,
                    "completed_at": "2026-10-11T00:00:00Z", "next_cycle_at": "2026-10-11T00:10:00Z"}]}

    def inspect(self, projection=None, at="2026-10-11T00:10:00Z", **policy):
        return self.helpers().inspect_cadence(projection or self.projection(), observed_at=at,
                    current_method=policy.get("current_method", True),
                    native_subagent=policy.get("native_subagent", True))

    def test_current_boundary_does_not_claim_native_liveness(self):
        result = self.inspect()
        self.assertEqual((result["status"], result["action"], result["missed_intervals"]), ("CURRENT", "NONE", 1))
        self.assertNotIn("native_status", result)

    def test_late_native_child_is_reported_to_supervisor_not_woken(self):
        result = self.inspect(at="2026-10-11T00:10:01Z")
        self.assertEqual((result["status"], result["action"]), ("LATE", "SUPERVISOR_RECOVERY_REVIEW"))

    def test_twice_cadence_boundary_and_unproven_after_it(self):
        self.assertEqual(self.inspect(at="2026-10-11T00:20:00Z")["status"], "LATE")
        self.assertEqual(self.inspect(at="2026-10-11T00:20:01Z")["status"], "CONTINUITY_UNPROVEN")

    def test_policy_is_supplied_by_caller_not_inferred_from_version(self):
        projection = self.projection()
        projection["summary"]["slk_version"] = "4.5.0"
        projection["overwatch_cycles"][0].update(cadence_seconds=240, next_cycle_at="2026-10-11T00:04:00Z")
        result = self.inspect(projection, at="2026-10-11T00:05:00Z", current_method=False, native_subagent=False)
        self.assertEqual(result["action"], "WAKE_BOUND_OVERWATCHER")

    def test_current_missing_role_is_unproven_legacy_missing_role_absent(self):
        projection = self.projection()
        projection["roles"] = []
        self.assertEqual(self.inspect(projection)["anomaly_codes"], ["OVERWATCHER_MISSING"])
        self.assertEqual(self.inspect(projection, current_method=False)["status"], "ABSENT")

    def test_other_run_child_or_activation_cannot_supply_current_cycle(self):
        for field, value in (("run_id", "run-b"), ("session_id", "/root/other"), ("foreground_turn_id", "old")):
            with self.subTest(field=field):
                projection = self.projection()
                projection["overwatch_cycles"][0][field] = value
                self.assertEqual(self.inspect(projection)["status"], "CONTINUITY_UNPROVEN")

    def test_projection_is_not_mutated(self):
        projection = self.projection()
        original = copy.deepcopy(projection)
        self.inspect(projection)
        self.assertEqual(projection, original)

    def test_invalid_cadence_boundary_and_timestamps_remain_errors(self):
        for field, value in (("cadence_seconds", True), ("cadence_seconds", 240),
                             ("next_cycle_at", "2026-10-11T00:11:00Z"), ("completed_at", "2026-10-11T00:00:00")):
            with self.subTest(field=field, value=value):
                projection = self.projection()
                projection["overwatch_cycles"][0][field] = value
                with self.assertRaises(self.helpers().OverwatcherContinuityError):
                    self.inspect(projection)


class NativeRecordsTests(HelperCase):
    timestamp = "2026-10-11T00:00:00Z"
    child = "/root/ow"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "simulated.jsonl"
        self.records = [{"timestamp": self.timestamp, "type": "session_meta", "payload": {"id": "parent-a"}},
            self.record("function_call", "call_spawn", namespace="collaboration", name="spawn_agent",
                        arguments=json.dumps({"task_name": "ow", "message": "PRIVATE PROMPT"})),
            self.record("function_call_output", "call_spawn", output=json.dumps({"task_name": self.child})),
            *self.sample("call_list", "running")]
        self.request = {"native_source_path": str(self.source), "native_execution_id": "codex-subagent-spawn:call_spawn",
                        "native_address": {"agent_id": self.child, "parent": {"session_id": "parent-a"}}}

    def record(self, kind, call_id, **payload):
        return {"timestamp": self.timestamp, "type": "response_item", "payload": {"type": kind, "call_id": call_id, **payload}}

    def sample(self, call_id, status, **arguments):
        return [self.record("function_call", call_id, namespace="collaboration", name="list_agents", arguments=json.dumps(arguments)),
                self.record("function_call_output", call_id,
                    output=json.dumps({"agents": [{"agent_name": self.child, "agent_status": status}]}))]

    def save(self):
        self.source.write_bytes(b"".join((json.dumps(record) + "\n").encode() for record in self.records))

    def snapshot(self, original_sample_id=None):
        self.save()
        return self.helpers().read_codex_subagent_snapshot(self.request, original_sample_id=original_sample_id)

    def test_original_record_hashes_and_sample_time_are_preserved(self):
        result = self.snapshot()
        self.assertEqual(result["sample_query_timestamp"], self.timestamp)
        self.assertEqual(result["agent_status"], "RUNNING")
        self.assertEqual(result["sample_call_sha256"], hashlib.sha256(json.dumps(self.records[3]).encode()).hexdigest())
        self.assertEqual(set(result["samples"]), {"call_list"})

    def test_read_only_repeat_does_not_create_proof_refresh_time_or_leak_bodies(self):
        first = self.snapshot()
        before = self.source.read_bytes()
        second = self.helpers().read_codex_subagent_snapshot(self.request)
        self.assertEqual(first, second)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.source.parent.iterdir()), [self.source])
        self.assertNotIn("PRIVATE PROMPT", json.dumps(first))

    def test_later_completion_is_read_without_exporting_completion_text(self):
        self.records.extend(self.sample("call_done", {"completed": "PRIVATE COMPLETION"}))
        result = self.snapshot(original_sample_id="call_list")
        self.assertEqual(result["agent_status"], "COMPLETED")
        self.assertEqual(result["samples"]["call_list"]["agent_status"], "RUNNING")
        self.assertNotIn("PRIVATE COMPLETION", json.dumps(result))

    def test_missing_return_is_not_assumed_running(self):
        self.records.pop()
        with self.assertRaises(self.helpers().OverwatcherSubagentError):
            self.snapshot()

    def test_ambiguous_pair_and_duplicate_parent_are_rejected(self):
        for record in (self.records[1], self.records[0]):
            with self.subTest(record=record["type"]):
                self.records.append(record)
                with self.assertRaises(self.helpers().OverwatcherSubagentError):
                    self.snapshot()
                self.records.pop()

    def test_unrelated_large_tool_body_has_no_read_cap_and_is_not_returned(self):
        self.records[3:3] = [self.record("function_call", "call_unrelated", namespace="functions", name="exec_command",
                    arguments=json.dumps({"body": "PRIVATE" * 2000})),
                    self.record("function_call_output", "call_unrelated", output="PRIVATE" * 2000)]
        result = self.snapshot()
        self.assertEqual(result["agent_status"], "RUNNING")
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_new_query_for_another_child_does_not_replace_this_child_sample(self):
        self.records.extend(self.sample("call_other", "running", path_prefix="/root/other"))
        self.assertEqual(self.snapshot()["sample_call_id"], "call_list")

    def test_unknown_latest_status_cannot_fall_back_to_older_running(self):
        self.records.extend(self.sample("call_unknown", "unrecognized"))
        with self.assertRaises(self.helpers().OverwatcherSubagentError):
            self.snapshot()

    def test_duplicate_json_keys_are_not_silently_overwritten(self):
        with self.assertRaises(self.helpers().OverwatcherSubagentError):
            self.helpers().native_object('{"payload": {}, "payload": {"type": "running"}}')

    def test_explicit_cross_rollout_snapshot_preserves_each_record_source(self):
        current = self.source.with_name("current.jsonl")
        current.write_text("".join(json.dumps(item) + "\n" for item in [self.records[0], *self.records[3:]]))
        del self.records[3:]
        self.request.pop("native_source_path")
        self.request["native_source_paths"] = [str(self.source), str(current)]
        result = self.snapshot()
        self.assertEqual(result["agent_status"], "RUNNING")
        self.assertEqual(result["record_sources"]["spawn_call"]["path"], str(self.source))
        self.assertEqual(result["record_sources"]["sample_output"]["path"], str(current))
        self.assertEqual(result["record_sources"]["sample_output"]["line"], 3)
        self.assertEqual([item["path"] for item in result["source_metadata"]], self.request["native_source_paths"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_each_explicit_source_requires_its_own_unambiguous_parent_metadata(self):
        current = self.source.with_name("current.jsonl")
        self.request.pop("native_source_path")
        self.request["native_source_paths"] = [str(self.source), str(current)]
        for metadata in ([], [self.records[0], self.records[0]],
                         [{"type": "session_meta", "payload": {"id": "another-parent"}}]):
            with self.subTest(metadata=metadata):
                current.write_text("".join(json.dumps(item) + "\n" for item in metadata))
                with self.assertRaises(self.helpers().OverwatcherSubagentError):
                    self.snapshot()


if __name__ == "__main__":
    unittest.main()
