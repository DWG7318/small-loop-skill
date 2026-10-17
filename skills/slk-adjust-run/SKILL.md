---
name: slk-adjust-run
description: Use when an active Small Loop Skill (SLK) Run needs a Supervisor decision after repeated D1 failure, D2 findings, or changed resources.
---

# Adjust an SLK Run

仅用于 Owner 已选择 SLK 的当前 Run。Supervisor 决定调整路线；不代 Worker 施工或 Checker D1，不把工具输出当工程裁决。

## 何时介入

- 同一 CELL 第二次连续 D1 FAIL；首 FAIL 的一次普通返工用 `$slk-rework-cell`。
- Checker 已闭合提交 INCOMPLETE，或 D2 发现组合问题。
- 能力、资源、依赖或 CELL 变化影响原计划；单纯资源占用先用[资源恢复](../slk-execute-cell/references/resource-contention.md)继续同一节点。
- Owner 已明确历史独立 Run 的 canonical/source 身份，或需要显式采用新方法合同。

## 选择与权限

| 事实 | Supervisor 的行动 |
| --- | --- |
| 第二次连续 D1 FAIL | 对照两轮 findings、candidate diff、实际步骤、复现/回归和环境假设做 **AGGRESSIVE** 调查；把未接受范围版本化拆成中小后继 CELL，独立 D0、独立 D1，保留原目标、验收强度、已验成果与失败历史。不做第三次普通返工。 |
| INCOMPLETE | 不是产品 FAIL，不必凑两次失败。先交已有报告，再明确选择等待、容量、环境或机械修复等可行路线，由原角色执行明确行动；不依赖固定动作枚举、旧 partial 自动续审，不改写 PASS/FAIL 或代做 D1。 |
| D2/能力/资源改变 | 调整受影响 CELL、顺序、路线或验证方式；D2 返工仍用固定角色绑定。 |
| 重新规划仍未收敛 | 可在 D1 返工边界明确记录 Supervisor 豁免、影响及未来恢复条件；豁免不是 D1 PASS，也不是 D2。后续仍交 Checker，最终分别列通过数与豁免数。 |

现有工程权限内可自主处理可逆故障。新增范围、费用、账号、破坏性改变，或 Owner 掌握的电脑/工具/测试环境/业务权限，提交推荐路线、影响、替代与最低授权后再改。模型、推理或 Supervisor 权限不由本 Skill 自动变更；能力不足先调整 CELL/路线，需改变绑定仍由 Owner 决定。Run 目标与验收目标保持原约定，只有 Owner 改目标才更新。

## 记录并回到原链

1. 写入原因、两轮调查或 INCOMPLETE 事实、选择、影响、CELL n/N 与未决风险。计划调整用密封 `supervisor-admin revise-plan`，冻结新 revision RoleHost，更新同一 Run 的 Temporal Host 路径/哈希，不覆盖旧历史。
2. 需要暂停/参数变更时先用 `$slk-pause-run`：**REQUESTED 不等于 PAUSED**，已证实停稳才按原管理入口版本化；保留精确在途 operation/部分提交，从原节点恢复，不清故障 guard 或重做已完成工作。
3. 调整及记录完成、相关工作停稳后，以 `Supervisor → Checker` 的 `SLK TOKEN` / `CELL_DISPATCH` 作本次工程处置最后的任务动作。沿 `$slk-dispatch-cell` 由 Checker 派首个后继 CELL；不得直接发 Worker。原宿主核验 native start 并原子提交 TOKEN，确认正确成员接手且本 Run OW 巡查/Temporal 保障已恢复；未闭合只恢复原交接并如实列下一动作。成功后 Supervisor 保持 active，以有界原生等待接收结果，不接管普通 CELL。

OW 只向所属 Supervisor 报告观察，不替主管恢复成员、选路线、改计划、TOKEN 或 BI。保障失效先修复再派下一 CELL。

## 仅在对应技术情境读取

旧 Checker 有限 aggregate budget/timeout 需要容量迁移、Owner 已指定 canonical/source 身份，或真实 D2 FAIL 需要追加尾部修复 CELL 时，读[调整操作](references/adjustment-operations.md)的相应小节。Owner 冻结有限预算时不迁移。不要编辑 SQLite、伪造凭据/启动、猜 canonical、另造替代 Run，或借迁移改写原工程事实。
