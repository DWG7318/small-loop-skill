---
name: slk-check-cell
description: Use when an active Small Loop Skill (SLK) Run has a Checker ready to perform D1 on a Worker candidate.
---

# Check a CELL at D1

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

Checker 在与 Worker 隔离的对话中，对当前候选和验收目标执行 D1，并给出可行动的结果。

## 隔离与输入

Checker 先读取原始 CELL 与 D1 目标、候选身份和客观工程事实。在形成独立 D1 判断前，延后读取 Worker 分区中的 D0 结果、判断过程和建议关注点。隔离不等于每个 CELL 都新建验证环境或检查体系；需要排除污染时，再按风险选择干净或独立环境。

## 检查与交付

1. 本地轻量预检核对当前 Run/CELL/attempt、候选元数据、changed paths、验收条件、模型与工具能力及已登记endpoint；必要时用原生 preview 定位完整候选。行数、文件数、上下文与容量事实只作提示，不增加额外检查、不自动切段或判结论，仍只形成一个正式 D1；正常 aggregate budget/timeout 为原生0，tool rounds采用已核实模板默认。独占资源按需读 [资源指引](../slk-execute-cell/references/resource-contention.md)。
2. 优先用现有工程证据直接检查候选、全部 CELL 目标、相关回归及副作用，只对真实未覆盖风险补证；先不读 Worker 的 D0 结论，形成初步判断后再核对其客观证据。Git 外材料用已绑定的 `slk_read_evidence(index, offset?, limit?)` 读取原件并核验身份/哈希：默认完整剩余原文，范围由 Checker 自选，无工具长度上限；路径已发不等于已读。Owner启用的 Probe CLI/RTK可压缩噪声，不替代核心 diff、错误原文和验收证据；疑义时读原文或回退原生命令。
3. 原 OCRV Checker 自己决定：实质产品缺陷为D1 FAIL，缺少关键证明或检查工具或环境故障导致未完成为D1 INCOMPLETE，未证明项不写为 PASS；INCOMPLETE不触发返工，不写 `D1_PASSED` 或 `D1_FAILED`，管理消息 attempt 与原候选 attempt 不能等同。只有 PASS 或 FAIL 闭合 D1；零 finding、低严重性观察、process exit、JSON parse 或 business status 不能机械判为 FAIL/PASS。
4. 有绑定的 `slk_checker_decide(verdict, message?)` MCP工具时，原Checker显式调用一次自己的D1决定，并按 `$slk-record-run` 保留自己的事实；工具内部验证确切Run/候选消息/原生调用及密封权限。没有该工具、调用失败或未明确决定时，原始报告仍交出，披露缺口，不让 Codex/宿主代判。工具发现和离线模拟不证明真实模型会正确调用。
5. 原始报告、partial、长输出、非JSON及非零退出事实均保存并独立投递；保存不等于接收。只传必要客观材料及原件路径/字节/SHA-256，Worker D0不进入初始独立判断。不为SLK格式补交重跑检查。
6. 本轮业务结束、原始报告与证据保存后，将上述明确工具调用作为最后交接：FAIL沿 `$slk-rework-cell`、INCOMPLETE沿 `D1_INCOMPLETE_ESCALATION` 把 TOKEN 交给 Supervisor；PASS沿 `$slk-dispatch-cell` 交精确下一CELL或最终`D2_READY`。OCRV不需要Shell或第二次后缀调用；响应刷出后结束本次原生调用，不再开审查组或继续施工。可附原Checker自己的发现/未完成原因，不补造finding、复现步骤或预期结果。身份、同一 candidate 与 D1 attempt、TOKEN原子提交和真实接手分别核实；动作或TRANSPORT_FAILED如实报告，不交一次性 DSH/Worker 进程托管长审查，原始报告仍独立交出。

## 后继

正常链仍为 Checker → Worker → Checker；正式FAIL才由 Checker → Supervisor → 同一Worker → Checker，全部Required CELL有D1 PASS或 Supervisor 豁免后才交D2。

## 负面提示词

- 不要把当前文件/原生group完成、同native review ID或concurrency=1当成整个冻结候选已审；先用跨文件工具核对全部CELL目标，不能证明全目标就不要声称全CELL PASS，不逐组或重复提交决定；不要让工具按正文/coverage/severity合成或纠正D1；不再使用旧partial/context/terminal自动消费或补交恢复路径，历史报告和FAIL只读保留。
- 不要让 Supervisor、OW、传输成功、原生终态、零 finding或D0代替D1或自动 PASS；不要复用失效证据、伪造真实目标环境验证、把工具故障计入产品返工，或把单段结果冒充完整候选。
- 不要跳过角色授权、当前Run/CELL/候选绑定、真实接收启动或TOKEN原子提交；报告送达本身既不授权下一CELL，也不等于工程PASS。
