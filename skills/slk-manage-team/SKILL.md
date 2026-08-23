---
name: slk-manage-team
description: Use when an SLK Run is establishing, recovering, replacing, or archiving its visible project conversations.
---

# Manage the SLK Team

## 当前目标

让 Supervisor、Checker、Worker 以项目中的可见对话存在，并在建立、接管和归档时保持清楚的任务 ID、关系和状态。

## 建立成员组

推荐的创建关系是一条向下交接链。原对话创建 Supervisor；Supervisor 接管后的后续顺序如下。

`$slk-plan-run` 已完成原对话 ↔ Supervisor 通讯测试时，任务 ID 与通道没有变化就复用已记录结果，不重复测试。接着建议按顺序进行：

1. Supervisor 创建 Checker，并确认它是项目任务列表中的可见对话；
2. 完成 Supervisor ↔ Checker 的双向通讯测试；
3. 做一次 Checker 理解确认，让 Checker 用当前 Run 说明日常 CELL 派发、D1 隔离、CELL 一分为二、返工和激活 Supervisor 的边界；回答模糊时先解释再确认；
4. Checker 创建 Worker，并确认它是项目任务列表中的可见对话；
5. 完成 Checker ↔ Worker 的双向通讯测试；
6. 完成 Supervisor ↔ Worker 的应急通道测试。

相邻通道服务于正常工作，Supervisor ↔ Worker 在 Checker 通讯异常时协助恢复。成员创建以项目任务列表中的可见对象、准确任务 ID 和真实回复为依据。Worker 不重复完整方法问答；Checker 创建 Worker 时只交付其施工、最低 D0、记录和回传所需规则。

正式成员对应项目任务列表中的可见对话，Owner 能够看到并联系。内部 subagent、隐藏执行或文字中的角色声明不作为正式成员，也不替代上述创建关系与通讯测试。

成员组与通讯通道建立后，Supervisor 把日常 CELL 循环交给 Checker，通常转为非活动状态，不在线等待或接收逐 CELL 汇报。需要上级协助或最终 D2 时，再由 Checker 或应急路径激活。

## 恢复或接管

成员发生问题时，通常由上一级成员优先恢复原成员。缺少回执不等于失效；创建接管成员属于确认原成员明确失效后的极端恢复：

- Worker 异常时，由 Checker 先恢复原 Worker，明确失效后再安排接管 Worker；
- Checker 异常时，由 Supervisor 先恢复原 Checker，明确失效后再安排接管 Checker；
- Supervisor 异常时，由原对话联系 Owner 并优先恢复原 Supervisor，明确失效后再协助建立接管 Supervisor。

明确失效可以依据任务 ID 不存在、平台显示失败或取消且无法继续，或者真实激活操作明确返回任务不可用。暂时没有回复不作为更换成员的依据。

接管成员可以先读取根 Run 记录、当前计划、候选和未完成交接，再进行双向通讯测试。接管确认后，把旧成员的实际状态写入记录。

## 收尾归档

D2 通过且最终记录完整后，建议先归档 Worker，再归档 Checker。归档结果结合准确任务 ID 和任务状态确认。Supervisor 继续保留，方便 Owner 后续查询。

## 完成后

建立或恢复完成后，日常工作回到 Checker 与 Worker 的中断前节点，Supervisor 结束本次激活；收尾归档完成后，把结果交还 `$slk-close-run`。
