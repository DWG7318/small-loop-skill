---
name: slk-close-run
description: Use when an active Small Loop Skill (SLK) Run has D1 PASS or Supervisor exemption for every planned CELL and is ready for D2.
---

# Close an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

所有计划 CELL 都有明确处理结果后，Supervisor 判断全部成果合起来是否正确。通过后完成记录、成员归档和 Owner 结论；发现组合问题时，把工作送回最近的正常节点。

## 激活与 D2 交接

所有 Required CELL 都有明确处理结果后，原 Checker 以最后一个 `slk_checker_decide` 动作沿 `Checker → Supervisor` 发送闭合 `D2_READY` 并以最终令牌激活 Supervisor；只有匹配 Supervisor v2 start 和 Checker 原子 TOKEN commit 都成立才完成交接。每个 CELL 的结果是 `D1 PASS` 或版本化 Supervisor 豁免；两者分别记录，不把豁免改写为完成。初始交接聚焦原始 Run 目标、最终候选、端到端入口和必要的客观环境信息，不先展开 Worker 判断与详细 D1 历史。

## 检查对象隔离

1. 原 Supervisor 实际开始 D2 时调用 `slk-transport start-d2 --request <密封管理请求> --sha256 <请求哈希>`：`operation=start-d2` 的原请求绑定本 Run、Supervisor role instance、RoleHost binding 路径/哈希和准确 `D2_READY` 的 `source_attempt_path`，由原 Host 核对当前 TOKEN/计划/原生身份并记录一次 `D2_STARTED`；重放不改开始时间。随后从 Run 目标、各 CELL 结果、最终候选和端到端入口检查真实组合结果，最终决定引用这次开始，不等到结果时补记开始。
2. 优先用现有入口直接检查 CELL 间衔接、主要端到端路径、关键风险、相关回归、副作用和剩余限制；按 Run 风险选择必要检查，不以新建检查体系替代真实组合验证。检查工具或环境故障先定位，不直接算作组合缺陷；证据不足记录未证明，交回可行验证路线，不写为 PASS。
3. 形成初步 D2 判断后，随后读取详细 D1 记录、D0、返工、豁免和证据位置，核对 CELL 是否完整、D1 是否由对应候选的证据支持、是否出现遗漏事实以及记录是否一致；缺少实质支持时交回 Checker 重判，不由 Supervisor 补写 D1。
4. D1 PASS 不作为 D2 通过证明；它只说明单个 CELL 的 D1 结果。D2 结论仍由组合、衔接和端到端证据支持。

D2 可以复用仍对应最终候选、环境与风险的有效客观证据，但不复用 D0、D1 的通过结论；重点仍是组合、衔接和 Run 风险，减少逐项重复 D1。证据失效或关键风险未覆盖时，再补相应检查。

## D2 发现问题

Supervisor 描述组合问题和受影响范围，建议调用 `$slk-adjust-run` 选择相关 CELL。修复路径回到：

```text
Checker → Worker → Checker
```

相关 D1 更新后，Supervisor 再检查受影响的 D2 部分。

## D2 通过后的收尾

唯一顺序：`D2_PASSED → terminal snapshot → OW final cycle → close-overwatcher → RUN_CLOSED → close-role`；本 Run 从未绑定 OW 时跳过两个 OW 节点，不改变其余顺序。

1. 用密封 `supervisor-admin` 之外的既有 D2 路径记录 `D2_PASSED`，冻结同一 runtime revision 的 `terminal snapshot`；若本 Run 绑定 Overwatcher，Supervisor 应在 `RUN_CLOSED` 前恢复仍属同一 Session 的必要 foreground turn，由 OW 写唯一 `OW final cycle`，再让 `supervisor-admin close-overwatcher` 同时消费密封 Supervisor/OW 凭据并绑定该 cycle ID 与同一 revision。关闭成功只归档本 Run 的 OW 绑定，不改变工程历史或 TOKEN。
2. OW 已关闭（或本 Run 从未绑定 OW）后才让密封 `supervisor-admin close-run` 写唯一 `RUN_CLOSED`，调用 `$slk-record-run` 导出最终 CELL 数、D0、D1通过数、Supervisor豁免数、限制和证据位置，并把最终 `SLK TOKEN` 标记为 `CLOSED`、不再流转。随后调用 `$slk-manage-team`：Supervisor 以 `supervisor-admin close-role` 按准确身份分别归档 Worker、Checker；重放同一请求是安全的，event ID 复用来表达不同内容会被拒绝。模型和普通 shell 均不接触角色凭据明文。只有中央投影同时显示 `lifecycle=exited`、`display_state=archived` 且没有 `active endpoint`，才可称该角色已经归档。保留 Supervisor 对话，不对其执行 `close-role`。本 Run 使用过 Cargo 隔离目录时，在相关命令全部结束后执行 `slk-cargo cleanup` 清理其精确 Run runtime。
3. 向 Owner 发送一个简洁结论，例如：Run 已完工，D0/D1/D2结果、豁免数量、已知限制和根记录路径。

Owner 可以根据结论继续查询；Supervisor 保留最终交接、D2结论和根记录路径，需要时再查阅详细工程历史。

## 负面提示词

- 不要把 D1 PASS 当成 D2 通过证明，或用逐 CELL 重跑完整 D1 替代真实组合、衔接与端到端检查；不要复用已失效的证据、跳过关键未覆盖风险，也不要把豁免写成通过或把归档计划写成已经归档。
- 不要把“计划归档”、原生 Session 已结束或已发出关闭命令写成“已经归档”；缺少 Worker/Checker 的中央 `close-role` 收据时，active/ready 就是真实未归档状态。
- 不要忽略这一边界：Supervisor 后补证据不能替代 Checker 的 D1；不要追认原本证据不足的 PASS，也不要在令牌尚未真实交回 Supervisor 时写入 D2 已开始或 Run 已关闭。
- 不要在 `D2_PASSED` 前或缺少 OW final cycle/匹配 runtime revision 时关闭 Overwatcher；不要先写 `RUN_CLOSED` 再尝试恢复 OW turn、补 terminal cycle 或关闭 OW，也不要在普通 CELL 边界关闭、暂停、释放或重新确认 Overwatcher。
- 不要让单条“请做 D2”、可见消息、终态结果或 Desktop bridge 已准备冒充 `D2_READY` 已交付；缺少全部 Required CELL 的当前 D1 结果、Supervisor v2 start 或 Checker 原子 TOKEN commit 时，不开始 D2。
