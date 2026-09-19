---
name: slk-record-run
description: Use when an active Small Loop Skill (SLK) Run needs its root record initialized or a member is preserving work and handoff facts.
---

# Record an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

在中央 SLK 数据根维护一份可读、可追查的 Run 状态，让接管成员和 Owner 理解已经做了什么、检查了什么、出现过什么问题以及下一步在哪里；SQLite 是状态事实，`SLK-RUN-<RUN-ID>.md` 是自动导出，完整工程历史留在中央状态，令牌只携带当前状态集合与记录指针。

通过 Grill 后，Supervisor 使用 `slk-state init-run` 写入 Run 定义、计划、方法版本、身份和端点，再使用 `$slk-manage-team` 建立后续成员。即使成员在其他 worktree 施工，三个角色仍指向同一中央状态；Checker 在 D1 前使用原始 CELL 定义和候选，依角色分区延后读取 Worker 的 D0、判断与建议，独立 D1 判断后再核对；D2 也先交原始 Run/GO 目标、最终候选与端到端入口，详细历史随后核对。

## 各角色写自己的事实

- Worker 通过 `slk-state` 记录施工变化、资源占用与恢复、候选、最低 D0、判断过程、风险和交付对象；本地 D0 尝试与正式候选、D1 返工分别标明。
- Checker 记录派发、D1 方法与结果、错误、返工建议、CELL 与 GO 进度，以及从实际工作中得到的 CELL 容量事实，并通过 `slk-state` 追加。
- Supervisor 仅在被激活时记录启动交接、计划调整、豁免、成员恢复、D2、归档或最终结论，并通过 `slk-state` 追加；关键失败、重要决定和未执行事项建议在继续调整前及时追加，保留可能被后续操作覆盖的必要证据，交接前补齐，不接管日常进度记录。

## 建议记录方式

- 接收者在令牌激活本轮后的第一步用 `slk-bi-query` 先比较编号与身份；发送者只在原生启动成功后用 `slk-state handoff` 原子推进当前有效令牌和最后真实流转，同号或旧号不改指针，不预写尚未发生的流转。
- CELL 历史、错误、失败尝试、返工、豁免和重要决定采用追加记录；后来的通过结论保留前面的真实过程。
- 命令和结果保留简洁摘要与证据路径、提交或哈希；工具或环境故障与产品缺陷分别记录，保留实际处理和未证明部分。
- 三个角色各自写入自己的事实；Owner、Overwatcher、其他 Agent 和 BI 只通过 `slk-bi-query` 读取。记录保持工程上足够完整，从当前节点与相关条目读取；原始日志按失败定位查阅，不复制整段令牌历史或大日志，也不为检查器反复生成证明材料。

## 工作顺序

每次角色行动的倒数第二项建议用 `slk-state` 写入自己的事实；最后一项完成真实传输并在成功后推进 `SLK TOKEN`。完成传输后结束本轮工作，不跟踪下一对话；Markdown 自动导出失败只形成 warning，可稍后重新生成。

## 负面提示词

- 不要等到最后交接才补写关键失败或重要决定，也不要手工改写自动导出或让三个角色以外的主体写状态；不要把尚未执行的操作写成已经执行失败，不要抹掉错误、返工或豁免历史；不要复制整段令牌历史，也不要把简要记录扩成逐命令审计，不要为了记录而全程盯着成员。
