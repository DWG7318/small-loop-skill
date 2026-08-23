---
name: small-loop-skill
description: Use when one bounded engineering Run has a single serial GO and CELL path suited to SLK.
---

# Small Loop Skill

## 方法身份

SLK 是 Loop Engineering 的线性形态，面向中小型工程或大型工程中相对独立的中小范围；一个 SLK 对应一个 Run，GO 与 CELL 沿一条线性路径推进。

它以 CELL Loop 重复派发、施工与 D0、候选交付、隔离 D1，帮助成员判断怎样继续：D1 FAIL 回到同一 CELL 返工，D1 PASS 前进，全部 CELL 处理后由 D2 闭合 Run。

## 可见成员

- Supervisor 在启动、上级协助、豁免和 D2 等边界按需激活。
- Checker 负责日常 CELL 推进：向 Worker 派发、直接协作并在隔离状态下执行 D1。
- Worker 完成当前 CELL，并在交付前执行最低程度 D0。

D0 提供交付前基本信心，D1 判断 CELL 是否达到约定目标，D2 判断全部成果合起来是否正确。

原对话与 Owner 选择 SLK，并明确 Run 目标、边界和 Owner 关心的结果。Agent 在创建 Supervisor 前结合项目整理 Run、GO、初始 CELL 与分层检查方案。Supervisor 接管后，原对话退出工程工作，继续保留 Owner 联系和 Supervisor 异常恢复入口。

Supervisor 通过理解确认后，先在项目根目录创建 `SLK-RUN-<RUN-ID>.md`。随后按 Supervisor 创建 Checker，Checker 创建 Worker 的关系建立成员；在 Worker 创建前完成 Checker 职责理解确认。通讯测试完成后，角色完成自己当前 Loop 节点和必要交接才结束当前活动；接收回执不等于节点完成。成员不使用`wait_threads`或读取其他成员施工状态，下一条真实消息重新激活对应角色。Checker 与 Worker 继续线性循环，异常、重要计划变化、豁免和最终 D2 交接再激活 Supervisor。

## 按当前情境选择指导

- 新 Run、GO 与初始 CELL 方案：`$slk-plan-run`
- Supervisor、Checker、Worker 的模型能力选择：`$slk-select-models`
- Supervisor 开工前理解确认：`$slk-grill-supervisor`
- 建立、恢复、更换或归档成员：`$slk-manage-team`
- Checker 派发前校准并交付既定 CELL：`$slk-dispatch-cell`
- Worker 施工与最低 D0：`$slk-execute-cell`
- Checker 隔离执行 D1：`$slk-check-cell`
- 各成员写入共享 Run 记录：`$slk-record-run`
- D1 未通过后的普通返工：`$slk-rework-cell`
- Supervisor 处理升级决策、返工路线、能力安排、Owner 授权建议或豁免：`$slk-adjust-run`
- Worker 向 Checker 交付后缺少当前 CELL 的接收证据：`$slk-recover-communication`
- 所有计划 CELL 明确处理后的 D2、归档和 Owner 结论：`$slk-close-run`

通常读取当前情境对应的指导即可；新的情况出现时，再补充相关 Skill。
