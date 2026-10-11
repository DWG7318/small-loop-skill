"""Installed-template contract checks; no server or real Run is started."""
import unittest

from slk_temporal.contracts import ContractError, StartSlkRequest, notification_native_id


class ContractTests(unittest.TestCase):
    def request(self):
        return {"run_id": "RUN-A", "method_version": "4.5.0", "runtime_revision": 0,
                "task_queue": "slk-local", "ack_timeout_seconds": 60,
                "startup_idempotency_key": "start-a",
                "roles": [{"role": role, "role_instance_id": f"a-{role.lower()}",
                           "endpoint_ref": f"endpoint-{role.lower()}"}
                          for role in ("SUPERVISOR", "CHECKER", "WORKER", "OVERWATCHER")]}

    def test_startup_keeps_unique_exact_roles(self):
        parsed = StartSlkRequest.from_dict(self.request())
        self.assertEqual(parsed.supervisor.role_instance_id, "a-supervisor")
        self.assertEqual(parsed.overwatcher.role_instance_id, "a-overwatcher")
        self.assertEqual(parsed.to_dict(), self.request())

    def test_duplicate_role_address_is_rejected(self):
        value = self.request()
        value["roles"][1]["endpoint_ref"] = value["roles"][0]["endpoint_ref"]
        with self.assertRaises(ContractError):
            StartSlkRequest.from_dict(value)

    def test_notification_identity_is_per_run_and_event(self):
        self.assertEqual(notification_native_id("RUN-A", "event-1"),
                         notification_native_id("RUN-A", "event-1"))
        self.assertNotEqual(notification_native_id("RUN-A", "event-1"),
                            notification_native_id("RUN-B", "event-1"))


if __name__ == "__main__":
    unittest.main()
