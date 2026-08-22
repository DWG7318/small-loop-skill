---
name: slk-diagnose-defect
description: Use when an SLK CELL rework is not converging because the defect cause remains unclear or contradictory.
---

# Diagnose a Defect

## 当前目标

用较小的诊断成本找到足以指导修复的原因，再把结果交回普通 CELL 返工。

## 建议做法

1. 固定当前失败候选、现象、环境和 D1 证据，尝试稳定复现。
2. 若暂时未复现，记录已经验证的条件和未复现证据，寻找与原环境最关键的差异。
3. 每轮选择一个假设，并设计一个能区分该假设真假的小实验。
4. 实验支持根因后，选择最小修复范围；实验不支持时，保留结果并换一个更有信息量的假设。
5. 根据缺陷风险和可重现程度选择回归证据。稳定且重要的缺陷适合保留失败前、修复后和相关回归；偶发或环境性问题可以使用风险相称的替代证据。
6. 汇总复现情况、实验、根因判断、最小修复建议、剩余不确定性和建议验证。

## 完成后

把诊断结果交回 `$slk-rework-cell`。Worker据此修复，Checker继续对原 D1 验收目标负责。
