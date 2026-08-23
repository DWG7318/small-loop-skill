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

- 先看角色职责；规划阶段参考拟施工工作的难度与范围，施工中再看当前 CELL、累积工程量、电脑配置和可用环境。
- 以能力层级描述选择；不同平台中能力相近的模型可以替换。
- 记录三个角色的选择、理由和可替换范围，不把一次选择冻结为整个 Run 的固定型号。

## 三个角色

| 角色 | 建议能力 |
|---|---|
| Supervisor | 相对较强且专业的编程与推理模型，适合方法理解、升级决策、豁免和 D2 组合检查。 |
| Checker | 相对较强且专业的编程模型，适合隔离完成独立审查；通常不弱于当前 Worker。 |
| Worker | 仍使用可靠的专业编程模型。CELL 边界清楚、难度合适时，可以比 Supervisor 与 Checker 降低一级，但不能太低到无法稳定理解工程、施工和测试。 |

## Owner 指定

Owner 可以直接指定 Supervisor、Checker 或 Worker 使用的模型；这种选择不违反本 Skill，也不因偏离建议层级而被判定为错误。Agent 记录 Owner 指定及其对施工能力、电脑和 CELL 大小的影响，必要时相应调整 CELL，但不擅自替换 Owner 指定的模型。

Owner 已指定某个角色模型时，后续“提高一级”不自动覆盖该指定；确实值得变更时，由 Supervisor 先说明理由、影响和 CELL 调整方案，再由 Owner 决定是否改变自己的指定。

## 施工中的调整

- CELL 的大小与 Worker 能力、电脑和累积工程量相互匹配，并保留余量。
- D1 返工显示当前能力不足、且 Worker 模型未由 Owner 直接指定时，可以让 Worker 提高一级，再继续同一 CELL。
- 本 Skill 由 `$slk-adjust-run` 调用时，完成模型选择后返回当前调整，由 Supervisor 统一记录和交还施工；这样不另起一轮重复调整。
