---
name: slk-select-models
description: Use when an active Small Loop Skill (SLK) Run needs role-specific model capability choices before member creation or after capability-related rework.
---

# Select Models for an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

为 Supervisor、Checker、Worker 选择与角色和当前工程相称的专业编程模型，同时保留后续调整空间和跨平台可替换性。

## 建议依据

- 按 Owner 指定、角色基准、当前 CELL 难度、返工信号的顺序判断；初始选择覆盖三个角色，但不是让三个角色共同投票。规划阶段先为每个角色选定模型，施工中再由 Checker 或 Supervisor 按各自边界调整当前返工 CELL 的 Worker。
- 判断 Worker CELL 时看边界、已有实现路径、验证入口、跨模块联动、风险与环境未知量。明显小的 CELL 通常同时具备边界清楚、已有实现路径、直接验证入口，且没有显著跨模块联动、迁移或未知环境；如果不能明确判断为小 CELL，就按常规 CELL 选择。
- 以能力层级描述选择；不同平台中能力相近的模型可以替换，但替换不应把能力降到基准线以下。
- 记录三个角色的选择、理由和可替换范围，不把一次选择冻结为整个 Run 的固定型号。

## 三个角色基准线

| 角色 | 当前建议基准 |
|---|---|
| Supervisor | `gpt-5.6-sol` + `xhigh`，用于方法理解、调整决策、豁免和 D2 组合检查。 |
| Checker | `gpt-5.6-sol` + `medium`，用于日常派发与隔离 D1。 |
| Worker | 常规 CELL 使用 `gpt-5.6-terra` + `high`；只有明显小的 CELL 才使用 `gpt-5.6-luna` + `xhigh`。 |

这些是每个新 CELL 的选择基准，不是整个 Run 的永久绑定，也不妨碍不同平台使用能力相近的可替换模型。

## 当前 CELL 的升级阶梯

第一次 D1 FAIL 先用原模型做针对性返工。同一 CELL 第二次 D1 返工，或同一 Run 第一次 D2 返工时，只升级负责当前返工 CELL 的 Worker：小 CELL 路径为 `Luna xhigh → Terra high`，常规路径为 `Terra high → Sol medium`。

升级后再次 FAIL，即第三次 D1 或同一 Run 第二次 D2 时，再升级当前 Worker：`Terra high → Sol medium；Sol medium → Sol high`。同时由 Checker 重新规划当前 CELL；D2 情境由 Supervisor 重新规划当前修复 CELL。可以把 CELL 一分为二或另选施工方案，不只依靠继续提高模型。

升级只跟随当前 CELL。该 CELL 完成或被重新划分后，下一个 CELL 重新从基准线选择；拆出的新 CELL 也按各自实际范围重新选择。Checker 与 Supervisor 不因 D1 或 D2 FAIL 自动升级。

## Owner 指定

Owner 可以直接指定 Supervisor、Checker 或 Worker 使用的模型；这种选择不违反本 Skill，也不因偏离建议层级而被判定为错误。Agent 记录 Owner 指定及其对施工能力、电脑和 CELL 大小的影响，必要时相应调整 CELL，但不擅自替换 Owner 指定的模型。

Owner 已指定某个角色模型时，后续“提高一级”不自动覆盖该指定；确实值得变更时，由 Supervisor 先说明理由、影响和 CELL 调整方案，再由 Owner 决定是否改变自己的指定。

## 施工中的调整

- CELL 的大小与 Worker 能力、电脑和累积工程量相互匹配，并保留余量。
- D1 或 D2 返工需要模型变化、且 Worker 模型未由 Owner 直接指定时，按当前 CELL 的升级阶梯选择。
- 本 Skill 由 `$slk-adjust-run` 调用时，完成模型选择后返回当前调整，由 Supervisor 统一记录和交还施工；这样不另起一轮重复调整。
