---
name: slk-troubleshoot-run
description: Use when an active Small Loop Skill (SLK) Run has uncertain member, handoff, state, resource, or continuity anomalies during construction.
---

# Locate an SLK Run anomaly

仅用于已选择 SLK 的 Run。这是**可选**的短定位入口，不是正常通讯、验收或恢复的必经层；已知故障可直接到既有 Skill。它不授予新修复权限，不接管产品 Debug、D1 或 Supervisor 决策。

## 先保留并定位

1. 保留已有报告、候选、原请求/operation、原始日志及成功/部分提交，不为排障重跑工程。用当前中央只读投影、根记录和计划核对精确 Run、CELL/attempt、TOKEN、角色/端点、message 与最后可信事实；摘要或旧话题冲突时先停止串题，不猜最近 Session。
2. 区分已保存、已受理、真实 native start、原角色工程决定、ACK/TOKEN 提交及实际结束。原件缺失、过期或矛盾保持 UNKNOWN；不从退出码、UI、报告格式或另一 Run 的活动推断 PASS、接手、停稳或死亡。
3. 只选当前原因对应入口；命令/具体取证线索按需读[运行预案](references/run-recipes.md)的相应小节，不加载全部参考。

Supervisor 对现场补漏与结果核验负责，不把可处理的漏交资料、错误位置或未闭合后缀一律退给 SLK 开发。可绕开不适用的流程障碍，用自己的身份代交已有原件、补充客观说明或续机械后缀；记录原责任人、原件/hash、自己的动作与未完成项。代交不等于代写 Worker/Checker 工程事实或代判 D1；资料确实不存在则如实披露，不补造。需要源码根治的缺陷另行留证，不妨碍权限内现场处置。

| 当前操作/事实 | 直接入口 |
| --- | --- |
| 已有精确消息/交接，缺接收或提交证据 | `$slk-recover-communication`；由原发送者沿原 operation 恢复，不换 ID 或重发已确认交接。无原消息不套它。 |
| 成员真实失活、登记/端点需要恢复或替换 | `$slk-replace-member`；Supervisor 决策，Supervisor 自身替换仍由 Owner。 |
| 正常 D1 FAIL / INCOMPLETE / 调整路线 | 首 FAIL 用 `$slk-rework-cell`；第二次连续 FAIL、INCOMPLETE 或 D2/能力问题用 `$slk-adjust-run`。排障不改判。 |
| 锁/独占资源冲突 | [资源恢复](../slk-execute-cell/references/resource-contention.md)，从同一检查/施工节点继续。 |
| OW/Temporal 保障异常、UNKNOWN 或状态矛盾 | Supervisor 核实并沿 `$slk-overwatch-run` / `$slk-manage-temporal` 修复；保障恢复前不派下一 CELL。 |
| 需暂停、重配置或处理半提交恢复 | `$slk-pause-run`；REQUESTED≠PAUSED，保留精确在途 operation，从已完成部分之后续做。已有最终结论后的收尾半提交用 `$slk-finalize-run`。 |
| 首次/中途更换后的组件、配置、登记、理解或就绪缺项 | `$slk-troubleshoot-preflight`；看当前准备操作，不因已有 Run 就当施工消息故障。 |

## 权限与返回

预案是建议。Supervisor 可按真实证据选择、组合、改变或跳过；未收录的新问题继续定位，不被案例清单阻断。正常通讯仍由原发送者/接收者完成；OW 只写自己的观察并向所属主管报告后继续巡查，不代发、重试、恢复、改工程事实/BI/TOKEN。

原责任角色执行既有权限内动作，Supervisor 处理可逆工具/环境/保障故障；新增范围、费用、账号、破坏性改变、模型或主管权限仍由 Owner 决定。修复后仅核实受影响条件及实际结果，写明原因、动作、原件路径与未解决项，回到原节点/operation；不重复准备、施工或 D0/D1/D2。经验经验证后再维护，不把猜测/偶发问题推广成全局限制，不加统一时限、材料上限、监控器或 daemon。
