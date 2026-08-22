---
name: slk-dispatch-cell
description: Use when an SLK Checker is ready to hand one planned CELL to the Worker.
---

# Dispatch a CELL

## 当前目标

由 Checker 把当前 CELL 交给 Worker，让 Worker 能直接施工，也让之后的 D1 保持同一个验收目标。

## 建议交付内容

- `CELL n/N` 与所属 GO；
- 本 CELL 要实现的目标和可观察结果；
- 本次施工范围，以及暂时留在后续 CELL 的内容；
- Worker 需要的相关上下文、入口、候选基线和已有证据；
- 建议的最低 D0；
- Checker 将使用的 D1 验收目标；
- 已知风险、资源假设和需要保留的工程余量。

## 交付方式

Checker 可以用一条结构清楚的消息发送完整 CELL，确认内容已经出现在 Worker 对话并观察其活动状态。这里传递施工目标，不把 Checker 的 D1 判断提前交给 Worker。

Worker 提出合理澄清时，Checker可以补充上下文；若答案会改变 Run 目标或验收目标，建议请 Supervisor 协助判断。

## 完成后

Worker 使用 `$slk-execute-cell` 开始施工。Checker 保留当前 CELL 和 D1 目标，等待候选交付。
