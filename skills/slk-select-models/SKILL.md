---
name: slk-select-models
description: Use when an active Small Loop Skill (SLK) Run needs role-specific model capability choices before member creation or after capability-related rework.
---

# Select and freeze role models

仅用于已启用 SLK 的 Run；Owner 决定具体型号/reasoning，角色不能自行推断、切换或升降级。

- Supervisor：推荐 Codex，当前能力参考 gpt-6.1-sol high/xhigh；Owner 决定实际平台/型号，低 Token 观察不意味着自动降为低性能模型。
- Checker 推荐 OCRV / Qwen3.8-Max，Worker 推荐 DSH / DeepSeek V4 Flash；推荐不是品牌白名单。4.5.5 新选择按真实适配能力登记，历史 Run 保持原冻结绑定，变更仍需原授权及版本化采用。
- OW：Supervisor 唯一直属观察 subagent。Owner 确认能完成核验的高效、低推理开销型号/reasoning；gpt-6-luna high/xhigh 仅推荐，不是 Luna 系列白名单或能力等级硬门槛。

登记真实 runtime/provider/model/reasoning、设备、Session、adapter、endpoint、上下文/任务容量及可写工作区；以当前 readiness 核实，不凭提示词自报。新 Run 用 preflight-new-run，续接用 preflight-admission，模型决定不替代身份/能力验证。

D1 FAIL 不自动升级 Worker；Supervisor 按 `$slk-rework-cell` 给同一 Worker 改进指引。需改冻结绑定仍先由 Owner 明确修订，再版本化登记/受影响复验。不用未登记对话、临时同级模型或第二 Worker/Checker 绕过原角色权威。未支持的平台或父子能力缺口如实说明，不因通用规则就声称已可接入；不另建独立 OW 绕开直属关系。
