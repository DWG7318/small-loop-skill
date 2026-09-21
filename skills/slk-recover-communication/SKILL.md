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

1. 用 `slk-bi-query` 与 `slk-transport inspect` 核对准确 Run/CELL/TOKEN、原 `message_id`、sender/receiver、endpoint version、payload SHA-256 和原生启动证据；旧 running、旧 TOKEN、可见文字或 heartbeat 不证明已启动。
2. 已有匹配 `started.json` 或完成证据时立即停止，不重复激活、不重做工程工作。
3. 只有原投递身份完整且没有 native start 证据时，才可调用 `slk-transport retry-exact`；同一 `message_id`、端点、payload 与 scope 最多一次，结果写入确定性 recovery evidence。
4. 原发送者在匹配 native start 后才用自己的凭证执行 `slk-state handoff`。Overwatcher 若已绑定，可执行检查/原样重试并用 `record-observation` 记录，但不 handoff、不改 TOKEN，也不替发送者写工程事实。
5. 重试耗尽、证据冲突、身份缺失，或需要改接收者、端点、内容、route、CELL/attempt 时，返回 `SUPERVISOR_DECISION_REQUIRED`；可由 Overwatcher 唤醒 Supervisor，也可沿原有直连上报。不要猜 ID 或创建替代角色。
6. 每次操作结束当前 turn；不要使用正时长 `wait_threads`、轮询循环、daemon 或无限 retry。

## 明确失效

任务 ID 不存在、平台明确失败/取消且无法继续，或真实激活返回端点不可用，才调用 `$slk-manage-team` 做 rebound/replacement。暂时没有回复不等于成员失效。

## 负面提示词

- 不要把 exact retry 变成新消息，不要更换 receiver、endpoint、payload、scope 或 token sequence；不要凭发送成功声称已启动，也不要让 Overwatcher 成为必经 relay、推进 TOKEN、修改 BI、判 D1/D2 或接管 Supervisor。
