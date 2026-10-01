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

1. 用 `slk-bi-query`、`slk-transport inspect` 与 `inspect-native-activity` 核对准确 Run/CELL/TOKEN、原 `message_id`、sender/receiver、endpoint version、payload SHA-256 与 native-request SHA-256、`started.json` v2、当前原生任务和 runtime revision；缺失、过期、身份不符、查询错误或权限不足均为 `UNKNOWN`，旧 running/TOKEN/Session/PID、可见文字、终态或 heartbeat 不证明当前活动。
2. 已有匹配 `slk.native-start/v2` 时不重复激活。普通路径由原发送者幂等提交；若历史假启动已把 TOKEN 置于 Checker，则复用同一 candidate/message/attempt，在独立 `.native-recovery-v2` 由外部 OCRV 宿主建立真实 D1，不恢复 Worker、不重放候选、不移动/回滚 TOKEN、不改旧证据。旧结果描述器导致匹配 v2 start 的完成候选以 `DSH_RESULT_INVALID` 终止时，`INVALID_RESULT_CONTRACT` 由标准工具先 `prepare-invalid-result-recovery`，再交原 Checker 内部使用密封凭证唤醒原 Worker Session 一次，只补交平铺结果后复用既有认证恢复并进入真实 OCRV D1；Root 只准备/投递闭合信封，不直接恢复或转换嵌套结果，不代写 Worker/Checker 事实。多段 OCRV 逐段发布 start/activity，检查当前段而不是第一段已退出 PID；wrapper start 不是 D1。标准工具用密封 Checker 凭证记录实际终态与 result/aggregate 哈希，OCRV 长审查不由一次性 DSH 进程托管。
3. 原目标空闲、原投递身份完整且没有 native start 时，才可调用 `slk-transport retry-exact`；同一 `message_id`、端点、payload 与 scope 最多一次，结果写入确定性 recovery evidence。
4. 目标是已登记的 Codex Supervisor、外部 App Server 已因 Desktop active writer 耗尽原样重试时，保留原失败消息并使用两阶段 Desktop current-turn bridge：当前 Codex Desktop 宿主先 `prepare-desktop-current-turn`，再读取准确目标 thread 的当前 active turn、发送准备阶段生成的原样 `prompt`，并回读同一 turn；只有平台回读出现新的 `functionCallOutput/codex_app/send_message_to_thread` 且消息哈希完全匹配，才以闭合 host receipt 执行 `complete-desktop-current-turn`，在独立 recovery 目录写新 `started.json`。可见消息、发送成功或自报收据都不证明启动；缺少同 turn 平台回读时继续 `CODEX_ACTIVE_WRITER_UNRESOLVED`，不移动 TOKEN、不改写原失败/重试证据。PowerShell 用 `python <slk-transport.pyz>` 调用；不要用 `& <slk-transport.pyz>`。`--attempt-root` 是 attempts 根目录，不是 `<run_id>/<message_id>`。不要先 resume；不匹配 thread/turn/host/identity 时返回 `SUPERVISOR_DECISION_REQUIRED`，不猜 ID、不创建替代角色，并如实等待 Owner/Main 真实激活。
5. 普通 handoff 由原发送者在匹配 v2 start 后用自己的密封凭证提交；TOKEN 已在 Checker 的恢复明确跳过提交，标准工具仅在内部使用 Checker 凭证写实际 D1。Supervisor/Overwatcher/普通 shell 不接触任一角色凭证；Overwatcher 只检查、触发允许的恢复并记录观察，不 handoff。
6. Run 已显式启用 4.3.0 Temporal 时，`RunSlkWorkflow` 只记录同一 operation 的投递、超时与匹配 `native-start ACK`；超时后有 Overwatcher 就请求其按本 Skill 恢复，否则请求原发送者恢复。delivery success、工具终态或 recovery activity 成功都不是 ACK；匹配 ACK 后立即停止后续恢复。
7. 重试耗尽、证据冲突、身份缺失，或需要改接收者、端点、内容、route、CELL/attempt 时，返回 `SUPERVISOR_DECISION_REQUIRED`；可由 Overwatcher 唤醒 Supervisor，也可沿原有直连上报。不要猜 ID、自动升级模型、启用 BoM 或创建替代角色。
8. 每次操作结束当前 turn；只允许同一进程内有界的 `wait-for-change` 读取状态变化，不要使用正时长 `wait_threads`、外部轮询循环、daemon 或无限 retry。

## 明确失效

任务 ID 不存在、平台明确失败/取消且无法继续，或真实激活返回端点不可用，才调用 `$slk-manage-team` 做 rebound/replacement。暂时没有回复不等于成员失效。

## 负面提示词

- 不要把 inactive-target exact retry 变成新消息，也不要在 active writer 已存在时先 `thread/resume`、继续争夺外部 writer或把 steer 伪装成旧消息重放；不要用 `& <slk-transport.pyz>`、post-turn 延迟脚本、后台自唤醒、sleep、“15 秒后自动”或固定秒数承诺替代真实激活；不要把 legacy start、旧 Session/PID、wrapper ACK、第一 segment PID、可见消息、自报文本、发送成功、终态或 Temporal activity 当作当前 D1 活动；4.3.4 平铺 start 只允许标准工具在 TOKEN 已属 Checker、Worker 已完成且 task/hash/endpoint/envelope/原 Session/终态/candidate/中央交接链全部吻合的窄恢复分支读取，不能冒充本次要求匹配 v2 start 的旧结果描述器补交，不要放宽普通 v2 或活动标准，不要手改 endpoint/receiver/payload/scope/TOKEN 或覆盖旧证据；不要由 Root、Supervisor、Overwatcher 或普通 shell 解封凭证、直接恢复 Worker、转换嵌套结果、代写 Worker/Checker 事实，也不要让一次性 DSH 进程托管 OCRV 长审查；不要自动升级模型、引入 BoM route，或让 Temporal/Overwatcher 成为必经 relay、推进 TOKEN、修改 BI、判 D1/D2 或接管 Supervisor。
