---
name: slk-manage-team
description: Use when an SLK Run is establishing, recovering, replacing, or archiving its visible project conversations.
---

# Manage the SLK Team

## 当前目标

让 Supervisor、Checker、Worker 以项目中的可见对话存在，并在建立、接管和归档时保持清楚的任务 ID、关系和状态。

## 建立成员组

推荐的创建关系是：原对话创建 Supervisor，Supervisor 创建 Checker，Checker 创建 Worker。

每创建下一级成员，建议立即做一次不含工程工作的双向通讯测试，并记录任务 ID 和实际状态：

1. 原对话 ↔ Supervisor；
2. Supervisor ↔ Checker；
3. Checker ↔ Worker；
4. Supervisor ↔ Worker 的应急通道。

前三条服务于正常工作，第四条在 Checker 通讯异常时协助恢复。成员创建以项目任务列表中的可见对象、准确任务 ID 和真实回复为依据。

成员组与通讯通道建立后，Supervisor 把日常 CELL 循环交给 Checker，通常转为非活动状态，不在线等待或接收逐 CELL 汇报。需要上级协助或最终 D2 时，再由 Checker 或应急路径激活。

## 恢复或接管

成员发生问题时，通常由上一级成员先恢复原对话，或者创建一个接管成员：

- Worker 异常时，由 Checker 协助恢复或安排新 Worker；
- Checker 异常时，由 Supervisor 协助恢复或安排新 Checker；
- Supervisor 异常时，由原对话联系 Owner 并协助建立接管 Supervisor。

接管成员可以先读取根 Run 记录、当前计划、候选和未完成交接，再进行双向通讯测试。接管确认后，把旧成员的实际状态写入记录。

## 收尾归档

D2 通过且最终记录完整后，建议先归档 Worker，再归档 Checker。归档结果结合准确任务 ID 和任务状态确认。Supervisor 继续保留，方便 Owner 后续查询。

## 完成后

建立或恢复完成后，日常工作回到 Checker 与 Worker 的中断前节点，Supervisor 结束本次激活；收尾归档完成后，把结果交还 `$slk-close-run`。
