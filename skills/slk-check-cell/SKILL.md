---
name: slk-check-cell
description: Use when an active Small Loop Skill (SLK) Run has a Checker ready to perform D1 on a Worker candidate.
---

# Check a CELL at D1

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

Checker 在与 Worker 隔离的对话中，对当前候选执行 D1，并给出可行动的结果。

## 隔离与输入

Checker 先读取原始 CELL 与 D1 目标、候选身份和客观工程事实。在形成独立 D1 判断前，延后读取 Worker 分区中的 D0 结果、判断过程和建议关注点。隔离不等于每个 CELL 都新建验证环境或检查体系；需要排除污染时，再按风险选择干净或独立环境。

## 建议检查

1. 先做 Checker 本地轻量预检：确认候选对应当前 `CELL n/N`，读取候选元数据、changed paths、验收条件、模型与工具能力、已通过的 OCRV runtime/model/adapter/endpoint 与 D1 验收目标。OCRV 先物化最终 background，记录字符/字节/证据量，再执行 `review --preview` 核对完整候选清单；旧的 800 行、2 文件、8000/12000 背景量和上下文估计只作提示，不切段或阻止模型启动。正常请求的 aggregate budget 与 review timeout 固定为原生 `0`（不限），`max-tools=0` 只表示采用已验证的模板默认轮数而不是无限；单组输入仍服从真实模型上下文。preview 不完整或身份不符仍在模型启动前返回 `OCRV_REVIEW_INCOMPLETE`。
2. 检查目标结果、相关回归、明显副作用和候选中客观可观察的风险。
3. OCRV 标准入口用密封 Checker 凭证记录绑定当前 candidate 的 `D1_STARTED`；Supervisor、Overwatcher 和普通 shell 不读取凭证、不代写 D1。Checker 优先使用现有测试、构建入口或直接操作，验证目标和真实未覆盖风险；独占资源阻塞时按需读取 [`slk-execute-cell/references/resource-contention.md`](../slk-execute-cell/references/resource-contention.md)，不把占用误判为 D1 FAIL。
   Owner 已为本次 Run 启用效率工具时，Checker 可用 Probe CLI 独立定位影响范围，用 RTK 压缩高噪声测试或构建输出；核心 diff、关键错误原文和决定 D1 的证据仍直接检查，出现失败、截断或疑义时回退原生命令，不能让压缩摘要替代独立判断。
4. 随后读取 Worker 的 D0 与施工记录，核对是否出现新的客观事实或遗漏风险；D0 结论不替代 Checker 的独立证据。
5. Checker 对完整候选给出唯一一个正式 D1 结果；只有 PASS 或 FAIL 闭合 D1。精确 PASS 复用应同时绑定 candidate、scope 和 criteria 哈希；过程把 `process exit`、`JSON parse` 与 `business status` 分开。合法 INCOMPLETE 可有空 findings/evidence，预算/超时、缺少关键证明或覆盖不完整保留证据并返回 `OCRV_REVIEW_INCOMPLETE`，检查工具或环境故障不写为 PASS，也不冒充产品 FAIL。发现绑定验收条件的实质产品缺陷才记 FAIL；若完整覆盖已经产生有效 MEDIUM/HIGH/BLOCKER/CRITICAL finding，辅助 Tool 的失败应作为附加 reason，不能覆盖已经成立的 FAIL；完整覆盖下只有低严重性观察时可以 PASS 并保留观察，不能机械判为 FAIL。INCOMPLETE 保留同一 candidate 与 D1 attempt，不增加返工 round；关键验收条件有直接证据才写 PASS。OCRV 长审查不由一次性 DSH/Worker 进程托管；旧版本已有封闭 D1-A/B/C partial 只按 `$slk-recover-communication` 消费，仍只形成一个正式 D1，不让新阈值切段。确需改变方案时交 Supervisor 协助：
   - `D1 PASS：CELL n/N`
   - `D1 FAIL：CELL n/N，进入返工`；`D1 INCOMPLETE：CELL n/N，说明未证明项`
6. D1 FAIL 时形成结构化 `D1_FAILURE_ESCALATION`；D1 INCOMPLETE 时形成结构化 `D1_INCOMPLETE_ESCALATION`，绑定当前未闭合事件、候选消息、reason codes、原生终态/result 与证据路径哈希，把 TOKEN 交给 Supervisor 做容量/环境管理。两者都不由 Checker直接启动下一次工作，但 INCOMPLETE 不含 findings/rework round、不增加 FAIL 次数，也不改变 D1 权威。
7. 在执行 D1 的同时，顺手记录本 CELL 的容量事实，例如工作量是否合适、是否接近当前能力或是否因过大带来返工；这复用已有事实，不增加额外检查。
8. 标准工具先把终态 run/message、当前原生 review 身份、实际 result SHA-256 及分段 aggregate/segment 哈希闭合绑定，再用 Checker 凭证把 D1 结果与容量事实写入 `slk-state`，建议调用 `$slk-record-run`；INCOMPLETE 只登记未证明项，不写 `D1_PASSED` 或 `D1_FAILED`。FAIL 用 `--slk-post-d1`，PASS 用 `--slk-complete-d1`，INCOMPLETE 用 `--slk-manage-incomplete` 把准确责任交给 Supervisor；只有接收者匹配 v2 start 与发送者原子 TOKEN commit 均成立，本轮才完成，否则记 `TRANSPORT_FAILED` 且责任仍由 Checker 持有。

## 后继

- D1 PASS 后，Checker 更新进度；还有 CELL 时沿 `Checker → Worker` 使用 `$slk-dispatch-cell` 校准，并由标准 PASS 后缀派发精确下一 CELL。所有计划 CELL 都已经获得 D1 PASS 或单独记录的 Supervisor 豁免时，标准 PASS 后缀沿 `Checker → Supervisor` 交付 `D2_READY`、最终令牌和 D2 条件。
- D1 FAIL 后，Checker 沿 `Checker → Supervisor` 发送 `D1_FAILURE_ESCALATION` 与 TOKEN，再由 `$slk-rework-cell` 进入受限返工路径。
- D1 INCOMPLETE 不触发返工或失败升级；标准管理后缀把 TOKEN 交给 Supervisor，Supervisor 选择等待真实原生工作、调整容量/环境或机械恢复，再把同一候选交回原 Checker 重判。旧有限预算记录仅在准确原因仍是 budget-only 且 Owner 明确授权时使用现有恢复 Tool；次数保护防重复副作用，不是工程永久额度，仍 INCOMPLETE 也应再次走管理出口而不能死停。

## 负面提示词

- 不要让 D0 结论或 Worker 判断引导初始 D1，也不要把对话隔离扩成每个 CELL 都新建验证环境；不要为检查器误报递归扩建证明材料，不要把工具故障直接判成产品失败，也不要以一般测试通过掩盖真实缺陷或把证据不足写成 PASS。
- 不要把行数、文件数或背景字符阈值当成硬拒绝或自动切段理由，也不要把零 finding、零 comments、无报错或空证据列表自动 PASS，或把合法 INCOMPLETE 的空 findings/evidence 判成 payload invalid；不要把低严重性观察机械升级为 FAIL，不要把 INCOMPLETE 当成第三种闭合结论，不要让 Supervisor 后补证据自动替代 Checker 的 D1，也不要把间接验证写成真实目标环境验证。
- 不要把 INCOMPLETE、`TRANSPORT_FAILED`、`OCRV_REVIEW_INCOMPLETE`、OCRV 进程退出或检查覆盖不完整伪装成产品 D1 FAIL、返工 round 或 `D1_FAILURE_ESCALATION`，不要让单个 segment verdict 冒充 aggregate D1，不要丢弃已完成 segment 后从零重查；不要让一次性 Worker/DSH 进程托管长审查，也不要让 Supervisor 重做或覆盖 OCRV 的 D1；不要把 Worker 的 DELIVERED、Overwatcher 的观察/恢复成功或 BI 状态当成 D1 PASS，也不要用终态结果补造缺失的启动证据或在 revisioned contract 中分步推进 TOKEN。
- 不要把 aborted 或预算终态 Session 当成自由重跑：前者仅在无 terminal、原进程已死、全部冻结身份/哈希匹配且未恢复过时，由密封原 Checker 先读 `session show`；后者不翻倍预算、不改全局默认、不手造无谱系 Session 或更换候选/attempt，也不把预算、工具、成本问题写成产品 FAIL。Root、Supervisor、Overwatcher 和普通 shell 不运行恢复、不接触 Checker 凭证、不代写 D1。
- 不要把“消息已发”、工具正常退出、可见文本、后来的终态或 OW/Supervisor 补救成功写成 Checker 已完成；不要跳过标准后缀、用错误下一 CELL、在未全部 D1 PASS 时发 `D2_READY`，或缺少接收者 v2 start/原子 TOKEN commit 仍结束 Checker。
