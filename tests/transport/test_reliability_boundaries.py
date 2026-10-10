"""Local trusted-file/identifier limits are not security or semantic boundaries."""
import hashlib
import json

import pytest

from slk_transport import contracts, role_eval, run_readiness
from slk_temporal import contracts as temporal_contracts, delivery_client, recovery_client, standard_adapter


@pytest.mark.parametrize("pattern", [contracts.IDENTIFIER, role_eval.IDENTIFIER,
    temporal_contracts.IDENTIFIER, standard_adapter.IDENTIFIER])
def test_safe_identifier_grammar_has_no_arbitrary_length_limit(pattern):
    assert pattern.fullmatch("RUN-" + "a" * 512)
    for unsafe in ("RUN/other", "../RUN", "RUN\\other", "RUN a", "RUN\n"):
        # A dot-only prefix was historically valid in Temporal; separators are not.
        if "/" in unsafe or "\\" in unsafe or " " in unsafe or "\n" in unsafe:
            assert not pattern.fullmatch(unsafe)


@pytest.mark.parametrize("reader", ["readiness", "delivery", "recovery"])
def test_hash_bound_local_proof_accepts_large_original_json_and_rejects_changed_bytes(tmp_path, reader):
    path = tmp_path / "proof.json"
    raw = b'{"original":true}' + b" " * (16 * 1024 * 1024 + 1)
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    proof = {"path": str(path), "sha256": digest}
    def read():
        if reader == "readiness": return run_readiness._proof(proof)
        if reader == "delivery": return delivery_client._load_hashed(path, digest, "local proof")
        return recovery_client.read_proof(proof, "local proof")
    assert read() == {"original": True}
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError):
        read()
