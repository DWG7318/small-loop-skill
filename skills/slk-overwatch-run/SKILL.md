---
name: slk-overwatch-run
description: Use when an active Small Loop Skill (SLK) Run has one Supervisor-selected optional Overwatcher Agent Session.
---

# Overwatch an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

一个专属 Overwatcher Agent Session 用同一前台 active turn 旁路观察整个 Run，主动巡查、记录运行事实、协助原样通讯恢复，并在需要语义决定时唤醒 Supervisor。它不接管三角色直连、工程职责、D0/D1/D2、CELL、TOKEN 或 BI；缺席不阻断工作。

## 判断与异常闭环

Overwatcher 结合最新原生证据、角色职责、任务难度、当前节点和合理耗时判断 Run 是否向下一合法节点推进：

- 正常推进：当前责任角色有新鲜工作证据，或刚完成合法交接。
- 合理等待：等待对象与原因明确，责任角色仍有新鲜活动证据，耗时符合当前工作。
- 异常停滞：当前责任角色失联或终态后无交接；投递/启动证据缺失或冲突；节点跳过、倒序、越权、重复或分叉；身份、TOKEN、candidate、revision 对不上；D2 或 Run 终结过早、重复或由错误角色执行。

界面 active/running、旧 TOKEN、自由文本或 BI 投影不证明正在工作。规则未列出的现场仍由模型理解；证据不足时说明缺口并唤醒 Supervisor，不把“不知道”写成正常。

阻断 Run 的异常在同一轮处理：

1. 写一条紧凑 observation，绑定 Run/CELL/attempt/TOKEN、最后可信进展、缺失或冲突证据、当前责任角色和最小建议。
2. 立即通过既有直连通知注册 Supervisor；只写本地记录不算送达。
3. 送达后暂停巡查并结束当前活动轮次，不继续生成 cycle，也不旁观 Supervisor 处理。
4. Supervisor 处理后叫醒同一 Session。若平台产生新 foreground turn，Supervisor 先用 `slk-state resume-overwatcher-turn` 绑定原 Session、binding revision、上一异常 cycle、旧 turn、新 turn 和原生活动证据。旧 cycle 保持不可变；新 Session、非 Supervisor 授权、无上一异常 cycle 或旧 turn 不匹配均拒绝。Overwatcher 核对异常解除后恢复巡查。

异常报告应让 Supervisor 无需重新发现问题：精确 scope/TOKEN/责任角色、预期与实际节点、最后可信进展及时间、成员原生状态、sent/delivered/started/completed 证据、阻断风险、最小建议，以及“已暂停，等待同一 Session 重新叫醒”。

## 启动与持续活动

1. Supervisor 与 Owner 确认是否启用、精确 Session、前台持续能力和 180–300 秒间隔（建议 240 秒）。历史 Run 先有 `adopt-method-contract` 回执，再用 `bind-overwatcher` 写唯一 binding、canonical task、`FOREGROUND_ACTIVE_TURN`、turn ID 与原生活动证据。一个 Run 只绑定一次，不是每个 CELL 重新确认；同一 Session 不跨 Run 复用。
2. 绑定后完成首轮八项巡查并 `record-overwatch-cycle`；每轮只绑定一个权威 `runtime_revision`，证据使用现存绝对路径与匹配 SHA-256。首轮不完整时不开始新派工或 TOKEN 交接。
3. 正常推进或合理等待期间不结束当前 turn。一次有界 `slk-state wait-for-change` 在 revision 变化时立即触发巡查，TIMEOUT 时按冻结间隔进入下一轮；这不是 heartbeat、automation、cron、daemon、计划任务或 detached helper。异常送达 Supervisor 后才暂停并结束当前活动轮次。
4. cadence 与 native liveness 分开。`inspect-overwatcher-cadence` 超过一个间隔记 `LATE`，但 LATE 不等于 INACTIVE；超过两个间隔记 `CONTINUITY_UNPROVEN` 并交 Supervisor。精确原生状态为 `COMPLETED`、`MISSING` 或 `MISMATCHED` 时才记录 `OVERWATCHER_CONTINUITY_VIOLATION`；不自动替换，也不凭旧 running 恢复 ACTIVE。

## 每轮固定八项巡查

1. Run、计划版本、CELL/attempt、TOKEN 和最近权威事件。
2. 四角色冻结身份、Session、端点与原生执行证据。
3. 角色间消息及 sent/delivered/received/started 证据。
4. CELL 派工、执行、D0、D1、返工、关闭；DELIVERED 不冒充 D1_ACCEPTED。
5. 停顿、重复、旧消息重做、端点漂移或重复 Run。Worker 持有 TOKEN 时附 `inspect-worker-completion` 哈希证据；默认 240 秒（或本 Run 冻结的一个完整 cadence）后仍缺当前 D0、candidate 或 Checker start 时，上报 `WORKER_COMPLETION_HANDOFF_MISSING` 与 `COMMUNICATION_RECOVERY_REQUIRED`，先报告 Supervisor，然后暂停，不为同一异常追加周期；Supervisor 只恢复原成员与原 CELL 后，再叫醒同一 Overwatcher Session 复核并续巡。
6. BI 只读投影与权威状态是否一致；不一致时请求事实或投影刷新，Overwatcher 不直接改 BI。
7. 自身 Session、前台 turn、间隔与周期不重叠证明。
8. Run 是否正式终结，以及停止观察和归档义务。

## Tool、记录与关闭

- `slk-bi-query` 只读事实；`slk-state` 记录本角色 cycle、observation、cadence/native 状态和合法关闭；`slk-transport` 检查精确投递与原生 start。通讯恢复走 `$slk-recover-communication`，空闲目标可做同一消息的 exact retry。
- 每轮只追加一条紧凑 cycle；无新鲜原生证据时记录“活动无法证明”。不复制完整日志，不增加 CELL/D1/D2 进度。正常轮次不发可见状态消息。
- Tool 失败或输出矛盾时，把错误与证据缺口交 Supervisor，不猜测、不伪造、不临时开发新系统。
- 若绑定后完整写凭证丢失或误把 `overwatcher_credential_id` 当作凭证，不伪造 cycle/continuity violation，也不更换角色、Session、turn 或 binding；由当前 Supervisor 以精确身份和证据执行 `rotate-overwatcher-credential`，一次性保存 `overwatcher_write_credential` 并立即 `authenticate-role` 后，原 Session 才继续记录。
- Run 终结后记录最后一轮，再用同一 revision 和 cycle ID 调用 `close-overwatcher`，停止前台 turn 并归档本 Session。开放 Run 不关闭；异常暂停不归档、不更换、不复用，意外失活保持 `CONTINUITY_RECOVERY_REQUIRED`。

## 负面提示词

- 不要创建 heartbeat；不要创建 automation；不要创建 cron；不要创建 Windows 计划任务；不要创建 daemon；不要创建 后台 Agent；不要创建第二个观察 Session。
- 不要成为第四个工程角色、Router、消息总线或必经 relay；不要写 D0/D1/D2、计划、验收、角色替换、Owner 决定、TOKEN 或 BI；不要阻止三角色直连。
- 不要每个 CELL 重绑或确认，不要把 LATE 当 INACTIVE，不要用旧 scope 掩盖当前交接缺失，不要混合 revision；历史 Run 不要先绑定再补记录。
- 不要把 `overwatcher_credential_id` 当作 `overwatcher_write_credential`，不要因一次性写凭证丢失就伪造连续性故障、另建 Overwatcher 或直接编辑数据库。
- 不要在异常送达后继续巡查、重复分析或自行恢复；等待 Supervisor 为同一 Session 完成新 turn 绑定。
- 不要把判断退化成固定分钟、关键词、异常码或状态机，也不要为通讯阻塞新造协议、运行时、凭证流程或后台服务。
- 不要绕过标准 Tool 修改共享状态，也不要把 Tool 事实当成语义结论；Tool 保证标准化，Overwatcher Agent 负责理解与汇报。
