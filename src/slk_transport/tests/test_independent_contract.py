"""Independent installed-wheel checks; no source-path or native Agent fixture."""
import unittest

from slk_transport.contracts import ContractError, Endpoint, canonical_json_sha256


class ContractTests(unittest.TestCase):
    def endpoint(self):
        return {"schema_version": "slk.transport-endpoint/v1", "run_id": "RUN-A",
                "role": "checker", "role_instance_id": "RUN-A-checker-1",
                "agent_runtime": "ocrv", "adapter": "ocrv-checker", "host_id": "host-a",
                "endpoint_version": 1, "state": "active",
                "address": {"launcher": "C:/tools/slk-checker.cmd"}}

    def test_exact_endpoint_retains_native_address(self):
        value = self.endpoint()
        parsed = Endpoint.from_dict(value)
        self.assertEqual(parsed.role_instance_id, "RUN-A-checker-1")
        self.assertEqual(parsed.address, value["address"])

    def test_title_is_not_an_endpoint(self):
        value = self.endpoint()
        value["conversation_title"] = "looks like the Checker"
        with self.assertRaises(ContractError):
            Endpoint.from_dict(value)

    def test_hash_is_order_independent_not_content_independent(self):
        self.assertEqual(canonical_json_sha256({"a": 1, "b": 2}),
                         canonical_json_sha256({"b": 2, "a": 1}))
        self.assertNotEqual(canonical_json_sha256({"a": 1}),
                            canonical_json_sha256({"a": 2}))


if __name__ == "__main__":
    unittest.main()
