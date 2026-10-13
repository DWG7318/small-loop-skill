---
name: slk-check-cell
description: Use when an active Small Loop Skill (SLK) Run has a Checker ready to perform D1 on a Worker candidate.
---

# Check a CELL at D1

仅用于已选择 `$small-loop-skill` 的当前 Run。原 OCRV Checker 在与 Worker 隔离的对话中，对同一完整候选执行一次正式 D1；Tool、Supervisor、OW 和宿主都不代判。

## 先独立检查

1. 本地轻量预检核对当前 Run/CELL/候选消息/attempt、冻结目标及 D1 条件、候选元数据、changed paths、登记端点、模型与工具能力；必要时用原生 preview 定位完整候选。行数、文件数、上下文/容量只作提示，不加硬门槛、不自动切段。正常 aggregate budget/timeout 为原生 `0`，tool rounds 用已核实模板默认；Owner 冻结的有限预算不静默改写。
2. 先读原 CELL、全部目标、完整候选和必要客观事实，延后读 Worker 分区的 D0 结果、判断过程和建议关注点。优先复用仍有效的工程证据，覆盖相关回归和副作用，只为未覆盖风险补证；形成独立初步判断后再核对 Worker 客观原件。隔离不要求每个 CELL 新建环境，排除污染时按实际风险选择独立环境。
3. Git 外材料用绑定的 `slk_read_evidence(index, offset?, limit?)` 读取并核验原件身份/哈希。默认完整剩余原文，无工具长度上限；范围由 Checker 自选，路径已发不等于已读。Probe CLI/RTK 仅在 Owner 启用时降噪，不替代核心 diff、错误原文或验收证据。资源冲突时才读 [资源恢复](../slk-execute-cell/references/resource-contention.md)。

单文件、单组结束、同 native review ID 或 concurrency=1 都不证明冻结候选已全审；须跨文件核对全部 CELL 目标。不能证明全部目标就不能声称整个 CELL PASS，也不按组多次提交 D1。

## 原 Checker 显式决定一次

| 决定 | 本轮含义与去向 |
| --- | --- |
| PASS | 全部验收目标已有证明；原 Checker 按 `$slk-dispatch-cell` 交当前计划精确下一 Required CELL，末项交 `D2_READY`。 |
| FAIL | 实质产品缺陷；Checker → Supervisor，按 `$slk-rework-cell` 再交同一 Worker。 |
| INCOMPLETE | 关键证明不足或工具/环境故障导致未完成；用 `D1_INCOMPLETE_ESCALATION` 交 Supervisor 处理后回原 Checker，不触发返工，不写 `D1_PASSED/D1_FAILED`。 |

只有 PASS/FAIL 闭合 D1。管理消息 attempt 不是原候选 attempt。零 finding、低严重性观察、D0、process exit、JSON parse、business status 或 transport 成功都不自动生成结论；不编造 finding、复现或预期，不把故障算产品 FAIL，未实测目标环境不冒称实测。全部 Required CELL 有 D1 PASS 或 Supervisor 豁免后才进 D2。

先保存本人的事实、证据和完整原始报告（按需用 `$slk-record-run`）；索引用原件绝对路径/字节数/SHA-256。partial、长输出、非 JSON 和非零退出原样独立投递，不为 SLK 格式补交重跑。保存不等于接收，ACK/TOKEN/Temporal 失败不扣留报告。

组检查结束且旧后台工作停稳后，同一 Checker 对完整 CELL 收束判断；全组 reuse 但无本人 D1 时仍须收束，不重审成功文件。原 Checker 调用绑定的 `slk_checker_decide(verdict, message?)` **一次，作为最后业务动作**。工具用本人的密封凭据核对 Run、候选消息、candidate/D1 attempt 和原生调用，先保存本人决定；随后仅做响应刷出、原始结果/manifest 封存与原生退出，再由可信 Host 完成实际交接。`CHECKER_D1_RECORDED` 只说明决定已存，不说明已送达。纯传输恢复中，已有认证 D1 时不再调用模型，只续未完成交接；不要求 Checker 另写 Shell、第二次后缀或另一审查组。若另有实质证据证明原验收漏读必需合同或覆盖不足，保留原 D1 历史，交 Supervisor 按既有调整入口显式交原 Checker 重判；不能以补投递冒充已完成验收，也不由 Supervisor 代判。

真实交接是全部业务和证据封存后的最后任务动作。标准完成后缀核实后继真实 `slk.native-start/v2`，再原子提交 TOKEN 与唯一 `runtime_revision`；受理或终态不反推启动，不混候选/attempt/revision，不把一次性 Worker 进程用于托管长审查。Checker 不等待/轮询后继、不继续审查，也不留 post-turn/background 动作。工具缺失、内层 `isError`/业务失败或未明确决定仍交原报告并披露缺口；不由 Host 代判。真实 transport 失败只续原投递，不重新审查、改变历史 FAIL 或丢弃已保存 D1。

REQUESTED/PAUSED 不开新审查/派工，只按原暂停边界交出报告、管理回传及精确在途闭合，保留原决定和待续 operation。OW 只观察/报告 Supervisor，不代送、重试、写 Checker 事实或提交 TOKEN；guard 只阻断下一 CELL。
