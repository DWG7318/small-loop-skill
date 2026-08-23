---
name: slk-dispatch-cell
description: Use when an active Small Loop Skill (SLK) Run has a Checker ready to hand one planned CELL to the Worker.
---

# Dispatch a CELL

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

由 Checker 对计划中的既定 CELL 做一次派发前现实校准，再把它交给 Worker，让 Worker 能直接施工，也让之后的 D1 保持同一个验收目标。

## 派发前校准

- 对照当前 GO、前序 CELL 的实际施工、D0/D1、返工表现和真实依赖，动态校准既定 CELL 是否仍处在正确位置；
- 参考 Worker 当前模型、电脑、累积工程量和施工余量，判断范围是否仍然合适；
- 原验收目标不变而范围明显过大时，可以做一次简单的局部拆分：把 CELL 一分为二，形成两个串行 CELL，并同步 `CELL n/N` 与根 Run 记录；
- 变化会影响 Run、GO 或验收目标时，建议请 Supervisor 使用 `$slk-adjust-run` 组织调整。

这些判断复用已经产生的施工与检验事实，不另设容量检查。

## 建议交付内容

- `CELL n/N` 与所属 GO；
- 本 CELL 要实现的目标和可观察结果；
- 本次施工范围，以及暂时留在后续 CELL 的内容；
- Worker 需要的相关上下文、入口、候选基线和已有证据；
- 建议的最低 D0；
- Checker 将使用的 D1 验收目标；
- 已知风险、资源假设和需要保留的工程余量。

## 交付方式

Checker 使用能够继续 Worker 对话的真实激活操作发送完整 CELL。Worker 对当前 CELL 的明确回执说明交付已接收；回执只确认交付已接收，不结束 Worker 当前 CELL 的施工。文字只出现在后台记录中不构成接收证据。Checker 收到回执后结束当前活动，不使用`wait_threads`也不读取Worker施工状态，随后由候选交付重新激活Checker。这里传递施工目标，不把 Checker 的 D1 判断提前交给 Worker。

真实激活操作明确报告 Worker 任务不可用时，Checker 可以使用 `$slk-manage-team` 优先恢复原 Worker；缺少回复本身不表示需要更换 Worker。

Worker 提出合理澄清时，Checker可以补充上下文；若答案会改变 Run 目标或验收目标，建议请 Supervisor 协助判断。

## 完成后

Worker 使用 `$slk-execute-cell` 开始并继续施工。Checker 保留当前 CELL 和 D1 目标，收到明确回执后结束该次激活；候选交付重新激活Checker后才开始 D1。
