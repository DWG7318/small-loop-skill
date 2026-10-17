---
name: slk-manage-team
description: Use when an active Small Loop Skill (SLK) Run is establishing, observing, recovering, replacing, or archiving its visible project conversations.
---

# Manage the SLK Team

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

让 Supervisor、Checker、Worker 以项目中的可见对话存在，并在建立、接管和归档时保持清楚的任务 ID、关系和状态。

职责不绑定 Agent 品牌；按 Owner 确认的实际 Agent、模型和平台能力建立成员与真实通道。平台缺少可信身份、原生消息或归档能力时如实说明相应限制，不以同名或文字声明冒充可见成员或已完成操作。

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

成员组与通讯通道建立后，Supervisor 用首枚 `SLK TOKEN T001` 把第一个待派发 CELL 和日常循环交给 Checker。Worker 与 Checker 完成自己当前 Loop 节点和必要交接后结束当前活动，接收令牌本身不结束受领工作，也不另增回执轮次；两者不使用`wait_threads`、不读取彼此施工过程，下一条真实消息按需激活。Supervisor 交接后继续在线，不要求逐 CELL 额外汇报。

## Supervisor 低 Token 观察

用平台原生等待接收事件或精简状态，如 Codex 的 `wait_threads`；复用游标只取新增变化，等待返回后继续等待，不因本轮正常而退出。先看准确任务 ID、当前 TOKEN、活动回合状态和最近客观交付，出现矛盾才定向读取必要片段；不反复展开完整聊天、日志或成员推理，不把观察变成 D1/D2 预判。频率随现场选择，不设统一分钟数或无输出次数门槛。

成员已结束、失败或遇到平台容量终止，但当前节点没有候选/结论、后继令牌或阻碍交接时，使用 `$slk-recover-communication` 现场恢复并记录；仍在运行的长任务不因暂时无输出而重派或判为失败。Supervisor 是现场排障、补漏和记录的主要负责人，在既有授权内直接处理，不把恢复推给方法源码升级；超出已有资源或 Owner 决策边界时才请求对应授权。

## 恢复或接管

成员发生问题时，通常由上一级成员优先恢复原成员。缺少回执不等于失效；创建接管成员属于确认原成员明确失效后的极端恢复：

- Worker 异常时，由 Checker 先恢复原 Worker；Supervisor 发现静默停点或接到求助时可现场接手，但先明确唯一恢复发送者，原发送者停止自行重试并交代已发/待处理消息；明确失效后再安排接管 Worker；
- Checker 异常时，由 Supervisor 先恢复原 Checker，明确失效后再安排接管 Checker；
- Supervisor 异常时，由原对话联系 Owner 并优先恢复原 Supervisor，明确失效后再协助建立接管 Supervisor。

明确失效可以依据任务 ID 不存在、平台显示失败或取消且无法继续，或者真实激活操作明确返回任务不可用。暂时没有回复不作为更换成员的依据。

接管成员可以先读取根 Run 记录、当前计划、候选和未完成交接，再进行双向通讯测试。恢复原成员所持未完工程节点时重发原令牌编号；接管持有工程责任的新成员确认后，上一级用递增编号把当前节点交给新任务 ID，使旧令牌失效，并把旧成员的实际状态写入记录。

Supervisor 只在旁观时终止，由原对话恢复其观察活动，附当前 Run 与记录位置，不重放历史交出令牌，也不夺取 Worker/Checker 的当前令牌。Supervisor 确实持有调整/D2 节点时才恢复该当前令牌；更换仅观察的 Supervisor 同样只更新成员身份与通道，不制造工程流转。

## 收尾归档

已有真实 D2 或授权终止结果时，转到 `$slk-finalize-run` 处理剩余收尾；成员管理不再重复归档清单。

## 完成后

建立或恢复完成后，日常工作回到 Checker 与 Worker 的中断前节点，Supervisor 继续低 Token 观察。Run 正式收尾或 Owner 明确停止后才结束持续观察。

## 负面提示词

- 不要把内部 subagent 或文字中的角色当成项目可见成员；不要只凭发出操作便声称创建、恢复或归档已完成；不要凭暂时无回复更换成员，或把 completed/error=null 当成工程完成；不要用反复读取完整施工日志代替低 Token 观察。
