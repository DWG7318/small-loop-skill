---
name: small-loop-skill
description: Use when one bounded engineering Run has a single serial CELL path suited to SLK.
---

# Small Loop Skill

## 方法身份

SLK 是 Loop Engineering 的线性形态，面向中小型工程或大型工程中相对独立的中小范围；一个 SLK 对应一个 Run，Run 直接包含线性 CELL 路径。

它以 CELL Loop 重复派发、施工与 D0、候选交付、隔离 D1，帮助成员判断怎样继续：D1 FAIL 回到同一 CELL 返工，D1 PASS 前进，全部 CELL 处理后由 D2 闭合 Run。进入施工后的一个 Run 同时只有一个当前有效的 `SLK TOKEN`；令牌本身不是新文件、角色、审批或外部状态系统，只在既有 Loop 节点边界流转，携带令牌编号、Run、CELL、当前节点、接收者、候选（如有）、下一动作和根记录路径；中央 SQLite 保存状态事实，`slk-state` 供三个角色按职责写入，`slk-bi-query` 供 Owner、其他 Agent 与未来 BI 只读查询。

## 成员与运行时

- Supervisor 在启动、上级协助、豁免和 D2 等边界按需激活。
- Checker 负责日常 CELL 推进：向 Worker 派发、直接协作并在隔离状态下执行 D1。
- Worker 完成当前 CELL，并在交付前执行最低程度 D0。

D0 提供交付前基本信心，D1 判断 CELL 是否达到约定目标，D2 判断全部成果合起来是否正确。

原对话与 Owner 选择 SLK，并明确 Run 目标、边界和 Owner 关心的结果。Agent 在创建 Supervisor 前结合项目整理 Run、初始 CELL 与分层检查方案。Supervisor 接管后，原对话退出工程工作，继续保留 Owner 联系和 Supervisor 异常恢复入口。

Supervisor 通过理解确认后，用 `slk-state init-run` 初始化中央状态与自动生成的 `SLK-RUN-<RUN-ID>.md` 导出。随后按 Supervisor 创建 Checker，Checker 创建 Worker 的关系建立成员；在 Worker 创建前完成 Checker 职责理解确认。通讯测试完成后，Supervisor 用 `T001` 把第一个待派发 CELL 的责任交给 Checker；此后当前持有者在完成既有节点时单调增加编号，并用真实激活操作把完整 `SLK TOKEN` 消息投递到已登记的目标原生 Agent 入口。与消息匹配的原生启动证据才证明该次流转；同一 Run 全部成功流转中编号最大且身份匹配的令牌才是当前事实，并由接收者在该次激活中先登记状态再完成下一节点，不增加令牌专用回执。只有真实投递成功才结束当前活动，操作明确失败时仍持有当前令牌，并以同一拟发送编号、内容和接收者重试。当前令牌只证明当前责任与最后已确认边界，不证明接收者正在实时施工；旧 running 标记、旧进度或持有令牌也不证明活跃。没有后续令牌或结果时只报告“令牌已交给相应角色，后续执行未确认”。成员不使用`wait_threads`或读取其他成员施工状态，下一条真实消息重新激活对应角色；异常、重要计划变化、豁免和最终 D2 交接再激活 Supervisor。跨 Agent 流转时，当前发送者按已登记的精确角色端点调用 `slk-transport send`，由适配器进入目标的原生 Agent 入口；观察到原生启动证据后才用 `slk-state handoff` 推进令牌。数据库记录不等于投递，不按对话标题猜测目标，也不增加确认专用回合。状态与通讯边界见 [`docs/state/SLK-STATE.md`](../../docs/state/SLK-STATE.md) 和 [`docs/transport/SLK-TRANSPORT.md`](../../docs/transport/SLK-TRANSPORT.md)。

## 按当前情境选择指导

- 新 Run 与初始 CELL 方案：`$slk-plan-run`
- Cargo 或其他明显独占资源的隔离与恢复安排：`$slk-guard-resources`
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

## 负面提示词

- 不要把 SLK Run 绑定到任何由单个对话持续工作到底的 Goal 模式，也不要让这类 Goal 驱动或续作 Run；这不限制目标定义，天然冲突来自固定对话与 `SLK TOKEN` 在 Supervisor、Checker、Worker 之间逐节点流转不能同时成为执行主线。
- 不要把针对某个 CELL、某类工作或一次经验形成的容量估计、数字边界或经验规则，泛化为所有 CELL、整个 Run 或其他项目共同遵守的一刀切定额；不要为了平均、整齐或便于管理，要求每个 CELL 满足相同指标。这不排除根据具体 CELL 的目标、难度、依赖、模型、电脑和余量，形成只适用于该 CELL 的、有事实依据的容量边界。
- 不要把 SLK TOKEN、SQLite 或 BI 当成逐条命令队列、运行监视器、裁决者或额外确认层；不要让 Owner、其他 Agent 或 BI 修改状态，也不要让相同或更旧的令牌编号创建新工作、回退指针或重开 CELL，当前同号未完成节点只从已记录边界续做；不要把 Checker 的 D1 交给 Supervisor，把接收令牌或局部结果当成 CELL 完工，把豁免写成 D1 PASS，或用 `wait_threads`、旧状态和读取成员施工状态代替真实交接。
- 不要把零 finding、没有报错或与验收目标无对应关系的一般测试通过直接等同于 D1 PASS，也不要用 Supervisor 后补证据替代 Checker 的 D1；不要把候选可能正确、D1 已通过和 D2/Run 已关闭合并成一个结论，或把间接验证写成未实际执行的目标环境验证。
