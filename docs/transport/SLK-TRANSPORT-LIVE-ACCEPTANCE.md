# SLK Cross-Agent Transport Live Acceptance

- Date: 2026-09-20 (Asia/Shanghai)
- Accepted transport source commit: `3bb79b45252e256d3b4529384cd57896db2dd448`
- Accepted artifact SHA-256: `3240dfe9d9c1fa21b67eb0bcd9e42a54a89c0672ae99b582cbd132986bba461c`
- Evidence root: `D:\SLK\.codex\.tmp\slk-transport-live-20260920-012838\evidence`
- Independent verifier result: `TRANSPORT_DRILL_PASS`
- Source worktree: clean before and after the live drill; the drill changed only disposable repositories and external runtime/evidence roots.

## Accepted Runs

| Run | Legs | TOKEN | OCRV verdict | Retired endpoint | Failed boundary | Crossover |
|---|---|---:|---|---|---|---|
| `RUN-LIVE-A-20260920-012838` | `S-C → C-W → W-C → C-S` | `1 → 4` | `PASS` | v1 rejected; v2 completed | token stayed at 2 | none |
| `RUN-LIVE-B-20260920-012838` | `S-C → C-W → W-C → C-S` | `1 → 4` | `PASS` | v1 rejected; v2 completed | token stayed at 2 | none |

The first `S-C` send in each Run was executed by its temporary Codex Supervisor Agent. The drill harness did not call the first Checker delivery in place of that Supervisor. Each final `C-S` leg resumed the exact Supervisor thread and completed an exact turn.

## Redacted native identity proof

The following values are SHA-256 hashes of native identities. Raw thread, session, and review identities remain only in the local evidence tree.

| Run | Codex Supervisor thread | DSH Worker session | OCRV Checker session |
|---|---|---|---|
| A | `392e430d72e7a211248769fca665ea68f0b1c5951a63e34a5113641e5d29de55` | `23e95b13edfecbd11df965a2921545cd159b875ab628e27b95264c7e45d70ae9` | `fb6d8213b891a560767ff3641d7f9df98928931d8b915a14b0a0274cd6f290e1` |
| B | `c8568068cd6469fe0233003ec646b6a69c657ee11afc9cd4c20bc43908d8dac4` | `3b5e663f38255dc38bb2d92f6857bf3bc946466690b9ba2041e1b39abc4d2340` | `5dd0567557189c806db58d0a20851142b81f3c7c50edd8706a8b2a6ed44b9487` |

All six hashes differ. Each Run also has a distinct OCRV review invocation and Codex final turn. Both OCRV invocations used `dashscope-tokenplan / qwen3.8-max`; both returned `PASS`.

## Evidence interpretation

For each Run, the independent verifier required exactly four attempt directories with `endpoint.json`, `envelope.json`, `accepted.json`, `started.json`, and `completed.json`; it parsed the closed endpoint/envelope/result contracts, checked TOKEN sequences `1..4`, matched every role edge and payload type, compared Worker and final Supervisor nonces, required OCRV `PASS`, required unique native identities across Runs, and scanned each Run tree for the other Run's nonce.

## Pre-acceptance corrections

Three failed diagnostic runs were retained outside this accepted evidence root and were not counted as acceptance:

1. A newly created Codex thread was closed before its first turn and therefore could not be resumed. Bootstrap now keeps one App Server connection through that first turn.
2. `cmd.exe /c` truncated the multiline DSH contract, and the Worker sandbox could not write directly to the external evidence root. Live DSH uses the PowerShell entry, writes to a bounded workspace drop, and the host adapter validates, copies once to immutable evidence, then removes the drop.
3. A text-only disposable candidate caused OCRV to skip review, and the transport confused the OCR engine exit code with the wrapper verdict exit code. The drill now supplies a minimal reviewable Python candidate and preserves a structurally valid `INCOMPLETE` as non-PASS instead of misreporting it as an invalid transport result.

No diagnostic failure was reclassified as a PASS.
