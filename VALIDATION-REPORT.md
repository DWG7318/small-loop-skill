# Validation Report — SLK 2.4.0

Local validation date: 2026-07-30
Local platform: Windows, Python 3.14

## Verified locally

- PASS: repository identity, root/install mirrors, file set, and SHA-256 Manifest;
- PASS: official minimal Serial Plan and referenced frozen GO Contract hashes;
- PASS: 48 pytest contract, causal-repair, negative, integrity, and cross-platform
  configuration tests;
- PASS: 33 focused causal-repair and invariant tests;
- PASS: invalid plans, Candidate-binding mismatches, missing D1 PASS Candidate/
  lineage anchors, invalid round/count states, and fourth ordinary repair attempts
  remain rejected under `python -O`;
- PASS: blank D0-D3, Owner, and Run templates are `PENDING`;
- PASS: D1 lineage binding, one-hypothesis/one-experiment D0 evidence,
  complete ORIGINAL/REPAIR PASS/FAIL Candidate, round, and rejection-count matrix,
  regression-first/exemption paths, and the third-rejection gate;
- PASS: temporary installed-skill smoke check, UTF-8 reads, YAML parsing, JSON
  contract parsing, and local reference closure;
- PASS: sensitive-information and method-boundary scans plus Git diff whitespace
  validation.

## Remote evidence boundary

GitHub Actions runs the same validation on `ubuntu-latest` and `windows-latest`.
This report does not claim remote CI success until the pull-request checks complete.
