---
name: slk-record-run
description: Use when an SLK member is finishing a work action and needs to preserve progress, evidence, errors, rework, or handoff facts.
---

# Record an SLK Run

## 当前目标

在项目根目录维护一份可读、可追查的 `SLK-RUN-<RUN-ID>.md`，让接管成员和 Owner 理解已经做了什么、检查了什么、出现过什么问题以及下一步在哪里。

Supervisor 可以从 `assets/SLK-RUN.template.md` 创建记录。即使成员在其他 worktree 施工，三个角色仍指向同一个根记录绝对路径。

## 各角色写自己的事实

- Worker 记录施工变化、候选、最低 D0、风险和交付对象。
- Checker 记录 D1 方法、结果、错误、返工建议、进度和从实际工作中得到的 CELL 容量事实。
- Supervisor 记录计划变化、GO 进展、豁免、D2、成员接管、归档和最终结论。

各自完成自己的记录，减少由其他角色补写造成的遗漏或推测。

## 建议记录方式

- 当前进度和当前 CELL 可以更新为最新状态。
- CELL 历史、错误、失败尝试、返工、豁免和重要决定采用追加记录；后来的通过结论保留前面的真实过程。
- 命令和结果保留简洁摘要。重要且难以重现的原始证据可以记录路径、提交、候选或哈希。
- 记录保持工程上足够完整，不复制全部聊天和大体积原始日志。

## 工作顺序

每次角色行动的倒数第二项建议写入自己的记录，最后一项把结果传输给下一对话。完成传输后结束本轮工作。
