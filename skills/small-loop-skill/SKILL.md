---
name: small-loop-skill
description: Use when one bounded engineering Run has a single serial GO and CELL path suited to SLK.
---

# Small Loop Skill

## 方法身份

SLK 面向中小型工程，或大型工程中相对独立的中小范围。一个 SLK 对应一个 Run，GO 与 CELL 沿一条线性路径推进。

SLK 帮助成员决定怎样继续推进 Run；遇到偏差时，优先寻找恢复、调整或上级协助路径。

## 可见成员

- Supervisor 在启动、上级协助、豁免和 D2 等边界按需激活。
- Checker 负责日常 CELL 推进：向 Worker 派发、直接协作并在隔离状态下执行 D1。
- Worker 完成当前 CELL，并在交付前执行最低程度 D0。

D0 提供交付前基本信心，D1 判断 CELL 是否达到约定目标，D2 判断全部成果合起来是否正确。

原对话与 Owner 选择 SLK，并明确 Run 目标、边界和 Owner 关心的结果。Agent 在创建 Supervisor 前结合项目整理 Run、GO、初始 CELL 与分层检查方案。Supervisor 接管后，原对话退出工程工作，继续保留 Owner 联系和 Supervisor 异常恢复入口。

Supervisor 通过理解确认后，先在项目根目录创建 `SLK-RUN-<RUN-ID>.md`，再建立 Checker 与 Worker。通讯测试完成后，Supervisor 通常转为非活动状态，不在线等待日常 CELL；Checker 与 Worker 继续线性循环。重复返工、成员或通讯异常、重要计划变化、豁免以及最终 D2 交接会再次激活 Supervisor。

## 按当前情境选择指导

- 新 Run、GO 与初始 CELL 方案：`$slk-plan-run`
- Supervisor 开工前理解确认：`$slk-grill-supervisor`
- 建立、恢复、更换或归档成员：`$slk-manage-team`
- Checker 派发前校准并交付既定 CELL：`$slk-dispatch-cell`
- Worker 施工与最低 D0：`$slk-execute-cell`
- Checker 隔离执行 D1：`$slk-check-cell`
- 各成员写入共享 Run 记录：`$slk-record-run`
- D1 未通过后的普通返工：`$slk-rework-cell`
- Supervisor 调整模型、电脑、CELL、路线或豁免安排：`$slk-adjust-run`
- 消息或成员激活状态不清楚：`$slk-recover-communication`
- 全部 CELL 完成后的 D2、归档和 Owner 结论：`$slk-close-run`

通常读取当前情境对应的指导即可；新的情况出现时，再补充相关 Skill。
