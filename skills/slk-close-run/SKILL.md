---
name: slk-close-run
description: Use when an active Small Loop Skill (SLK) Run has D1 PASS or Supervisor exemption for every planned CELL and is ready for D2.
---

# Close an SLK Run

仅用于 Owner 已选择 SLK、全部 Required CELL 已有 D1 PASS 或版本化 Supervisor 豁免的 Run。Supervisor 负责真实组合 D2 和收尾控制；豁免单独保留，不冒充通过。

## 接手并真实开始 D2

封装原开始请求时按需读 [D2 操作字段](references/close-operations.md#d2-的原请求)，不另造开始协议。

原 Checker 以最后一个 `slk_checker_decide` 动作沿 `Checker → Supervisor` 交闭合 `D2_READY` 与最终令牌；匹配 Supervisor v2 native start **及** Checker 原子 TOKEN commit 才算交接完成。可见消息、终态或 bridge 准备好不替代它。

初始输入只聚焦原始 Run 目标、最终候选、端到端入口及必要客观环境，不先展开 Worker 判断或详细 D1 历史。原 Supervisor **实际开始时**用密封 `slk-transport start-d2 --request <原请求> --sha256 <哈希>` 记录一次 `D2_STARTED`，绑定准确 D2_READY/RoleHost/当前计划与 TOKEN。最终决定引用这次真实开始；重放保留原时间，不在完成时补造开始。

## D2 判断与回修

1. 对照 Owner 冻结范围核对最终累计 diff 与真实组合结果，检查 CELL 间衔接、主要端到端路径、关键风险、回归、副作用及限制；按 Run 风险用现有入口验证。共享 helper 也须属于已批准范围和正确模块，不因改动小就跨包。不把检查/验收本身另建为施工 CELL，不逐 CELL 重跑完整 D1 来冒充组合验证。
2. 可复用仍对应最终候选、环境及风险的有效客观证据，不能复用 D0/D1 的通过结论。**D1 PASS 不作为 D2 通过证明**；证据失效或关键风险未覆盖才补对应检查。工具/环境故障先定位，不直接判组合缺陷；不足的证据如实记“未证明”，未完成不写 PASS。
3. 形成初步 D2 判断后再读详细 D1、D0、返工、豁免及原件索引，核对完整性、候选对应、遗漏与记录一致性。缺实质支持交回 Checker 重判；Supervisor 后补证据不能替代 Checker 的 D1。
4. Supervisor 沿自身既有显式 D2 路径记录结论与组合证据，不用 `supervisor-admin` 代判 D2。发现问题写明范围，经 `$slk-adjust-run` 回 `Checker → Worker → Checker`，相关 D1 更新后重查受影响 D2，不重跑无关成果。

## 通过后

D2 通过后进入 `$slk-finalize-run`；已有真实 D2 结果的续收尾直接进入该 Skill，不重复验收。PAUSED 不是终态，暂停/重配置用 `$slk-pause-run`；放弃或撤销沿原真实终态处理，不伪造 D2 PASS。
