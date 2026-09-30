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

1. 先做 Checker 本地轻量预检：确认候选对应当前 `CELL n/N`，读取候选元数据、changed paths、验收条件、模型与工具能力、已通过的 OCRV runtime/model/adapter/endpoint 与 D1 验收目标。OCRV 先物化最终 background，记录字符/字节/证据量，再执行 `review --preview`；仅按 preview 的真实 reviewable paths、criteria 和容量动态生成顺序 `D1-A/B/C...` 内部段。每段用 `--exclude` 排除其余候选路径，preview 选中路径应与 manifest 完全相同，否则模型启动前返回 `OCRV_REVIEW_INCOMPLETE`。内部段共享同一 CELL、candidate、attempt 与 TOKEN，仍只形成一个正式 D1。
2. 检查目标结果、相关回归、明显副作用和候选中客观可观察的风险。
3. OCRV 标准入口用密封 Checker 凭证记录绑定当前 candidate 的 `D1_STARTED`；Supervisor、Overwatcher 和普通 shell 不读取凭证、不代写 D1。Checker 优先使用现有测试、构建入口或直接操作，验证目标和真实未覆盖风险；独占资源阻塞时按需读取 [`slk-execute-cell/references/resource-contention.md`](../slk-execute-cell/references/resource-contention.md)，不把占用误判为 D1 FAIL。
   Owner 已为本次 Run 启用效率工具时，Checker 可用 Probe CLI 独立定位影响范围，用 RTK 压缩高噪声测试或构建输出；核心 diff、关键错误原文和决定 D1 的证据仍直接检查，出现失败、截断或疑义时回退原生命令，不能让压缩摘要替代独立判断。
4. 随后读取 Worker 的 D0 与施工记录，核对是否出现新的客观事实或遗漏风险；D0 结论不替代 Checker 的独立证据。
5. 由 Checker 汇总内部检查段后给出唯一正式 D1 结果；只有 PASS 或 FAIL 闭合 D1。段严格顺序执行，HIGH/BLOCKER/CRITICAL finding 立即停止后继；精确 PASS 复用应同时绑定 candidate、scope 和 criteria 哈希。aggregate 只接收段身份、verdict、reason codes、finding 摘要及 request/result 哈希，不回灌完整段结果或其路径。过程把 `process exit`、`JSON parse` 与 `business status` 分开；段超时、缺少关键证明或覆盖不完整保留证据并返回 `OCRV_REVIEW_INCOMPLETE`，检查工具或环境故障不写为 PASS，也不冒充产品 FAIL。发现绑定验收条件的实质产品缺陷才记 FAIL；完整覆盖下只有低严重性观察时可以 PASS 并保留观察，不能机械判为 FAIL。INCOMPLETE 保留同一 candidate 与 D1 attempt，不增加返工 round；关键验收条件有直接证据才写 PASS。OCRV 长审查不由一次性 DSH/Worker 进程托管；确需改变方案时交 Supervisor 协助：
   - `D1 PASS：CELL n/N`
   - `D1 FAIL：CELL n/N，进入返工`；`D1 INCOMPLETE：CELL n/N，说明未证明项`
6. D1 FAIL 时形成结构化 `D1_FAILURE_ESCALATION`：绑定失败事件、候选哈希、返工轮次、CELL 目标、验收条件、具体差距、复现方式、期望结果和证据引用；把 TOKEN 交给 Supervisor 生成改进指引，不由 Checker 直接启动返工。
7. 在执行 D1 的同时，顺手记录本 CELL 的容量事实，例如工作量是否合适、是否接近当前能力或是否因过大带来返工；这复用已有事实，不增加额外检查。
8. 标准工具先把终态 run/message、当前原生 review 身份、实际 result SHA-256 及分段 aggregate/segment 哈希闭合绑定，再用 Checker 凭证把 D1 结果、错误、返工与容量事实写入 `slk-state`，建议调用 `$slk-record-run`；INCOMPLETE 只登记未证明项，不写 `D1_PASSED` 或 `D1_FAILED`、不推进令牌。后继交付仍由发送者在匹配 v2 start 后原子提交 TOKEN、事件和 revision；失败记 `TRANSPORT_FAILED` 且责任仍由 Checker 持有。

## 后继

- D1 PASS 后，Checker 更新进度；还有 CELL 时沿 `Checker → Worker` 使用 `$slk-dispatch-cell` 校准并派发下一个既定 CELL。所有计划 CELL 都已经获得 D1 PASS 或单独记录的 Supervisor 豁免时，沿 `Checker → Supervisor` 交付最终令牌和 D2 条件。
- D1 FAIL 后，Checker 沿 `Checker → Supervisor` 发送 `D1_FAILURE_ESCALATION` 与 TOKEN，再由 `$slk-rework-cell` 进入受限返工路径。
- D1 INCOMPLETE 时 Checker 保留 `SLK TOKEN`，不触发返工或失败升级；优先补齐证据，确需改变 Run 方案时再请 Supervisor 使用 `$slk-adjust-run` 协助，Supervisor 提供新证据后仍由 Checker 重判 D1。

## 负面提示词

- 不要让 D0 结论或 Worker 判断引导初始 D1，也不要把对话隔离扩成每个 CELL 都新建验证环境；不要为检查器误报递归扩建证明材料，不要把工具故障直接判成产品失败，也不要以一般测试通过掩盖真实缺陷或把证据不足写成 PASS。
- 不要把 D1-A/B/C 内部检查段并行化、分配给其他角色、推进 TOKEN 或记录成多次正式 D1；它们始终汇成一个正式 D1。不要把零 finding、零 comments、无报错或空证据列表自动 PASS，也不要把低严重性观察机械升级为 FAIL；不要把 INCOMPLETE 当成第三种闭合结论，不要让 Supervisor 后补证据自动替代 Checker 的 D1，也不要把间接验证写成真实目标环境验证。
- 不要把 INCOMPLETE、`TRANSPORT_FAILED`、`OCRV_REVIEW_INCOMPLETE`、OCRV 进程退出或检查覆盖不完整伪装成产品 D1 FAIL、返工 round 或 `D1_FAILURE_ESCALATION`，不要让单个 segment verdict 冒充 aggregate D1，不要丢弃已完成 segment 后从零重查；不要让一次性 Worker/DSH 进程托管长审查，也不要让 Supervisor 重做或覆盖 OCRV 的 D1；不要把 Worker 的 DELIVERED、Overwatcher 的观察/恢复成功或 BI 状态当成 D1 PASS，也不要用终态结果补造缺失的启动证据或在 revisioned contract 中分步推进 TOKEN。
