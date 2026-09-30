---
name: slk-select-models
description: Use when an active Small Loop Skill (SLK) Run needs role-specific model capability choices before member creation or after capability-related rework.
---

# Select Models for an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

冻结并核对当前 SLK 的原生角色绑定，不在 CELL 之间自动换模型：Codex = Supervisor（`gpt-5.6-sol` + `xhigh`），OCRV = Checker（Qwen3.8-Max），DSH = Worker（DeepSeek V4 Flash）。

## 绑定规则

- readiness 同时核对角色、runtime、provider、model、reasoning、session、adapter、endpoint、上下文/任务容量、可写工作区与 Run；使用 `slk-transport preflight-run` 形成闭合结果，提示词自称某角色不构成绑定。
- Checker 只使用登记的 `ocrv-checker` 端点，Worker 只使用登记的 `dsh-worker` 端点；Codex 对话不能代替二者。
- D1 FAIL 不自动把 DSH Worker 升级成其他模型；按 `$slk-rework-cell` 由 Codex Supervisor 为同一 Worker 生成受限改进指引。
- 改变固定角色或模型需要 Owner 明确修订方法合同；Supervisor、Checker 和 Overwatcher 都不能自行降级、升级或静默替换。

## 负面提示词

- 不要用 Codex Checker、Codex Worker、能力相近、模型升级阶梯或“临时替代”绕过固定运行时；不要把返工指引当成模型切换、第二 Worker、第二 Checker 或验收权威。
