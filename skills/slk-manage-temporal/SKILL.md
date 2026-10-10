---
name: slk-manage-temporal
description: Use when an active Small Loop Skill (SLK) Run needs its shared Temporal service and per-Run continuity workflows prepared, checked, repaired, or closed.
---

# Manage SLK Temporal

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

用一套本地共享、headless 的 Temporal 服务承载多个 SLK Run；每个 Run 只创建独立的 `SLK.Start` 与 `SLK.Run` 工作流。Temporal 保存通讯与运行保障事实，不复制工程状态，也不判断 CELL、D0、D1、D2、模型、TOKEN 或 BI。

## 开工准备

1. 检查本机登记的 Temporal 地址、namespace、task queue、执行进程和持久数据库可达；不为每个 Run 另装服务、另开端口或另建数据库。
2. 用 `RUN_TEAM_REGISTRY` 的四角色端点和当前 runtime revision 构造闭合 `StartSlkRequest`；方法版本为 4.4.2，未知字段、旧版本、重复角色或缺少 OW 都保持未就绪。
3. 标准 worker 使用 `--standard-config-root`，不要求项目自写 adapter。先用 `<run>.bootstrap.json` 校验真实中央初始登记和启动输入，再以稳定 Run ID 创建且仅创建一次工作流对并保存真实 identity；此时 `SLK.Run` 应停在 `AWAITING_ADMISSION`，任何投递均被拒绝。
4. 取得真实 identity 后才冻结 RoleHost、OW 活动证据和 `<run>.json`。现成 Codex Desktop OW 由继承真实 Desktop 能力的宿主执行 `attest-desktop-overwatcher --request <json> --sha256 <hash> --evidence-root <dir>`：闭合请求固定 `thread_id/host_id/cwd/turn_id/platform_input_item_id`，入口只调用 `read_thread`，生成匹配 `slk.native-start/v2` 与 `slk.desktop-overwatcher-attestation/v1`；不发送消息、不调用模型、不建 daemon。`<run>.json` 使用 `slk.temporal-standard-adapter/v2` 并绑定 attestation 路径/哈希，同时明确 `admission_kind=PRODUCT|ISOLATED_CONFORMANCE_SAMPLE` 和对应 `admission_path`；前者只执行 `preflight-new-run`，后者只允许一次性单 CELL 样本执行 `preflight-conformance-sample`。再用 `slk-temporal-admit` 触发唯一 `slk.prepare_run`；只有状态成为 `READY/IDLE` 才把 readiness 收据交给 `$slk-manage-team`，未证明时不派首 CELL，同 ID 改参数不重建、不覆盖。

## 运行边界

- 每个交接由原角色调用 hash-bound `continue-staged-handoff`，把不可变 operation/message、sender/receiver、CELL/attempt、payload SHA-256 和 runtime revision 经 Role Host 提交给已绑定 `SLK.Run`；其单个 Activity 是唯一物理启动入口，Role Host 不再同时直发。匹配 `slk.native-start/v2` 后仍由同一 Host 使用原发送者 sealed credential 提交中央 TOKEN；外部既有 request 要绑定其路径/哈希并只补原 operation 的 ACK+commit，已有 Host ACK 的重试只补 commit，不再 request/启动。
- ACK 超时只请求一次精确恢复，不换接收者、不改 payload、不重做工程副作用；这是短调用的防重复尝试数，不是工程恢复次数。恢复目标是原发送者，Supervisor 原则上优先机械恢复，也可按事实选择人工处理。
- 接收者真实启动后开始本 Run 的责任停留计时；同一成员达到 1800 秒（只扣已确认 PAUSED 的责任重叠时间，REQUESTED 不扣），Temporal 独立于 OW 的在线状态、巡查结论或自报，直接通知登记的 Supervisor 一次，只要求排查而不判断长工作是否合理。恢复不重置已用时；启动/RPC 的有限 timeout 只证明短调用结果，匹配 native start 之后不作为工程 turn 的死亡线。
- 每次 1200 秒审计重新调用 `inspect-native-activity --desktop-overwatcher-attestation <path> --desktop-overwatcher-attestation-sha256 <hash>`，由当次真实继承 Desktop thread/pipe/originator 的可信宿主实时 `read_thread` 核查同一 OW turn；初次 request 的 `reader_thread_id` 只证明 attestation 创建者，不锁死后续查询者，也不改变目标 Run/角色/endpoint/thread/turn/input/hash。不用 `native-activity.json` 的旧时间续命。异常、UNKNOWN、无效收据或 Activity 失败形成 runtime guard 并报告；guard 修复前不派下一 CELL。
- OW 退出 Hook 由已有宿主独立观察，以闭合 notice 进入本 Run；不能依赖 OW 退出前自报。任何发起者都触发 Supervisor 二次确认；消息 accepted、原生 turn 启动、Supervisor 实际接管分别记录，不能互相替代。通知模型来自 Supervisor 的冻结绑定，不复制 OW 参数；恢复正确成员与 OW 后才解除 guard。
- 一个 Run 的计时、恢复、关闭或重放不改变其他 Run；共享服务只在没有任何活动 Run 后由运维侧正常停止。

授权暂停使用 `$slk-pause-run` 和原密封 `pause-run/resume-run`：REQUESTED 即挡新施工，原结果/ACK/commit-only 保留；PAUSED 必须有全部旧调用的停稳证据。只有确认 PAUSED 的时间从成员 30 分钟责任计时扣除，REQUESTED 不扣，重复恢复不重置计时。OW 巡查与 20 分钟核验始终继续。暂停进入原 checkpoint（v2 可合法 IDLE，无须伪造 pending）；恢复保持原 operation、TOKEN、D0/D1 与故障 guard。中央/Temporal 半提交保持闸门，同 identity 补齐；排队原调用遇中央 PAUSED 不转失败恢复，中央释放后只唤醒原 pending。

## 收尾与故障

Run 的工程终结顺序完成后，Supervisor 关闭本 Run 的 `SLK.Run` 与 `SLK.Start`，只取消该 Run 的计时和待处理操作。Temporal 或 adapter 故障由 Supervisor 自主诊断、修复并验证既有范围内可逆操作，保留中央状态与候选，不逐次等待 Owner 许可；新增范围、费用、账号或破坏性改变仍交 Owner。下一 CELL 保持阻断；先真实 describe status/close time，不以 query 可读判断健康。运行中代码漂移只用 hash-bound `reload-temporal-worker` 保留原 pair；两执行确为 FAILED 时先用其 v2 `CLOSED_EXECUTION_MAINTENANCE` 加载唯一 worker（不是 READY），再用 `slk-temporal-recover prepare/restore` 保存原历史与 checkpoint、创建版本化同 Run 恢复 pair，最后正常重载到新 Host/config 根。标准步骤见 [`SLK-TEMPORAL.md`](../../docs/runtime/SLK-TEMPORAL.md#closed-execution-recovery)；原 pending 只补 ACK/commit，仍有未来运行保障，不重发、不重审、不重置历史。

## 负面提示词

- 不要把 Temporal 做成第二套 SLK、每 Run 独立服务器、工程裁决者、BI 写入器、角色创建器或模型路由器。
- 不要用 Activity 成功、进程退出、可见文本、旧 receipt 或工作流重放冒充 Agent 原生启动。
- 不要把 `BLOCKED`/`RECOVERY_REQUIRED` 变成等待超时，也不要在 ACK 后、中央 commit 前的重试中再次启动接收者或覆盖旧 update 结果。
- 不要让重试重新施工、重跑 D1、重复移动 TOKEN 或生成第二候选；不确定时保持阻断并交 Supervisor。
- 不要让单个 Run 关闭共享服务，也不要让一个 Run 的 ID、计时、恢复或证据污染另一个 Run。
- 不要在工作流身份尚不存在时伪造 identity/readiness，也不要让启动依赖尚未创建的 child identity；`PAIR_CREATED` 不是产品准入，`AWAITING_ADMISSION` 期间任何 CELL 投递均应被拒绝。
- 不要弹出 PowerShell/控制台窗口；服务和 worker 使用 headless 方式，BI 窗口仍按准备规则可见。
