# OCRV integration for SLK 4.4.2

OCRV is the registered original Checker, normally Qwen3.8-Max. Worker owns D0, original Checker owns D1, Supervisor owns D2. SLK never derives D1 from severity, finding counts, coverage, task_done, native exit or missing output.

Save and deliver every existing report/log, even partial, non-JSON or nonzero-exit output. Delivery is independent of TOKEN/state/Temporal engineering-dispatch guards; failure is reported as a communication fact. A saved file is not proof of delivery. No format supplement, synthesized terminal, classification correction or automatic review retry is required. Historical reports/FAIL remain unchanged and are not reinterpreted as new explicit decisions.

OCRV 1.12.13 is a stateless review harness. Its built-ins cannot call arbitrary shell commands. Its official MCP client supports stdio subprocesses and an explicit tool allowlist. The SLK integration exposes only `slk_checker_decide(verdict, message?)`; no source path, identity, credentials, shell or general executor is accepted from the model. Identity comes from the prepared host and native invocation receipt. Without a deliberate tool call no D1 is recorded. An action error is not PASS/FAIL and cannot prevent report delivery.

After deployment is independently authorized, generate this entry using the selected installed OCRV root and canonical installed transport. This function only emits configuration; merge its output into existing `mcp_servers`, preserving other settings. It does not edit global config or install a framework.

Deployment order (Supervisor only after acceptance): install the hash-bound method package and run its existing `integrations/ocrv/install.ps1 -OcrvRoot <selected OCRV root>`, then merge the MCP entry below. Before any real review, inspect the selected `ocr-slk.ps1` rule argument: Root confirmed this machine currently forces `D:/OCRV/slk/slk-d1-rule.json`, which references old `SLK-D1-REVIEW.md` prose claiming adapter classification. Keep the existing wrapper and rule JSON path. Retain the original config in the existing deployment backup, remove ONLY the `rules` entry referencing that legacy SLK Markdown, and preserve `include` byte-for-byte in meaning (including test files), `exclude` and unrelated configuration. Leave the old Markdown as history, not a loaded override; do not add a second SLK rule file or another wrapper. The generated background is the sole SLK responsibility prose loaded by the native review, with the bound tool description. A source/Skill update alone does not perform this deployment.

After that exact edit, compare before/after config: unchanged inclusion/exclusion and unrelated entries, no remaining legacy SLK prose override. Read back actual wrapper/config paths and installed hashes; run the normal native `--preview` for the unchanged candidate/scope and MCP tool discovery, checking test-file inclusion and the whole-candidate tool description. Preview/discovery is not a paid review or D1 proof. Missing/conflicting rules or tools keep product readiness blocked. Root performs this real-runtime edit and evidence collection after independent acceptance; this maintenance candidate did not inspect, change or dispatch the actual runtime.

```powershell
function Get-SlkCheckerMcpConfiguration([string]$OcrvRoot) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $launcher = (Get-Command slk-transport.cmd -ErrorAction Stop).Source
    $package = Join-Path (Split-Path $launcher) 'slk-transport.pyz'
    $bridge = Join-Path ([IO.Path]::GetFullPath($OcrvRoot)) 'slk_checker_decision.py'
    foreach ($path in @($package, $bridge)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing installed file: $path" }
    }
    @{slk_checker_decision=@{type='stdio'; command=$python;
        args=@('-B', $bridge, '--transport', $package); tools=@('slk_checker_decide')}} |
        ConvertTo-Json -Depth 5
}
```

The exact `--transport` package is placed first on the MCP subprocess import path; a source checkout/PYTHONPATH is not assumed. Optional `message` carries original Checker findings/reasons without a report template. The one deliberate tool call records D1 and runs the existing standard successor; OCRV needs no shell or second suffix invocation.

OCRV inherits the invocation-bound environment from the existing transport. Preparation must verify the configured tool is actually discoverable and local `slk_transport` resolves to the deployed package. No generic command tool or alternative D1 author may replace it. Offline protocol/action tests prove wiring and rejection only, not that the real model consistently makes a whole-candidate decision or calls the tool correctly.

Before a Run, verify version/update need, managed wrapper/capability hashes, headless execution, actual model/endpoint, native activity and available standard actions. Native preview is optional input planning, never a report-release test. Every helper remains headless and ends with its invocation; no daemon is added.

First formal FAIL goes to Supervisor for bounded guidance. After a second consecutive formal FAIL, Supervisor investigates more aggressively and considers smaller successor CELLs; this is role guidance, not a host verdict/rework veto. Only explicit role actions may advance engineering state or start next work.

Invocation boundary: OCRV may split the selected diff into semantic/per-file groups, each with its own plan/main conversation and the same registered tools. `--concurrency 1` serializes groups; it does not merge them. Native review identity is authority evidence, NOT proof of whole-candidate review. Existing `file_find`/`file_read_diff` permit cross-file inspection; the native diff map is injected before grouping. Background and tool descriptions require one decision for the entire frozen candidate/all CELL criteria, never one per file/group; unverified goals must not become whole-CELL PASS. Existing immutable action/dedup guards remain, but cannot prove model comprehension. No real product group count or model invocation was inspected here; offline tests verify instructions/wiring, not whole-candidate competence. This patch adds no grouping override, coverage gate, aggregate approval round or review Agent.

Protocol/source basis: [OCRV v1.12.13 MCP configuration](https://github.com/alibaba/open-code-review/blob/fabbdb29/pages/src/content/docs/en/mcp.md), [stdio environment and calls](https://github.com/alibaba/open-code-review/blob/fabbdb29/internal/mcp/client.go), [tool registration/allowlist](https://github.com/alibaba/open-code-review/blob/fabbdb29/internal/mcp/provider.go), [group dispatch and shared diff map](https://github.com/alibaba/open-code-review/blob/fabbdb29/internal/agent/agent.go), [grouping/fallback](https://github.com/alibaba/open-code-review/blob/fabbdb29/internal/agent/grouping.go). `--tools` overrides built-in definitions; it is not an arbitrary command runner.
