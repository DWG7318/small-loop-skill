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
def test_method_contract_admits_452_and_preserves_451_but_not_unpublished_version(filename):
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
        assert validator.is_valid("4.5.1")
        assert validator.is_valid("4.5.2")
        assert not validator.is_valid("4.5.3")
