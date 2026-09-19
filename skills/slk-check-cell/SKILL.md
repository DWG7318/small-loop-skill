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

1. 确认候选对应当前 `CELL n/N`，验收目标仍是规划时的目标。
2. 检查目标结果、相关回归、明显副作用和候选中客观可观察的风险。
3. 用 `slk-state write` 记录 `D1_STARTED`，优先使用现有测试、构建入口或直接操作，验证目标和真实未覆盖风险，形成独立判断；证据足够时收敛。检查命令遇到独占资源阻塞时按需读取 [`slk-execute-cell/references/resource-contention.md`](../slk-execute-cell/references/resource-contention.md)，不把占用误判为 D1 FAIL。
   Owner 已为本次 Run 启用效率工具时，Checker 可用 Probe CLI 独立定位影响范围，用 RTK 压缩高噪声测试或构建输出；核心 diff、关键错误原文和决定 D1 的证据仍直接检查，出现失败、截断或疑义时回退原生命令，不能让压缩摘要替代独立判断。
4. 随后读取 Worker 的 D0 与施工记录，核对是否出现新的客观事实或遗漏风险；D0 结论不替代 Checker 的独立证据。
5. 由 Checker 给出 D1 结论；检查工具或环境故障先定位，不直接算作产品缺陷。证据不足时记录未证明（不写为 PASS），优先换用现有可行验证方式，确需改变方案时交 Supervisor 协助：
   - `D1 PASS：CELL n/N`
   - `D1 FAIL：CELL n/N，进入返工`
6. D1 FAIL 时说明具体差距、复现方式和期望结果，让 Worker 能针对性修复。
7. 在执行 D1 的同时，顺手记录本 CELL 的容量事实，例如工作量是否合适、是否接近当前能力或是否因过大带来返工；这复用已有事实，不增加额外检查。
8. 把 D1 PASS/FAIL、错误、返工与容量事实通过 `slk-state write` 记录，建议调用 `$slk-record-run`；随后按精确端点调用 `slk-transport send`，原生启动成功后用 `slk-state handoff` 传递结论，失败时记录 `TRANSPORT_FAILED` 且仍由 Checker 持有责任。

## 后继

- D1 PASS 后，Checker 更新进度；还有 CELL 时沿 `Checker → Worker` 使用 `$slk-dispatch-cell` 校准并派发下一个既定 CELL。所有计划 CELL 都已经获得 D1 PASS 或单独记录的 Supervisor 豁免时，沿 `Checker → Supervisor` 交付最终令牌和 D2 条件。
- D1 FAIL 后，Checker 沿 `Checker → Worker` 交还令牌，并使用 `$slk-rework-cell` 与 Worker 继续直接协作。
- 需要改变 Run 方案时，请 Supervisor 使用 `$slk-adjust-run` 协助判断。

## 负面提示词

- 不要让 D0 结论或 Worker 判断引导初始 D1，也不要把对话隔离扩成每个 CELL 都新建验证环境；不要为检查器误报递归扩建证明材料，不要把工具故障直接判成产品失败，也不要以一般测试通过掩盖真实缺陷或把证据不足写成 PASS。
