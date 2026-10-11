---
name: slk-execute-cell
description: Use when an active Small Loop Skill (SLK) Run has a Worker ready to implement one received CELL.
---

# Execute a CELL

仅用于已选择 `$small-loop-skill` 的当前 Run。原 Worker 完成一个既定 CELL、最低 D0 和可检查候选，再直接交回原 Checker。

## 本地预检与连续施工

1. 对照已通过的 Run readiness，核对 DSH runtime/model/adapter/endpoint、所需 Skill/Tool、真实上下文与任务能力；核对不可变 task file/SHA-256、当前 `runtime_revision`、TOKEN、`CELL n/N`、目标/范围/依赖、D1 目标及候选基线。相同或更旧 TOKEN 不重开 CELL。
2. 启动前做有界 Git 预检：repo root、worktree、common-dir、objects/refs 均须符合沙箱可写边界；支持独立可写 clone/simple layout，拒绝 common-dir 在沙箱外的 linked worktree。实例 ID 确定且不超过合同的 64 字符。预检失败或范围明显超能力时保留已有输出，报告实际限制，不造 candidate 或自行搬移布局。
3. 同一 CELL 内连续完成编辑、命令、测试和最低 D0。可按需要顺序分内部段，但不另建 CELL/TOKEN、不并行 Worker、不换目标或自行进入未派发 CELL。最低 D0 围绕本次变化和风险提供基本信心，不重复完整 D1/D2。
4. 原 Worker 用本次原生调用绑定的 `SLK_WORKER_ACTION_COMMAND` 调用 `submit-worker-action --event WORK_STARTED|D0_COMPLETED|CANDIDATE_SUBMITTED --details <本人的JSON动作文件>`，显式记录自身事实；候选动作含实际 `candidate`。所属可信入口内部消费本人的密封权限和密封 Checker endpoint/envelope，不泄露凭据，不从最终报告合成 D0 或候选。

独占资源阻塞时才读 [资源恢复](references/resource-contention.md)，恢复同一节点，不算返工。Owner 已启用 Probe CLI/RTK/Ponytail 时可用于定位、低噪声输出和减少过度施工；完整原文仍可追溯，失败、截断、疑义或核心代码事实回读原文/原生命令。正式 FAIL 返工只接受绑定当前失败事件、候选和 round 的 `D1_REWORK_DIRECTIVE`，不是 Supervisor 的 D1 裁决。

## 保存事实，不污染初始 D1

交接前把实际变化、D0 原始结果/判断/风险写入 **Worker 事实与证据分区**，通过所属宿主的 `slk-state write` 追加并导出；大证据用 `register-evidence`。默认入口是紧凑 evidence index：命令、退出码、摘要/关键失败、原件绝对路径、字节数、SHA-256；完整原件保留可读，不截断材料。需要记录细节时用 `$slk-record-run`。

初始 Checker 业务载荷只含统一 TOKEN 头、`CELL n/N`、候选身份/访问位置、客观变更范围及运行候选必需的事实。D0 结果、判断过程、建议关注点留在 Worker 分区，待 Checker 独立判断后再核对；不拼进初始 D1 背景。**这不允许丢弃或扣留原始报告：完整报告仍独立保存、原样投递，D0 部分保持所属分区。**

## 最后动作：候选交接

施工、D0、本人事实、报告与证据准备完成后，以标准候选提交/交接作为最后任务动作。可信 Host 保存完整原件并独立交原 Checker；自由文本、partial、长输出、非 JSON、缺项/多字段或非零退出都不触发格式补交或重跑。候选缺失时交出报告并披露 Checker 无法审查的真实限制，不编造 workspace 候选。

代码完成、保存报告、受理或 TOKEN 维护成功均不等于交付。报告投递不等 ACK/TOKEN/Temporal 维护；工程推进另核实恰好一次当前 Run/CELL/attempt/candidate、payload 哈希和原 Checker 的真实 `slk.native-start/v2`，随后原子提交 TOKEN 与唯一 `runtime_revision`。终态不能补造启动，不能分步 handoff。匹配提交后结束，不等 D1、不轮询或读取 Checker 状态、不重复交接，也不留 post-turn/background 动作。

明确未启动、端点不可用或投递失败才用 `$slk-recover-communication`；OW 只观察/报告 Supervisor，不替 Worker 投递、exact retry、写事实或提交 TOKEN。REQUESTED/PAUSED 不开新施工；只沿原暂停边界闭合原输出、ACK 或 commit-only，不借恢复重做工程。原 Checker 随后用 `$slk-check-cell` 执行隔离 D1。
