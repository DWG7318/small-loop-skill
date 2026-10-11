---
name: slk-select-models
description: Use when an active Small Loop Skill (SLK) Run needs role-specific model capability choices before member creation or after capability-related rework.
---

# Select and freeze role models

仅用于已启用 SLK 的 Run；Owner 决定具体型号/reasoning，角色不能自行推断、切换或升降级。

- Supervisor：Codex，canonical gpt-6.1-sol，由 Owner 选 high/xhigh。
- Checker：OCRV / Qwen3.8-Max；Worker：DSH / DeepSeek V4 Flash，保持既有冻结绑定。
- OW：Supervisor 唯一直属观察 subagent。Owner 确认能完成核验的高效、低推理开销型号/reasoning；gpt-6-luna high/xhigh 仅推荐，不是 Luna 系列白名单或能力等级硬门槛。

登记真实 runtime/provider/model/reasoning、设备、Session、adapter、endpoint、上下文/任务容量及可写工作区；以当前 readiness 核实，不凭提示词自报。新 Run 用 preflight-new-run，续接用 preflight-admission，模型决定不替代身份/能力验证。

D1 FAIL 不自动升级 Worker；Supervisor 按 `$slk-rework-cell` 给同一 Worker 改进指引。需改冻结绑定仍先由 Owner 明确修订，再版本化登记/受影响复验。不用 Codex 对话、临时同级模型或第二 Worker/Checker 绕过原角色权威。
