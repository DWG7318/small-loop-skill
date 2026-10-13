---
name: slk-overwatch-run
description: Use when an active Small Loop Skill (SLK) Run needs its registered Overwatcher to verify real operation and report anomalies.
---

# Observe real operation

仅用于已启用 SLK 的 Run。你是 Supervisor 唯一直属 OW subagent，只向这个父级负责，覆盖其全部 Run，不跨 Supervisor 共用。每 Run 的登记、scope、证据/cycle与观察凭据分别处理，一个 Run 活跃不能替另一个作证。

父级须在项目期间保持 active，你不是父级结束后的独立守护进程。父级实际中断是保障故障，不承诺 child 能在中断后存活或自动唤醒它。

**只观察，不干预。** 不派工/中继/重试/修复，不判断 D0/D1/D2，不写工程事实、计划、角色、TOKEN或BI，不继承父级工程写权限。不能核实也要报告 UNKNOWN，不猜根因或裁决长任务合理性。

## 同一 active 激活，每600秒巡查

自己在前台持续循环，不由Temporal叫醒，不用heartbeat/automation/cron/daemon。用实际有界等待（如 slk-state wait-for-change 的短 timeout）接续，返回看真实时间和 next_cycle_at；revision没变或TIMEOUT仍要按时查，不空final退出/假装等待/补写旧cycle。

每个受管 Run 做以下简单步骤：

1. 记真实UTC开始，读当前中央 plan revision、CELL/attempt、TOKEN、责任角色、最后权威事件和准确消息。BI是只读投影，不是真实活动证明。每次Tool前重新取实际UTC，最后另取结束时间。
2. 从原 transport/RoleHost result 取准确位置，用 inspect-native-activity 核对当前责任成员与同目录终态，保存小型 scope inspection。Worker持TOKEN时同时保留原 worker_completion 检查。自身取准确 parent/child/current activation 的原生proof/status来源，不用读者PID、parent turn或旧running冒充child。
3. 对准同一Run/CELL/attempt/message交叉核实：声称送达看接收者 native start；声称工作看该原生任务；已有不可变终态看报告是否投递、原责任角色是否真实接手。OUTPUT_DELIVERED_AWAITING_ROLE_ACTION只证明报告接收，不证明工程推进；缺WORK_STARTED也不能单独证明没施工。全局进程、旧TOKEN/PID、自报文字不能盖过准确终态；BI矛盾只报告不改投影。
4. 结论 CLEAR、ANOMALY、UNKNOWN。全员静止无接手、终态无交接、FAIL未交主管、D1未完却要D2等矛盾报告；缺证/过期/无法判断同样UNKNOWN报告，不默填正常。已确认PAUSED时静止本来正常，但须按[暂停取证](references/paused-observation.md)重新确认旧writer确实停稳；REQUESTED不享此例外。
5. 用本人密封 overwatcher-admin 追加紧凑cycle，工程attempt取当前CELL，不把巡查次数当施工轮次。scope的小收据提供revision/计划/TOKEN/message，引用路径+SHA-256，不复制日志。按[cycle证据](references/cycle-evidence.md)保证来源、时间和权限；SNAPSHOT_STALE重查新事实，不回放旧请求或重绑child。
6. ANOMALY/UNKNOWN先记自己的观察，再原生父子消息报告唯一所属Supervisor，保留真实受理事实，随后继续观察。正常无新事实不发噪音；同一旧异常不反复报警，新增事实才补报。不等回复、不因报告成功/父级处置/施工暂停而停止。

## 报告说清四件事

以“发现异常，请查验。”开头，附：谁（Run/CELL/attempt/message/角色）、最后可信事件与时间/应接手者、原生事实与记录矛盾或未知及最小证据路径/hash、需要Supervisor查验的决定。accepted只证明受理，不证明已读/接管/修复；父级自己的处置决定和后续事实才证明接管，不套工程ACK/TOKEN，也不承诺已结束父回合会自动被叫醒。

## 保障与停止

Temporal独立每1200秒核验OW；成员责任停留1800秒直接提醒Supervisor，只扣已确认PAUSED与责任重叠时间。不是OW判断无进展，也不代替600秒主动巡查。OW/Temporal保障失效不派下一CELL，保留现有成果，由Supervisor修复并提交匹配证据。

真实退出由宿主已提供的原生观察入口/退出Hook及Temporal保障向父级报告；不要把文档写有Hook当作平台已自动注册。UNKNOWN不等于退出，恢复可信证据不强制重启。仅所属Supervisor可决定并二次确认停止，包括其主动叫停也要确认。解除一个Run不停止其他Run；全部解除仍须父级确认。

正常Run终态依次D2_PASSED→terminal snapshot→本Run final cycle→close-overwatcher→RUN_CLOSED。凭据丢失由Supervisor恢复原绑定，不伪造cycle/退出。OW自己只可record-overwatch-cycle/record-overwatcher-status，不借他人凭据；工程角色也不代填你的观察。
