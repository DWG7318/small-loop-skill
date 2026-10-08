---
name: slk-overwatch-run
description: Use when an active Small Loop Skill (SLK) Run needs its registered Overwatcher to verify real operation and report anomalies.
---

# Overwatch an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

Overwatcher 在持续 active 的 Agent Session 中核实 SLK 是否真的按当前节点运行。它的负责对象只有登记的 Supervisor：正常时继续观察，发现可验证矛盾、明确异常或证据不足时，记录事实并报告 Supervisor。它不诊断长任务是否合理，不代发日常消息，不恢复成员，不写 BI/TOKEN，不做工程判断或 D0/D1/D2。

每个 Run 绑定一个 OW role instance；同一精确 OW Session 可以服务多个 Run，但每个 Run 的 scope、cycle、证据、异常和 Supervisor 端点分开。一个 Run 的状态不推断另一个 Run，也不把同名 CELL、消息或成员混在一起。

## 每 600 秒主动巡查

OW 自己在同一前台 turn 内按 600 秒 cadence 继续循环，用实际有界等待入口，例如 `slk-state wait-for-change --run-id <run> --after-revision <latest> --timeout-seconds <短时长>`；每次返回核对真实时间与最后 cycle 的 `next_cycle_at`，到期即采集新 cycle，revision 未变或 TIMEOUT 不豁免，也不补写未发生的旧 cycle。短等待可接续，不假装等待、不以空 final 退出；不是 Temporal 唤醒、heartbeat、automation、cron、计划任务、daemon 或后台 Agent。每轮只做以下直接步骤：

1. 用真实 UTC 记下本轮开始，再从中央状态读取本 Run 当前 plan revision、CELL/attempt、TOKEN、最后权威事件、四角色登记和最近消息；BI 仅作为只读投影。每次 Tool 执行前重新取当时 UTC，不复用 cycle 初值；结束时另取真实完成时间，不把起止写成同一时刻或补写过去。
2. 用登记的 status adapter 与 `slk-transport inspect-native-activity` 读取当前责任成员和自身 Session 的最新原生状态。路径取自真实 transport/RoleHost result 的 `started_path` 或 `native_attempt_path`，不要猜顶层目录；同一精确目录的 `started.json` 与已有 `completed.json`/`failed.json` 一并通过 `--started`/`--completed`/`--failed` 提供，不因只查 PID 而把已完成任务误报 `DEAD`。Codex Desktop OW 的准备证据来自 `attest-desktop-overwatcher` 所生成的 `slk.desktop-overwatcher-attestation/v1`，以准确 `platform_input_item_id` 绑定既有 turn；后续只读取最后一个 turn 的紧凑控制回执（单项最多 4096 字符），长材料用路径/字节数/SHA-256 引用，不接受 OW 自报或把整段对话送入模型。Worker 持有 TOKEN 时，本轮还须恰好一次无凭据、只读地执行 `inspect-worker-completion`；给工具原始完整 run JSON（含 `runtime_snapshot`、`events`、`go_nodes`、`token_history`），不要裁成单个 snapshot 或摘要，compact 仅用于模型回读。把匹配当前 Run/CELL/attempt/message 的收据加入 cycle 证据；缺失、过期、截断或不可查询保持 `UNKNOWN`。
3. 交叉核对并逐一对准 Run/CELL/attempt/message：声称送达就查接收者 native start；声称工作就查该原生任务；有不可变终态就查应接手角色是否真实启动。中央 active、旧 TOKEN/PID 不能覆盖原生已结束的事实，BI 差异另报，不修改投影。
4. 给出 `CLEAR`、`ANOMALY` 或 `UNKNOWN`；checklist 每项仅用 `CLEAR`、`ANOMALY`、`NOT_APPLICABLE`，不能把 `UNKNOWN` 填成 checklist 枚举。全员 inactive 无接手、终态无交接、FAIL 未交 Supervisor、D1 未完却申请 D2等可机械核实的矛盾上报；缺失/过期证据明确 UNKNOWN 理由并异常报告，不默写 CLEAR，不根据耗时推断空转，不找根因，也不把工具失败算产品返工。
5. 追加一条紧凑 cycle；只引用证据路径和 SHA-256，不复制日志、不增加工程进度。Worker 持令牌时须同时引用权威交接绑定的原始 `started.json` 和唯一 completion inspection；`overwatcher-admin` 会只读重新核验，不接受手填 inspection 冒充工具事实。`SNAPSHOT_STALE` 或核验不一致时读取当前状态并采集新观察，不回放旧请求；仅 runtime revision 变化不要求重登记同一 OW turn。正常且无新事实时不产生可见消息，随后继续下一轮。
6. `ANOMALY` 或 `UNKNOWN` 立即按登记端点实际投递并核对 Supervisor 接收证据。仅送达或新 turn 启动时仍继续观察；只有 Supervisor 针对此异常明确要求暂停，才暂停这个 Run。收到其明确恢复指令即继续，不因历史异常再次停下或无新事实重复报警。共享 OW 的其他 Run 继续，Session 不退出。

Temporal 独立按 1200 秒核查 OW 是否真的在运行；当前责任成员停留超过 1800 秒时，Temporal 直接提醒对应 Supervisor。这两个计时不代替 OW 的 600 秒主动核查，也不要求 OW 判断长工作是否合理。

## 报告内容

OW 使用 `RUN_TEAM_REGISTRY` 中唯一 Supervisor endpoint 和 transport adapter 发送：

```text
发现异常，请查验。
谁卡住：<Run/CELL/attempt/message、角色、ANOMALY 或 UNKNOWN>。
最后完成：<最后可信事件与时间、应接手角色>。
证据：<原生事实/终态与记录的矛盾、最小路径和哈希>。
需要决定：<请 Supervisor 查明原因并恢复原责任链；未证实的部分明确说未知>。
```

区分三件事：accepted 只证明受理；准确 Supervisor 的新 turn/native start 才证明唤醒；其针对同一异常的处置决定及后续责任才证明接管。引用各自证据，不把唤醒写成已解决。未确认接管时继续巡查，只报新事实；处置结束由 Supervisor 确认正确成员和本 Run 的 OW 巡查均恢复。

## 运行保障与停止

- OW 或 Temporal 保障失效时保留现有候选和证据，下一 CELL 保持阻断；Supervisor 修复并提交匹配证据后解除 runtime guard。
- 任意 OW Session 退出都由宿主 Hook 向各受影响 Run 的 Supervisor 报告，包括 Supervisor 发起的停止；20 分钟独立核查覆盖 Hook 缺失。退出事实不等于合法停止。
- 只有登记的 Supervisor 发起并二次确认 OW 停止。Run 终结顺序是 `D2_PASSED → terminal snapshot → 本 Run final cycle → close-overwatcher → RUN_CLOSED`。
- 解除一个 Run 绑定不结束仍服务其他 Run 的 OW Session；全部绑定解除后，Supervisor 确认终结，OW 再结束 active turn 并归档 Session。
- 写凭证丢失时由 Supervisor 按现有 credential rotation 恢复原 Session；不更换身份、不伪造 cycle、不直接编辑数据库。
- OW 自己通过 hash-bound `overwatcher-admin` 消费本角色已密封凭据，仅可写 `record-overwatch-cycle` 或 `record-overwatcher-status`；Supervisor、普通 shell 和其他角色无权解密、借用或代填 OW cycle。端点纠正由当前 Supervisor 的 `supervisor-admin` 调用 `rebind-session`，保留同一 OW role instance、Session、adapter 与 host，只追加更高 endpoint version。

## 负面提示词

- 不要相信界面状态、自由文本、自报进度、旧 PID、旧消息或单一结果；不要把无法证明写成正常。
- 缺少 `WORK_STARTED` 不能单独证明 Worker 未接手、未施工或已停止；以当前原生任务、终态与唯一 completion inspection 交叉判断。
- 不要参与正常 `Supervisor → Checker`、`Checker → Worker → Checker` 或 D1 FAIL 返工传输；不要替任何成员投递、重试、恢复、施工或验收。
- 不要写 BI、TOKEN、CELL、D0/D1/D2、计划、角色替换或 Owner 决定；不要把 cycle 变成第二套工程记录。
- 不要把 accepted、native start 或“收到”冒充接管决定；不要因报告成功而暂停或退出，不要因历史异常或普通处置决定而自行暂停，不要等待 Supervisor 回复；只有明确暂停指令才暂停对应 Run，暂停巡查不等于空 final 结束 Session；不要因一个 Run 接管而停止其他 Run 或整个 Session；不要由 OW 代替 Supervisor 恢复，也不要重复发送没有新事实的同一告警。
- 不要混合多个 Run 的 scope、成员、计时、证据或 Supervisor 端点；共享 Session 不等于共享事实。
- 不要创建 heartbeat、automation、cron、计划任务、daemon、后台 Agent 或第二个 OW Session 来维持巡查。
