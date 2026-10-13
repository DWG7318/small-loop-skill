# SLK Overwatch tools 1.0.1

Small, deterministic, read-only helpers used by SLK transport. This is not an
Agent, runtime manager, monitor service, timer, message sender or state writer.
Runtime and the wheel builder use only Python's standard library (Python 3.10+).

- `inspect_cadence(projection, observed_at=..., current_method=..., native_subagent=...)`
  calculates the existing cadence result. The caller supplies method policy;
  the helper does not maintain an SLK version allowlist or assert live execution.
- `read_codex_subagent_snapshot(request, original_sample_id=None)` reads exactly
  the caller-selected private Codex JSONL source and returns hashes, original
  times and status metadata. The caller must authenticate the source location,
  current registration and execution binding before calling it. A snapshot is
  not a native-start proof, host attestation or authorization to act.

The transport public functions and exception names remain compatibility facades.
Native-start creation/validation, proof writing, permissions, message delivery,
central state and Temporal remain outside this package. Malformed, ambiguous or
missing native evidence raises an error rather than inventing a fresh sample.
There are no model-output, record-length or source-size limits in these readers.

## Independent development and prebuilt use

From this repository's root, after installing the prebuilt wheel:

```powershell
python -m pip install --no-index artifacts/slk_overwatch_tools-1.0.1-py3-none-any.whl
python -m unittest discover -s tests -v
```

Developer-only build (no dependency installation or compiler):

```powershell
python build_wheel.py
```

This writes the reproducible wheel and `artifacts/BUILD_INPUTS.json`, containing
source input hashes and the actual wheel hash, not a circular self-commit hash.
`python -m pip wheel --no-deps --no-index .` also uses the same standard-library
PEP 517 builder. Parent SLK packages this exact runtime dependency explicitly;
ordinary users call the unified SLK installer, not these development commands.

The included tests use simulated records only. They do not claim a real Agent
Run, reach into the user's sessions, or replace source-location authorization.
