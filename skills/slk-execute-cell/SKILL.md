---
name: slk-execute-cell
description: Use when an active Small Loop Skill (SLK) Run has a Worker ready to implement one received CELL.
---

# Execute a CELL

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

Worker 完成当前 CELL，形成可检查候选，并把 Checker 需要的信息清楚交付出去。

## 建议做法

1. 重新确认当前 `SLK TOKEN` 的 `CELL n/N`、目标、范围、D1 验收目标和候选基线；接收令牌不结束当前 CELL 施工。收到相同或更旧的令牌编号时，不重开 CELL，只结合根记录和现有候选判断是否需要补交。
2. 在同一次当前 CELL 施工中连续完成所需编辑、工具调用、命令、测试和最低 D0，直到完成整个 CELL 候选；命令、工具结果或中间进展不构成 CELL 交付边界，也不要求 Worker 结束。新的发现明显影响当前目标时，才请 Checker 澄清或由其联系 Supervisor。
   Owner 已为本次 Run 启用效率工具时，Worker 可先用 Probe CLI 定位再精准读取，用 RTK 获取测试、构建或 Git 输出的低噪声首轮结果，并在适用时遵循 Ponytail 减少过度施工；完整原始输出仍应可追溯，出现失败、截断、疑义或需要核心代码事实时，读取保留原文或回退原生命令。
3. 选择最低 D0，为 Worker 自己的交付提供基本信心，例如目标测试、构建或直接 smoke。建议围绕本次变化和风险选择低成本检查，不提前重复 D1/D2 的完整验收。
4. 把实际变化、D0 命令与结果、判断过程和未覆盖风险写入根记录的 Worker 分区，作为本轮工作的倒数第二项，建议调用 `$slk-record-run`。
5. 初始 D1 交付的业务载荷只包含 `CELL n/N`、候选身份与访问位置、客观变更范围和运行候选所需的必要事实，此外保留主 Skill 定义的统一令牌头。D0 结果、判断过程和建议关注点不进入初始 D1 交付。
6. 作为最后一项，通过 `Worker → Checker` 把候选作为下一编号的 `SLK TOKEN` 发送给 Checker，使用类似格式：`已完成，请检验：CELL n/N`。采用能够真实激活目标对话的操作，按已登记的 Checker 精确角色端点调用 `slk-transport send`；观察到原生 Agent 启动证据才视为发送成功，发送后结束本轮Worker工作，不使用`wait_threads`也不读取Checker状态；令牌到达即开始 D1，不增加接收回执轮次。

## Checker 未被激活时

跨 Agent 交付由 `slk-transport` 进入 Checker 的原生 Agent 入口，而不是只把文字写入后台聊天记录或按标题寻找对话。Worker 在启动证据成立后结束当前活动，不继续停留或读取 Checker 状态；平台明确返回未启动、目标不可用或投递失败时，调用 `$slk-recover-communication`，通过 Supervisor 优先恢复原 Checker。

## 完成后

Checker 使用 `$slk-check-cell` 对同一候选执行隔离 D1。

## 负面提示词

- 不要以接收令牌、单条命令结束或中间结果代替完整 CELL 候选交付，也不要重复执行相同令牌或自行进入未派发 CELL；不要提前把完整 D1/D2 当成 D0，也不要把 D0 结论或判断过程塞入初始 D1 交付；不要在交付后等待或读取 Checker 检查过程。
