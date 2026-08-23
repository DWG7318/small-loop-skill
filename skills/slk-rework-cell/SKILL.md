---
name: slk-rework-cell
description: Use when an active Small Loop Skill (SLK) Run has a D1 FAIL and the same CELL needs focused rework.
---

# Rework a CELL

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

由 Checker 与 Worker 根据 D1 FAIL 修复当前 CELL，并保持原验收目标和清楚的返工历史。

## 建议做法

1. Checker 汇总失败现象、复现方式、期望结果和本轮最值得修复的差距。
2. Worker 继续处理同一 `CELL n/N`，先确认自己理解 D1 意见，再进行针对性修改。
3. 普通返工优先聚焦已知差距。错误原因仍不清楚时，可以调用当前环境中适合项目的 Debug Skill，例如 `$superpowers:systematic-debugging`；诊断完成后仍回到同一 CELL 和原 D1 目标。
4. 当前 Worker 能力不足、且模型未由 Owner 直接指定时，建议把能力提高一级；Owner 已指定时先保留该模型，Checker 可以校准 CELL，确实值得换模型时交给 Supervisor 形成建议并由 Owner 决定。D1 表明任务本身过大时，Checker 可以调用 `$slk-dispatch-cell`，按一分为二的方法重新派发，并共同保留原验收目标。
5. Worker 完成修改和最低 D0 后，使用 `$slk-execute-cell` 的记录与交付方式重新提交。
6. Checker 使用 `$slk-check-cell` 重新执行 D1，并记录本轮错误、变化和结果。

## 连续未收敛

通常两轮针对性返工仍未通过时，Checker 可以把完整情况交给 Supervisor。Supervisor 使用 `$slk-adjust-run` 综合考虑继续诊断、提高能力、形成电脑或环境变更建议、调整路线或暂时豁免。
