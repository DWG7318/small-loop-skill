---
name: slk-pause-run
description: Use when an active Small Loop Skill (SLK) Run needs authorized construction pause, safe parameter changes, or resumption from its original node.
---

# Pause and resume an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 目标与权限

暂停的是本 Run 施工，不是巡查、共享服务或其他 Run。Supervisor 以准备阶段保存的密封管理权限请求暂停，即使当前 TOKEN 在 Worker/Checker，也不抢令牌。Worker、Checker、OW 不能批准暂停或恢复。Owner 的模型选择权限、既有故障 guard 和工程验收要求不因暂停改变。

唯一生命周期是 `RUN_PAUSE_REQUESTED → RUN_PAUSED → RUN_RESUMED`，保存在原 append-only work_events。`REQUESTED` 已禁止新的 CELL/返工派发，但不等于停稳；原 Worker→Checker 结果、Checker→Supervisor 管理回传、原 ACK 和 commit-only 可继续闭合。已有 D1 不重验、不撤回；其原角色保存的下一步 operation 留在原处，恢复时由原角色补原交接，不由 Supervisor 伪造。

## 请求与停稳

1. 保存当前 Run/计划/runtime revision、TOKEN、全部原 pending operation/message、候选、D0/D1、日志和故障 guard。用原 `slk-transport pause-run --request <密封管理请求> --sha256 <哈希>`；外层仍是 `slk.supervisor-admin/v1`，operation 为 `pause-run`，不把凭据明文放进提示或普通 shell。
2. operation request 为闭合 `slk.run-lifecycle/v1`：`run_id`、`role_instance_id`、唯一 `pause_id`、`binding_path/binding_sha256`、`adapter_config_path/adapter_config_sha256`、绝对 `evidence_root` 和准确 `coordinator_started_path`（无该调用时为 null）。绑定的是本 Run 原 RoleHost、原 Temporal pair、原施工和通知 attempt roots，不枚举其他 Run 或共享目录。保留请求原件/哈希，后续重试不换 identity 或 revision 来绕过半提交。
3. Host 先记中央 REQUESTED，再更新原 Temporal 执行闸门；一侧失败保持停派。检查所有本 Run 原生调用/writer，包括旧端点、非 TOKEN 持有者、OCRV 实际 executor/残留子进程；中央 native receipt 与两个原 attempt roots 都要核查。不把 transport completed、归档标签、adapter 名称、全局进程存活或另一 Run 的活动当作停止证明。
4. 使用原生能力让精确调用到安全停点或自然退出；需要隔离时必须能证明旧 writer 不再写本 Run。没有通用 stop adapter；不猜 PID、不杀共享 app server/Temporal/OW。缺原生结束证据、精确 executor identity 或仍活动时，结果是 `SUPERVISOR_ADMIN_PENDING/pause_requested`，逐项报告缺失，不能改参数或说“已暂停”。协调本次动作的准确 Supervisor 调用可留作收尾，不忽略其他 Supervisor 调用；换一次调用不能沿用旧协调豁免。
5. 全部施工调用停稳后才写绑定路径/哈希的 `slk.run-quiescence/v1`、中央 RUN_PAUSED 和原 Temporal PAUSED。核对两侧同一 pause/event。只有成功最终收据缓存为完成；pending 证据保留。中央已成功而 Temporal 回执丢失时，重试原请求只补同一生命周期后缀，不重复工程动作。精确结构与不可变 proof 的执行取证入口见 [Transport 生命周期](../../docs/transport/SLK-TRANSPORT.md#run-lifecycle)。

## 修改与恢复

只在已证实 PAUSED 后，通过原管理入口版本化改参数、端点或采用方法合同；不改 SQLite，不覆盖旧登记。模型变化仍需 Owner 决定。按变化范围重做原团队预检、身份/能力检查与必要的正常通讯复测；补救通路不算正常通过。OW 和 Temporal 本 Run 核验仍有效，旧 writer 已停且原未完成 operation 可识别，才继续。

使用原 `slk-transport resume-run` 与新密封外层请求；operation request 保留同一 `pause_id`，上述字段绑定现在的 Host/config，另加原 `pause_request_path/pause_request_sha256`，以便同时核查旧 roots。Temporal RESUMED 先确认，中央 RUN_RESUMED 最后释放施工闸门，再用原 RESUMED identity 唤醒原 pending。半提交窗口碰到中央 PAUSED 的排队调用保持原 pending，不标失败/超时、不启动恢复、不 busy-loop；重试原请求补齐，不换操作或第二次派发。

恢复原节点和原 operation：不重做已完成工程/D0/D1、不重置 TOKEN、责任计时或故障 blocker，不用暂停冒充故障修复。成员 30 分钟计时仅扣**已确认 PAUSED**的重叠时段，REQUESTED 不扣；20 分钟工作 + 60 分钟暂停 + 10 分钟工作仍到 30 分钟阈值。暂停期间责任人变化，只扣其开始负责后的重叠时间；重复 resume 不再次扣时。OW 600 秒巡查、Temporal 1200 秒 OW 核验、其他 Run 计时始终继续。

## 负面提示词

- 不以“发出暂停命令”“停止派工”或 UI 标签冒充所有旧调用停稳；未知就是未证明，不假停，也不把有真实原生结束证据的历史调用永远当活调用。
- 不在 REQUESTED 改参数；不在一侧失败后换 ID/宽泛绕过 stale revision；同一请求只能凭自己的准确生命周期事件补齐。
- 不丢弃半提交、原候选、D1 或原 handoff；不由 Supervisor 补写 Checker 决定，不借恢复重跑 D0/D1/工程动作或解除真实 fault guard。
- 不暂停 OW 巡查，不停共享 Temporal/Worker/OW Session，不清其他 Run 的 TOKEN、计时、文件或服务。Owner 放弃沿原 RUN_ABANDONED/SUPERSEDED 路径，不假造 D2 PASS。
