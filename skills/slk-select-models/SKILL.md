---
name: slk-select-models
description: Use when an active Small Loop Skill (SLK) Run needs role-specific model capability choices before member creation or after capability-related rework.
---

# Select Models for an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

冻结并核对当前 SLK 的原生角色绑定，不在 CELL 之间自动换模型：Codex = Supervisor，固定 canonical `gpt-6.1-sol`，由 Owner 为每个 Run 选择 `high` 或 `xhigh`；OCRV = Checker（Qwen3.8-Max）；DSH = Worker（DeepSeek V4 Flash）。启用 Overwatcher 时，由 Owner 选择一款 Luna 级模型，例如 `gpt-5.6-luna`、`gpt-6-luna`，并冻结其 reasoning。

## 绑定规则

- readiness 同时核对角色、runtime、provider、model、reasoning、session、adapter、endpoint、上下文/任务容量、可写工作区与 Run；新 Run 使用 `slk-transport preflight-new-run`，续接使用 `preflight-admission`，提示词自称某角色不构成绑定。
- Supervisor 与 Overwatcher 的具体型号由 Owner 在创建或绑定前决定并冻结；同能力等级替代也需要登记真实型号并通过同一 readiness，不能由角色自行推断、升级、降级或静默替换。
- Checker 只使用登记的 `ocrv-checker` 端点，Worker 只使用登记的 `dsh-worker` 端点；Codex 对话不能代替二者。
- D1 FAIL 不自动把 DSH Worker 升级成其他模型；按 `$slk-rework-cell` 由 Codex Supervisor 为同一 Worker 生成受限改进指引。
- 改变已冻结角色型号需要 Owner 明确修订方法合同；Supervisor、Checker 和 Overwatcher 都不能自行降级、升级或静默替换。

## 负面提示词

- 不要把“Owner 可选同级型号”解释成角色可自行选型；不要用 Codex Checker、Codex Worker、能力相近、模型升级阶梯或“临时替代”绕过已冻结运行时；不要把返工指引当成模型切换、第二 Worker、第二 Checker 或验收权威。
