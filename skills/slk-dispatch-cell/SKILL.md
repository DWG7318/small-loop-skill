---
name: slk-dispatch-cell
description: Use when an active Small Loop Skill (SLK) Run has a Checker ready to hand one planned CELL to the Worker.
---

# Dispatch a CELL

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

由 Checker 对计划中的既定 CELL 做一次派发前现实校准，再通过 `Checker → Worker` 把当前 `SLK TOKEN` 交给 Worker，让 Worker 能直接施工，也让之后的 D1 保持同一个验收目标。

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

Checker 先用 `slk-state write` 记录 `CELL_DISPATCHED`，再按 Worker 精确端点调用 `slk-transport send` 一次发送完整 CELL，不把一个 CELL 拆成逐条命令派发；同一封闭信封写入 `SLK TOKEN Tnnn`、令牌编号、Run、CELL、当前节点、接收者、候选（如有）、下一动作和根记录路径，编号单调递增。文字只出现在数据库或后台不构成投递；出现真实激活的原生启动证据后才用 `slk-state handoff` 原子推进。Worker 直接开始 CELL，不增加令牌专用回执；Checker 发出完整 CELL 后结束本次激活，不使用`wait_threads`也不读取Worker施工状态，候选交付重新激活Checker。

`slk-transport` 明确报告未启动、投递失败或 Worker 端点不可用时，Checker 用 `slk-state write` 记录 `TRANSPORT_FAILED`，保留当前令牌与责任，沿用同一消息、信封、端点版本和拟发送编号重试；任务不可用时可使用 `$slk-manage-team` 优先恢复原 Worker，缺少回复本身不表示需要更换 Worker。

Worker 提出合理澄清时，Checker可以补充上下文；若答案会改变 Run 目标或验收目标，建议请 Supervisor 协助判断。

## 完成后

Worker 使用 `$slk-execute-cell` 开始并继续施工。Checker 保留当前 CELL 和 D1 目标，派发消息发出后结束本次激活；候选令牌重新激活Checker后才开始 D1。

## 负面提示词

- 不要为令牌增加接收回执或轮询，把一个 CELL 拆成逐条命令派发，或把接收令牌当成候选交付；接收令牌不是 CELL 完工。不要提前把 D1 判断给 Worker，也不要在派工后等待或读取 Worker 内部施工过程。
