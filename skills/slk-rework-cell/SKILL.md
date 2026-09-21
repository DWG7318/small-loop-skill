---
name: slk-rework-cell
description: Use when an active Small Loop Skill (SLK) Run has a D1 FAIL and the same CELL needs focused rework.
---

# Rework a CELL

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

由 Checker 与 Worker 根据 Checker 的 D1 FAIL 修复当前 CELL，并保持原验收目标和清楚的返工历史；Worker 在交付前的 D0 草稿自修单独记录为本地尝试。

## 建议做法

1. Checker 汇总失败现象、复现方式、期望结果和本轮最值得修复的差距。
2. Worker 继续处理同一 `CELL n/N`，先确认自己理解 D1 意见，再进行针对性修改。
3. 普通返工优先聚焦已知差距。错误原因仍不清楚时，可以调用当前环境中适合项目的 Debug Skill，例如 `$superpowers:systematic-debugging`；诊断完成后仍回到同一 CELL 和原 D1 目标。
4. 第一次 D1 FAIL 使用当前 Worker 模型做针对性返工；同一 CELL 第二次 D1 返工时，调用 `$slk-select-models` 为当前 CELL 做第一次升级。第三次 D1 FAIL 时执行第二次升级，并由 Checker 重新规划当前 CELL，可以调用 `$slk-dispatch-cell` 一分为二或另选施工方案，同时保留原验收目标。Owner 已指定模型时先保留该模型，确实值得变更时交给 Supervisor 形成建议并由 Owner 决定。
5. Worker 完成修改和最低 D0 后，使用 `$slk-execute-cell` 的记录与交付方式重新提交。
6. Checker 使用 `$slk-check-cell` 针对修复目标、受影响范围和相关回归重新执行 D1，保留未受影响且仍有效的已完成工作与客观证据，不复用通过结论；本轮错误、变化和结果由各自通过 `slk-state` 追加，不覆盖前轮事实，不重复施工未受影响且仍有效的已完成工作。

## 连续未收敛

第三次 D1 FAIL 后先重新规划当前 CELL；调整超出当前 CELL、影响后续 CELL 或 Run 时，Checker 再把完整情况交给 Supervisor。Supervisor 使用 `$slk-adjust-run` 综合考虑继续诊断、形成电脑或环境变更建议、调整路线或暂时豁免。

## 负面提示词

- 不要把 D0 草稿自修或 Checker 自建检查器故障计入 Worker 的 D1 返工次数；不要为局部修复重跑未受影响的全部有效检查，也不要借返工擅改原验收目标、重复施工未受影响且仍有效的已完成工作或覆盖 Owner 指定模型。
