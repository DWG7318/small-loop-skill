---
name: slk-recover-communication
description: Use when an active Small Loop Skill (SLK) Run has an exact delivery without matching native start evidence.
---

# Recover SLK Communication

仅用于已选择 `$small-loop-skill` 的当前 Run 的已有精确投递异常。正常链不经排障，无消息不套恢复；只续原交付/缺失后缀，不重跑工程、审报告或换身份。

## 核对原件

1. 原发送者用 `slk-transport inspect`、`inspect-native-activity` 和只读状态核对 Run/CELL/工程 attempt/message_id、角色/endpoint version、payload 与 native-request SHA-256、TOKEN/operation。缺失、过期、歧义或冲突保持 UNKNOWN；保存、accepted、可见文字、旧 PID、终态或 TOKEN 都不证明启动。
2. 已有匹配 `slk.native-start/v2`（`started.json`）时，只读复用同一 message/candidate/attempt，不再发送/激活。旧 Host 回执或暂存交接先核原端点/信封/真实启动；不足报未确认，不换 ID 掩盖。仅缺 ACK/commit 时，用原请求/已存 ACK 和既有 `continue-staged-handoff` 续缺失后缀，保留 operation/唯一 `runtime_revision`，不重复工程动作。
3. 仅在**证明原投递无启动且目标空闲**时 `retry-exact` 原样一次；message_id、端点/version、Run/CELL/attempt、TOKEN、scope、payload 不变，不换模型/Session/接收者。保留原失败与 `recovery/exact-1`；受理不明不盲重发，已有启动不再试。

## 按实际异常选入口

- Codex 已受理但缺平台回读：仅对原 attempt 用 `consume-desktop-readback --source-attempt <准确原attempt目录>`，不再发送。原 Temporal 通知目录的 `notification.json` 也走其已有消费分支，不强套 Checker-only `prepare-desktop-current-turn`；每条原通知只补原回执，重复调用复用结果，既有 proof 不改，新检查引用新回读事实。
- 普通发送和一次 exact retry 都因 active Desktop writer 未解析而失败，且明确返回 `DESKTOP_BRIDGE_REQUIRED`：Desktop 宿主用既有 prepare/complete 原样投递并留真实 host receipt。原 operation 与实际新消息各保身份，不重写旧信封、不争 active writer 或在其前 resume。
- PowerShell 用 `python <slk-transport.pyz>` 而非 `& <slk-transport.pyz>`；`--attempt-root` 是 attempts 根，不是 `<run_id>/<message_id>`。
- 明确工程行动仍由原责任角色提交；Supervisor 仅在原登记 Session 用 `submit-supervisor-decision`，不等整个 turn 终结。密封凭据只由所属可信入口消费，不借他人权限或编辑 SQLite。

## 不能闭合就升级

重试耗尽、冲突或端点失效交登记 Supervisor，说明已保存内容、投递事实和未完成动作。Supervisor 按 `$slk-troubleshoot-run` 承担现场补漏，不无限等待源码维修；`SUPERVISOR_DECISION_REQUIRED` 由其据实处理，不靠换 ID 绕开。无活动接收者由 Owner/Main 真实激活，不猜接管。更换/恢复成员或旋转凭据用 `$slk-replace-member`，新端点不等于原消息已送达。Temporal 故障按原 operation 用 `$slk-manage-temporal`，不另造身份/工作流。

报告原样保存/独立投递，不等 ACK/TOKEN/Temporal；维护失败另记，正文/格式/退出码不补造 D0/D1/D2、启动、接手或 TOKEN。旧格式/pre-D0/partial/context/terminal 自动消费退役，历史 FAIL/原件只读，不为模板重跑 Agent。

恢复交接是本次最后工程动作；Worker/Checker 闭合后结束本次激活。Supervisor 完成现场补漏后仍 active，以有界原生等待接收结果/OW 报告；不用忙轮询、无限 retry、daemon、自唤醒或 post-turn/background 脚本。REQUESTED/PAUSED 不开新工程，仅按原暂停边界闭合精确在途输出/ACK/commit-only。OW 只观察/报告 Supervisor，不 relay、exact retry、写 BI/工程事实或 TOKEN；runtime guard 只阻断下一 CELL，不停当前 CELL、不自动暂停 Run 或扣报告。
