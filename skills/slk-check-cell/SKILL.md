---
name: slk-check-cell
description: Use when an active Small Loop Skill (SLK) Run has a Checker ready to perform D1 on a Worker candidate.
---

# Check a CELL at D1

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

Checker 在与 Worker 隔离的对话中，对当前候选执行 D1，并给出可行动的结果。

## 隔离与输入

Checker 先读取原始 CELL 与 D1 目标、候选身份和客观工程事实。在形成独立 D1 判断前，延后读取 Worker 分区中的 D0 结果、判断过程和建议关注点。Checker 根据风险选择检查，并在适合时使用干净或独立的验证环境。

## 建议检查

1. 确认候选对应当前 `CELL n/N`，验收目标仍是规划时的目标。
2. 检查目标结果、相关回归、明显副作用和候选中客观可观察的风险。
3. 根据变化大小选择足够的命令和证据，先形成独立 D1 判断。
4. 随后读取 Worker 的 D0 与施工记录，核对是否出现新的客观事实或遗漏风险；D0 结论不替代 Checker 的独立证据。
5. 由 Checker 给出 D1 结论：
   - `D1 PASS：CELL n/N`
   - `D1 FAIL：CELL n/N，进入返工`
6. D1 FAIL 时说明具体差距、复现方式和期望结果，让 Worker 能针对性修复。
7. 在执行 D1 的同时，顺手记录本 CELL 的容量事实，例如工作量是否合适、是否接近当前能力或是否因过大带来返工；这复用已有事实，不增加额外检查。
8. 把本次 D1、错误、返工或容量事实写入根记录，建议调用 `$slk-record-run`，随后再把结论传给下一成员。

## 后继

- D1 PASS 后，Checker 更新进度；还有 CELL 时使用 `$slk-dispatch-cell` 校准并派发下一个既定 CELL。所有计划 CELL 都已经获得 D1 PASS 或单独记录的 Supervisor 豁免时，Checker 向 Supervisor 汇报 Run 已具备 D2 条件。
- D1 FAIL 后，Checker 使用 `$slk-rework-cell` 与 Worker 继续直接协作。
- 需要改变 Run 方案时，请 Supervisor 使用 `$slk-adjust-run` 协助判断。
