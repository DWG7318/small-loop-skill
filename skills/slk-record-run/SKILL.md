---
name: slk-record-run
description: Use when an active Small Loop Skill (SLK) Run needs its root record initialized or a member is preserving work and handoff facts.
---

# Record an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

在项目根目录维护一份可读、可追查的 `SLK-RUN-<RUN-ID>.md`，让接管成员和 Owner 理解已经做了什么、检查了什么、出现过什么问题以及下一步在哪里。

通过 Grill 后，Supervisor 可以从 `assets/SLK-RUN.template.md` 创建记录，写入 Run 定义、计划、方法版本和自己的任务 ID，再使用 `$slk-manage-team` 建立后续成员。即使成员在其他 worktree 施工，三个角色仍指向同一个根记录绝对路径。

## 各角色写自己的事实

- Worker 记录施工变化、候选、最低 D0、判断过程、风险和交付对象。
- Checker 记录 D1 方法、结果、错误、返工建议、CELL 与 GO 进度，以及从实际工作中得到的 CELL 容量事实。
- Supervisor 仅在被激活时记录启动交接、本次调整、豁免、成员恢复、D2、归档或最终结论，不接管日常进度记录。

各自完成自己的记录，减少由其他角色补写造成的遗漏或推测。

记录采用角色分区。Checker 在 D1 前使用原始 CELL 定义和候选，延后读取 Worker 的 D0、判断与建议；独立 D1 判断形成后，再核对 Worker 分区。D2 交接也先给 Supervisor 原始 Run/GO 目标、最终候选和端到端入口，详细施工历史随后核对。

## 建议记录方式

- 当前进度和当前 CELL 可以更新为最新状态。
- CELL 历史、错误、失败尝试、返工、豁免和重要决定采用追加记录；后来的通过结论保留前面的真实过程。
- 命令和结果保留简洁摘要。重要且难以重现的原始证据可以记录路径、提交、候选或哈希。
- 记录保持工程上足够完整，不复制全部聊天和大体积原始日志。

## 工作顺序

每次角色行动的倒数第二项建议写入自己的记录，最后一项把结果传输给下一对话。完成传输后结束本轮工作。
