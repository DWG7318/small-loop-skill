---
name: slk-close-run
description: Use when an active Small Loop Skill (SLK) Run has D1 PASS or Supervisor exemption for every planned CELL and is ready for D2.
---

# Close an SLK Run

仅用于 Owner 已选择 SLK、全部 Required CELL 已有 D1 PASS 或版本化 Supervisor 豁免的 Run。Supervisor 负责真实组合 D2 和收尾控制；豁免单独保留，不冒充通过。

## 接手并真实开始 D2

原 Checker 以最后一个 `slk_checker_decide` 动作沿 `Checker → Supervisor` 交闭合 `D2_READY` 与最终令牌；匹配 Supervisor v2 native start **及** Checker 原子 TOKEN commit 才算交接完成。可见消息、终态或 bridge 准备好不替代它。

初始输入只聚焦原始 Run 目标、最终候选、端到端入口及必要客观环境，不先展开 Worker 判断或详细 D1 历史。原 Supervisor **实际开始时**用密封 `slk-transport start-d2 --request <原请求> --sha256 <哈希>` 记录一次 `D2_STARTED`，绑定准确 D2_READY/RoleHost/当前计划与 TOKEN。最终决定引用这次真实开始；重放保留原时间，不在完成时补造开始。

## D2 判断与回修

1. 对照 Owner 冻结范围核对最终累计 diff 与真实组合结果，检查 CELL 间衔接、主要端到端路径、关键风险、回归、副作用及限制；按 Run 风险用现有入口验证。共享 helper 也须属于已批准范围和正确模块，不因改动小就跨包。不把检查/验收本身另建为施工 CELL，不逐 CELL 重跑完整 D1 来冒充组合验证。
2. 可复用仍对应最终候选、环境及风险的有效客观证据，不能复用 D0/D1 的通过结论。**D1 PASS 不作为 D2 通过证明**；证据失效或关键风险未覆盖才补对应检查。工具/环境故障先定位，不直接判组合缺陷；不足的证据如实记“未证明”，未完成不写 PASS。
3. 形成初步 D2 判断后再读详细 D1、D0、返工、豁免及原件索引，核对完整性、候选对应、遗漏与记录一致性。缺实质支持交回 Checker 重判；Supervisor 后补证据不能替代 Checker 的 D1。
4. Supervisor 沿自身既有显式 D2 路径记录结论与组合证据，不用 `supervisor-admin` 代判 D2。发现问题写明范围，经 `$slk-adjust-run` 回 `Checker → Worker → Checker`，相关 D1 更新后重查受影响 D2，不重跑无关成果。

## 通过后的唯一收尾顺序

`D2_PASSED → terminal snapshot → OW final cycle → close-overwatcher → RUN_CLOSED → close-role`

从未绑定 OW 的历史 Run 跳过两个 OW 节点；不是允许当前 Run 缺少必要 OW。`D2_PASSED` 只表示工程验收通过，不代表全部清理完成。

1. 冻结 D2_PASSED 同一 runtime revision 的真实 query 投影。OW 在真实 active 执行中写本 Run 唯一末轮观察，实查原生调用、残留 executor/子进程、状态与证据；需要恢复时保持同一 child/Session 的准确新激活身份，缺证记 UNKNOWN，不补造 cycle。
2. Supervisor 按 `$slk-archive-members` 的既有 `close-overwatcher` 操作解除**本 Run**绑定，绑定末轮 cycle 和匹配 revision。OW 是同一真实 Supervisor 的唯一直属 child，平时每 600 秒逐 Run 巡查；解除一个 Run 不停止 child，不影响其他 active/PAUSED Run。全部绑定结束后也只有所属 Supervisor 可决定停止，由退出 hook/二次确认完成；不关闭共享服务。
3. OW close 改变 revision 后，重新取得当前 revision 的实际 `inspect-run-quiescence` proof，覆盖本 Run 全部 Worker/Checker/Supervisor 旧调用、非持令牌者和 OCRV 实际 executor；仅准确当前主管收尾调用可协调。活调用等原生安全停点/自然退出，UNKNOWN 不当作停止，不猜 PID 或用 archived/completed 标签假停。按[关闭操作](references/close-operations.md)密封原 `supervisor-admin close-run`，写唯一 `RUN_CLOSED`；再通过原客户端结束/核实该 Run **精确** `SLK.Run/SLK.Start` 的实际 COMPLETED 与 close time，最终成功收据才算此操作完成。保留共享 Temporal 服务/Worker、其他 Run pair 和 Supervisor 对话。
4. 调用 `$slk-record-run` 导出最终 CELL 数、D0、D1 通过数、Supervisor 豁免数、限制与证据路径；Run 为 `CLOSED`，最后 TOKEN 仅保留历史持有人，不再派新工作，不伪造 `TOKEN_CLOSED` 事件。随后用 `$slk-archive-members` 按准确身份逐个 `close-role` Worker/Checker，核对当前及被替换成员的精确端点/归档收据，不对 Supervisor 执行 close-role。只有真实中央收据及投影 `lifecycle=exited`、`display_state=archived`、无 `active endpoint` 才称已归档；计划/命令已发/Session 退出均不够。
5. 使用过 Cargo 隔离目录时，仅在相关命令全退出后 `slk-cargo cleanup` 此 Run 的精确 runtime；lease 情况按关闭操作参考核实。向 Owner 简报 D0/D1/D2、豁免、限制、完成与未完成收尾、根记录路径。保留 Supervisor 最终交接与证据供后查。

任何半提交/失败保留原请求、event ID、native identity、证据和成功部分，只续原操作的未完成后缀；不重做 D2/工程、不换 ID 重发、不因 RUN_CLOSED 已写谎报清理完成。凭据只由可信消费者密封使用，模型/shell 不见明文。

PAUSED 不是终态，也不替代 D2/原生清理/角色归档；暂停与重配置用 `$slk-pause-run`，REQUESTED 不等于停稳。Owner 放弃/撤销沿原 `RUN_ABANDONED`/`SUPERSEDED` 路径如实记录，不伪造 D2 PASS；普通 CELL 边界不关闭、暂停、释放或重确认 OW。
