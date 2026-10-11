---
name: slk-dispatch-cell
description: Use when an active Small Loop Skill (SLK) Run has a Checker ready to hand one planned CELL to the Worker.
---

# Dispatch a CELL

仅用于已选择 `$small-loop-skill` 的当前 Run。Checker 校准既定 CELL，再将完整任务直接交给已登记 Worker；不代替 Supervisor 规划，也不预给 D1 判断。

## 校准并准备任务

- 对照冻结计划、前序施工/D0/D1、返工和真实依赖，确认当前 CELL 的位置、范围和验收目标仍合适。模型、电脑、累积工程量和余量是情境事实，不另设容量检查或统一定额。
- 范围仍过大或变化影响 Run/验收目标时，退回 Supervisor 用 `$slk-adjust-run` 调整为可独立 D0/D1 的中小 CELL；不逐条命令派工。
- 任务说明 `CELL n/N`、目标及可观察结果、当前/后续范围、上下文与候选基线、相关证据、最低 D0、D1 目标和已知风险。Worker 澄清不改变目标时可补上下文，改变目标则交 Supervisor。
- Git common-dir 在 Worker 沙箱外时停止派发；Supervisor 可在施工前另备独立可写 clone/simple layout，不静默搬移原 linked worktree。

## 最后动作：精确交接

初始链为 Supervisor → Checker → Worker；Supervisor 的 `CELL_DISPATCH` payload 固定且仅含 `{worker_endpoint, worker_payload}`。前者是当前登记端点，后者是冻结任务，不把 Worker 内容放在顶层。D1 PASS 后由原 Checker 的标准 `--slk-complete-d1` 后缀交当前版本计划中的精确下一 Required CELL；末项交 `D2_READY`，不绕过 Required CELL。

交接前保存本人的校准事实和必要证据。完整任务一次发送，不拆命令；不可变 task file 与 payload SHA-256 绑定。同一封闭信封保留 `SLK TOKEN Tnnn`、单调编号、Run/CELL、`n/N`、当前位置、接收者、下一动作和根记录路径；当前角色、endpoint version、attempt 和哈希必须吻合。

Worker 原生进程建立后、任何终态前须有匹配的 `slk.native-start/v2`（`started.json`）。标准入口仅在所属可信 Tool 内消费密封 Checker 凭据，以 `commit-delivery-start` 同一事务绑定启动、推进 TOKEN、追加事件并生成唯一 `runtime_revision`。受理、后台文字、成功退出、终态或数据库状态都不能反推启动，不能分步 handoff 或混用 revision。

这次交接是 Checker 本次激活的最后任务动作：核实原子提交结果后结束，不加令牌回执、不用正时长 `wait_threads`、不读取 Worker 施工状态，也不留 post-turn/background 脚本。Worker 按 `$slk-execute-cell` 施工；候选交付重新激活 Checker 后，才用 `$slk-check-cell` 做 D1。接收任务不是完工。

## 不能正常派发时

明确未启动、投递失败或端点不可用时保留当前 TOKEN 和原消息，按 `$slk-recover-communication` 处理已有精确投递；不把排障插进每次正常交接。OW 只观察并报告 Supervisor，不代发、重试或提交 TOKEN；runtime guard 只阻断下一 CELL，不扣留已有报告或停止当前 CELL。REQUESTED/PAUSED 不开新派工，只沿原暂停边界闭合精确在途动作。
