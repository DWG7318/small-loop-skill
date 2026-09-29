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
2. 已有匹配 `started.json` 时立即停止，不重复激活，并由原发送者完成幂等 `commit-delivery-start`；只有终态完成而缺少对应 start 时直接拒绝，不能反向补造。若终态属于 DSH Worker 且仍缺 `WORK_STARTED`、D0、绑定当前 candidate/source message 的 `CANDIDATE_SUBMITTED` 或唯一 Worker→Checker start，则用 `inspect-worker-completion` 按 run+cell+attempt+candidate/message 精确检查；旧 attempt、其他 candidate/message 的 D1 不构成当前交接。一个完整巡查间隔后仍卡住时，Supervisor 只把闭合 `WORKER_COMPLETION_RECOVERY` 投递给原注册 OCRV Checker；该原生 Checker 先认证精确 role/endpoint/revision，再恢复原 DSH Session，让 Worker 只补交接后缀。OCRV 长审查由独立 headless Checker 传输宿主或当前持续 Supervisor 宿主管理，不由一次性 DSH 进程托管。
3. 原目标空闲、原投递身份完整且没有 native start 时，才可调用 `slk-transport retry-exact`；同一 `message_id`、端点、payload 与 scope 最多一次，结果写入确定性 recovery evidence。
4. 目标是已登记的 Codex Supervisor、外部 App Server 已因 Desktop active writer 耗尽原样重试时，保留原失败消息并使用两阶段 Desktop current-turn bridge：当前 Codex Desktop 宿主先 `prepare-desktop-current-turn`，再读取准确目标 thread 的当前 active turn、发送准备阶段生成的原样 `prompt`，并回读同一 turn；只有平台回读出现新的 `functionCallOutput/codex_app/send_message_to_thread` 且消息哈希完全匹配，才以闭合 host receipt 执行 `complete-desktop-current-turn`，在独立 recovery 目录写新 `started.json`。可见消息、发送成功或自报收据都不证明启动；缺少同 turn 平台回读时继续 `CODEX_ACTIVE_WRITER_UNRESOLVED`，不移动 TOKEN、不改写原失败/重试证据。PowerShell 用 `python <slk-transport.pyz>` 调用；不要用 `& <slk-transport.pyz>`。`--attempt-root` 是 attempts 根目录，不是 `<run_id>/<message_id>`。不要先 resume；不匹配 thread/turn/host/identity 时返回 `SUPERVISOR_DECISION_REQUIRED`，不猜 ID、不创建替代角色，并如实等待 Owner/Main 真实激活。
5. 原发送者在匹配 native start 后用自己的凭证执行 `slk-state commit-delivery-start`。Overwatcher 若已绑定，可检查、触发允许的恢复并用 `record-observation` 记录，但不 handoff、不提交 TOKEN，也不替发送者写工程事实。
6. Run 已显式启用 4.3.0 Temporal 时，`RunSlkWorkflow` 只记录同一 operation 的投递、超时与匹配 `native-start ACK`；超时后有 Overwatcher 就请求其按本 Skill 恢复，否则请求原发送者恢复。delivery success、工具终态或 recovery activity 成功都不是 ACK；匹配 ACK 后立即停止后续恢复。
7. 重试耗尽、证据冲突、身份缺失，或需要改接收者、端点、内容、route、CELL/attempt 时，返回 `SUPERVISOR_DECISION_REQUIRED`；可由 Overwatcher 唤醒 Supervisor，也可沿原有直连上报。不要猜 ID、自动升级模型、启用 BoM 或创建替代角色。
8. 每次操作结束当前 turn；只允许同一进程内有界的 `wait-for-change` 读取状态变化，不要使用正时长 `wait_threads`、外部轮询循环、daemon 或无限 retry。

## 明确失效

任务 ID 不存在、平台明确失败/取消且无法继续，或真实激活返回端点不可用，才调用 `$slk-manage-team` 做 rebound/replacement。暂时没有回复不等于成员失效。

## 负面提示词

- 不要把 inactive-target exact retry 变成新消息，也不要在 active writer 已存在时先 `thread/resume`、继续争夺外部 writer 或把 steer 伪装成旧消息重放；不要用 `& <slk-transport.pyz>`、post-turn 延迟脚本、后台自唤醒、sleep 或“15 秒后自动”一类固定秒数承诺替代真实激活；不要把可见消息、自报文本或发送成功当作平台回读，不要手改 endpoint JSON、更换 receiver/endpoint/payload/scope/token sequence，或凭终态结果/Temporal activity 声称已启动；不要由 Supervisor、Overwatcher 或普通 shell 直接调用已移除的 `resume-worker-continuation`，不要从一次性 DSH 进程托管 OCRV 长审查，也不要在 Checker 认证成功前把 native start 写成 authorized；不要由其他角色使用 Worker 凭据或补写 Worker 事实，不要自动升级模型或引入 BoM route，也不要让 Temporal 或 Overwatcher 成为必经 relay、推进 TOKEN、修改 BI、判 D1/D2 或接管 Supervisor。
