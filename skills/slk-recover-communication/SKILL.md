---
name: slk-recover-communication
description: Use when an active Small Loop Skill (SLK) Run has an exact delivery without matching native start evidence.
---

# Recover SLK Communication

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

用不可变投递证据判断“已经启动”“未确认”或“需要 Supervisor 决策”，在不改变工程语义的前提下最多原样重试一次。没有 Overwatcher 时，原发送者仍按同一规则恢复，Run 不因此停止。

## 恢复顺序

1. 用 `slk-bi-query` 与 `slk-transport inspect` 核对准确 Run/CELL/TOKEN、原 `message_id`、sender/receiver、endpoint version、payload SHA-256、task-file SHA-256、`started.json` 和 runtime revision；旧 running、旧 TOKEN、可见文字、终态结果或 heartbeat 不证明已启动。
2. 已有匹配 `started.json` 时立即停止，不重复激活，并由原发送者完成幂等 `commit-delivery-start`；只有终态完成而缺少对应 start 时直接拒绝，不能反向补造。若终态属于 DSH Worker 且仍缺 `WORK_STARTED`、`D0_COMPLETED`、`CANDIDATE_SUBMITTED` 或 Worker→Checker start，则先用 `inspect-worker-completion`；一个完整巡查间隔后仍卡住时，Supervisor 仅可把闭合 `WORKER_COMPLETION_RECOVERY` 投递给原注册 OCRV Checker。该原生 Checker invocation 先用自己的凭据证明精确 role、endpoint version 与 current runtime revision，才可通过内部 `checker-recover-worker` 恢复原 instance/session；随后由原 Worker 子进程安全注入其 DPAPI 凭据并完成同一后半段。
3. 原目标空闲、原投递身份完整且没有 native start 时，才可调用 `slk-transport retry-exact`；同一 `message_id`、端点、payload 与 scope 最多一次，结果写入确定性 recovery evidence。
4. 若唯一问题是 Codex Supervisor 正在写入且载荷为当前 `D1_FAILURE_ESCALATION`，不要重放旧信封；调用 `slk-transport recover-active-writer` 创建新的 `message_id`，绑定读取到的准确 active turn 并写不可变恢复回执。其他载荷或不匹配 turn 返回 `SUPERVISOR_DECISION_REQUIRED`。
5. 原发送者在匹配 native start 后用自己的凭证执行 `slk-state commit-delivery-start`。Overwatcher 若已绑定，可检查、触发允许的恢复并用 `record-observation` 记录，但不 handoff、不提交 TOKEN，也不替发送者写工程事实。
6. 重试耗尽、证据冲突、身份缺失，或需要改接收者、端点、内容、route、CELL/attempt 时，返回 `SUPERVISOR_DECISION_REQUIRED`；可由 Overwatcher 唤醒 Supervisor，也可沿原有直连上报。不要猜 ID、自动升级模型、启用 BoM 或创建替代角色。
7. 每次操作结束当前 turn；只允许同一进程内有界的 `wait-for-change` 读取状态变化，不要使用正时长 `wait_threads`、外部轮询循环、daemon 或无限 retry。

## 明确失效

任务 ID 不存在、平台明确失败/取消且无法继续，或真实激活返回端点不可用，才调用 `$slk-manage-team` 做 rebound/replacement。暂时没有回复不等于成员失效。

## 负面提示词

- 不要把 inactive-target exact retry 变成新消息，也不要把 active-writer steer 伪装成旧消息重放；不要更换 receiver、endpoint、payload、scope 或 token sequence，不要凭发送成功/终态结果声称已启动；不要由 Supervisor、Overwatcher 或普通 shell 直接调用已移除的 `resume-worker-continuation`，也不要在 Checker 认证成功前把 native start 写成 authorized；不要由其他角色使用 Worker 凭据或补写 Worker 事实，不要自动升级模型或引入 BoM route，也不要让 Overwatcher 成为必经 relay、推进 TOKEN、修改 BI、判 D1/D2 或接管 Supervisor。
