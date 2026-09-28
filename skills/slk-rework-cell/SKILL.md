---
name: slk-rework-cell
description: Use when an active Small Loop Skill (SLK) Run has a D1 FAIL and the same CELL needs focused rework.
---

# Rework a CELL

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

由 OCRV Checker、Codex Supervisor 与同一 DSH Worker 根据正式 D1 FAIL 修复当前 CELL，并保持原验收目标和清楚的返工历史；Worker 在交付前的 D0 草稿自修单独记录为本地尝试。

## 建议做法

1. OCRV Checker 写入 `D1_FAILED`，再发送结构化 `D1_FAILURE_ESCALATION` 与 TOKEN 给 Supervisor；载荷绑定失败事件、候选哈希、返工轮次、CELL 目标、验收条件、具体 findings 与证据引用。
2. Supervisor 不重做或接管 D1、不改变验收目标；只基于冻结 CELL 与 OCRV 失败事实写入 `REWORK_REQUESTED` state event，并形成 `D1_REWORK_DIRECTIVE` transport payload，给出一个根因假设、一个最小实验、最小修复边界和回归目标。
3. Supervisor 把 `D1_REWORK_DIRECTIVE` 与 TOKEN 直接交给同一 DSH Worker 后结束本轮；这是 `Supervisor → Worker` 唯一合法情形，不构成一般派工通路。
4. Worker 继续处理同一 `CELL n/N`，自行判断和施工；原因仍不清楚时可调用 Debug Skill，例如 `$superpowers:systematic-debugging`。第三次正式 D1 FAIL 后停止普通重试，由 Checker 与 Supervisor 重新审视当前 CELL；必要时可调用 `$slk-dispatch-cell` 一分为二或另选路线，但不自动替换 Worker。
5. Worker 完成修改和最低 D0 后，使用 `$slk-execute-cell` 的记录与交付方式重新提交。
6. OCRV Checker 使用 `$slk-check-cell` 针对修复目标、受影响范围和相关回归重新执行 D1，保留未受影响且仍有效的已完成工作与客观证据，不复用通过结论；本轮事实通过 `slk-state` 追加，不覆盖前轮记录，不重复施工未受影响且仍有效的已完成工作。

## 连续未收敛

第三次 D1 FAIL 后先重新规划当前 CELL；调整超出当前 CELL、影响后续 CELL 或 Run 时，Checker 再把完整情况交给 Supervisor。Supervisor 使用 `$slk-adjust-run` 综合考虑继续诊断、形成电脑或环境变更建议、调整路线或暂时豁免。

## 负面提示词

- 不要把 D0 草稿自修或 Checker 自建检查器故障计入 Worker 的 D1 返工次数；不要在初始施工、D1 PASS、D1 INCOMPLETE 或工具故障时创建 `D1_REWORK_DIRECTIVE`，不要把 `Supervisor → Worker` 扩成普通派工，也不要让 Supervisor 重判 D1、直接改代码或替 Worker 施工。
- 不要让 Overwatcher 提出修复假设、执行返工或判定回归；它只观察通讯与运行证据，第三次 D1 FAIL 后的路线仍由 Checker/Supervisor 按既有权威处理。
