"""Current method admission is additive; independent tool versions stay independent."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


@pytest.mark.parametrize("filename", [
    "slk-checker-completion.schema.json", "slk-checker-management.schema.json",
    "slk-checker-post-d1.schema.json", "slk-subagent-overwatcher.schema.json",
    "slk-temporal-delivery.schema.json", "slk-temporal-standard-adapter.schema.json",
    "slk-temporal-standard-bootstrap.schema.json",
])
def test_method_contract_admits_453_and_preserves_prior_versions_but_not_unpublished_version(filename):
    schema = json.loads((Path(__file__).parents[2] / "docs" / "contracts" / filename).read_text())
    def method_contracts(value):
        if isinstance(value, dict):
            if "method_version" in value.get("properties", {}):
                yield value["properties"]["method_version"]
            for item in value.values():
                yield from method_contracts(item)
        elif isinstance(value, list):
            for item in value:
                yield from method_contracts(item)
    contracts = list(method_contracts(schema))
    assert contracts
    for contract in contracts:
        validator = Draft202012Validator(contract)
        for version in ("4.5.0", "4.5.1", "4.5.2", "4.5.3"):
            assert validator.is_valid(version)
        assert not validator.is_valid("4.5.4")


def test_transport_method_admission_is_additive_and_closed():
    from slk_transport import SUPPORTED_METHOD_VERSIONS

    assert all(version in SUPPORTED_METHOD_VERSIONS for version in ("4.5.0", "4.5.1", "4.5.2", "4.5.3"))
    assert "4.5.4" not in SUPPORTED_METHOD_VERSIONS
