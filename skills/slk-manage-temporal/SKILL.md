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
4. 取得真实 identity 后才冻结 RoleHost、OW 活动证据和 `<run>.json`；配置明确写 `admission_kind=PRODUCT|ISOLATED_CONFORMANCE_SAMPLE` 和对应 `admission_path`，前者只执行 `preflight-new-run`，后者只允许团队准备规则中的一次性单 CELL 样本执行 `preflight-conformance-sample`。再用 `slk-temporal-admit` 触发唯一 `slk.prepare_run`；只有状态成为 `READY/IDLE` 才把 readiness 收据交给 `$slk-manage-team`，未证明时不派首 CELL，同 ID 改参数不重建、不覆盖。

## 运行边界

- 每个交接由原角色把不可变 operation/message、sender/receiver、CELL/attempt、payload SHA-256 和 runtime revision 提交给已绑定 `SLK.Run`；其单个 Activity 是唯一物理启动入口，Role Host 不再同时直发。匹配 `slk.native-start/v2` 才是 ACK。
- ACK 超时只请求一次精确恢复，不换接收者、不改 payload、不重做工程副作用。恢复目标是原发送者，Supervisor 选择机械恢复或人工处理。
- 接收者真实启动后开始本 Run 的责任停留计时；同一成员超过 1800 秒，Temporal 直接通知登记的 Supervisor 一次，不由 OW 中转，也不判断长工作是否合理。
- 每 1200 秒独立调用原生状态适配器核查本 Run 的 OW；异常、UNKNOWN、无效收据或 Activity 失败形成 runtime guard 并报告。无消息的定时醒来继续等待，ACK/恢复等待期间仍执行保障检查；guard 修复前不派下一 CELL。
- OW 退出 Hook 由已有宿主独立观察，以闭合 notice 进入本 Run；不能依赖 OW 退出前自报。任何发起者都触发 Supervisor 二次确认；消息 accepted、原生 turn 启动、Supervisor 实际接管分别记录，不能互相替代。通知模型来自 Supervisor 的冻结绑定，不复制 OW 参数；恢复正确成员与 OW 后才解除 guard。
- 一个 Run 的计时、恢复、关闭或重放不改变其他 Run；共享服务只在没有任何活动 Run 后由运维侧正常停止。

## 收尾与故障

Run 的工程终结顺序完成后，Supervisor 关闭本 Run 的 `SLK.Run` 与 `SLK.Start`，只取消该 Run 的计时和待处理操作。Temporal 或 adapter 中途不可用时保留中央状态与候选，下一 CELL 保持阻断；代码漂移只用 hash-bound `reload-temporal-worker` 替换准确 worker 进程链，并复核同一 Start/Run workflow ID、native run ID 与 startup fingerprint，不重建历史或用临时脚本伪造 ACK。

## 负面提示词

- 不要把 Temporal 做成第二套 SLK、每 Run 独立服务器、工程裁决者、BI 写入器、角色创建器或模型路由器。
- 不要用 Activity 成功、进程退出、可见文本、旧 receipt 或工作流重放冒充 Agent 原生启动。
- 不要把 `BLOCKED`/`RECOVERY_REQUIRED` 变成等待超时，也不要在 ACK 后、中央 commit 前的重试中再次启动接收者或覆盖旧 update 结果。
- 不要让重试重新施工、重跑 D1、重复移动 TOKEN 或生成第二候选；不确定时保持阻断并交 Supervisor。
- 不要让单个 Run 关闭共享服务，也不要让一个 Run 的 ID、计时、恢复或证据污染另一个 Run。
- 不要在工作流身份尚不存在时伪造 identity/readiness，也不要让启动依赖尚未创建的 child identity；`PAIR_CREATED` 不是产品准入，`AWAITING_ADMISSION` 期间任何 CELL 投递均应被拒绝。
- 不要弹出 PowerShell/控制台窗口；服务和 worker 使用 headless 方式，BI 窗口仍按准备规则可见。
