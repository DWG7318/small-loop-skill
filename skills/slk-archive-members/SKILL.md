---
name: slk-archive-members
description: Use when an active Small Loop Skill (SLK) Run has reached its truthful terminal state and its registered engineering endpoints must be retired.
---

# Archive the Run's members

仅用于已启用 SLK 的 Run，由 Supervisor 负责。归档是确切状态操作，不是把对话叫作“已归档”。工程收尾次序由 `$slk-finalize-run` 控制，本指引仅说明成员操作。

## 正常结束次序

1. `D2_PASSED → terminal snapshot → 本 Run final OW cycle → close-overwatcher → RUN_CLOSED`。用 hash-bound `supervisor-admin close-overwatcher` 在同一 runtime revision 消费已密封 Supervisor/OW 凭据，保存最后真实 cycle 并解除本 Run 绑定，不能先关闭 Run 再补观察。
2. 终态完整后，对准确 Worker、Checker 用 hash-bound `supervisor-admin close-role`；消费者内部执行 `slk-state close-role`。TOKEN、身份、终态或凭据不匹配便不声称完成；原请求可幂等重放，不另造归档事件。
3. 查询 `slk-bi-query roles`，只有中央 `ROLE_CLOSED` 收据及 `display_state=archived` 才称已归档。该操作追加退出事实、退役 active endpoint、撤销凭据；不创建继任者、不移动 TOKEN、不改写 D1/D2/Run 结论。Supervisor 保留。
4. 将真实收据与未完成事项交还收尾流程。原生 Session 结束、发出命令或 UI 标签都不代替中央收据。

## 共享 OW 与其他终态

OW 是 Supervisor 唯一直属 child，可服务该 Supervisor 多个 Run。解除此 Run 不停止 child 或其他 Run；即使全部解除，也只有所属 Supervisor 能决定并二次确认停止。原生真实退出须留证并报告父级，UNKNOWN 不是退出；不借用 OW 凭据代写巡查。

放弃或被替代的 Run 沿真实 `RUN_ABANDONED`/`SUPERSEDED` 路径及对应管理合同收尾，不能伪造 D2 PASS。终态或原生结束证据未闭合，列出缺项交 Supervisor，不宽泛删 Session、数据或后台进程。

每 Run Temporal 工作流关闭由 `$slk-manage-temporal` 处理；不关闭仍承载其他 Run 的共享服务。准确生命周期参数按需读 [管理合同](../../docs/transport/SLK-TRANSPORT.md#run-lifecycle)。
