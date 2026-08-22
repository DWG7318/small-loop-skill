---
name: slk-check-cell
description: Use when the SLK Checker has received a Worker candidate and needs to perform the CELL-level D1 review.
---

# Check a CELL at D1

## 当前目标

Checker 在与 Worker 隔离的对话中，对当前候选执行 D1，并给出可行动的结果。

## 隔离与输入

Checker 读取 CELL 验收目标、候选、Worker 交付和相关工程事实。Worker 的 D0 是输入；Checker 根据风险选择独立检查，并在适合时使用干净或独立的验证环境。

## 建议检查

1. 确认候选对应当前 `CELL n/N`，验收目标仍是规划时的目标。
2. 检查目标结果、相关回归、明显副作用和 Worker 已说明的风险。
3. 根据变化大小选择足够的命令和证据，减少与 D0 重复的低价值检查。
4. 由 Checker 给出 D1 结论：
   - `D1 PASS：CELL n/N`
   - `D1 FAIL：CELL n/N，进入返工`
5. D1 FAIL 时说明具体差距、复现方式和期望结果，让 Worker 能针对性修复。
6. 把本次 D1、错误或返工信息写入根记录，建议调用 `$slk-record-run`，随后再把结论传给下一成员。

## 后继

- D1 PASS 后，Checker 更新进度；还有 CELL 时进入 `$slk-plan-cell`，全部完成时向 Supervisor 汇报 Run 已具备 D2 条件。
- D1 FAIL 后，Checker 使用 `$slk-rework-cell` 与 Worker 继续直接协作。
- 需要改变 Run 方案时，请 Supervisor 使用 `$slk-adjust-run` 协助判断。

