---
name: slk-recover-communication
description: Use when an active Small Loop Skill (SLK) Run has a Worker candidate token that was not truly delivered to its Checker.
---

# Recover SLK Communication

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

使用真实的对话激活操作恢复当前 `SLK TOKEN` 的交付通道，并让同一 CELL 回到原定节点。

## 真实激活与接收证据

1. 确认准确的目标任务 ID 与原令牌编号，并调用当前平台能够继续该对话的真实激活操作；Codex Desktop 使用 `send_message_to_thread`。读取或写入后台聊天记录只说明记录存在，不作为激活。
2. 重发同一份完整原始令牌，包括 Run、GO、`CELL n/N`、当前节点、接收者、候选身份、下一动作和根记录路径；恢复投递沿用原令牌编号，避免把重试变成新工作。
3. 可见目标对话中出现该令牌消息才构成流转证据；任务状态、旧 running 标记或后台记录都不证明投递，也不追加令牌专用回执。
4. 发送后结束当前活动；平台明确返回不可用、消息未创建或投递失败时，再用真实激活操作把当前持有令牌、未投递的完整下一令牌、目标任务ID和调用结果装入通讯异常信封交给 Supervisor。恢复信封不是令牌所有权转移，Supervisor 不登记为当前持有者。

恢复消息路径保持为，令牌在 Checker 收到前仍由原成员持有：

```text
Worker → Supervisor → Checker
```

## Supervisor 恢复原 Checker

令牌未真实投递不等于 Checker 失效。Supervisor 核对准确任务 ID、平台状态和真实激活调用结果，优先恢复原 Checker，并向原任务 ID 重发同号的未投递令牌；成功后由 Checker 登记流转，D1 仍由 Checker 完成。

Supervisor 发送一份干净的 D1 恢复信封，不重新解释工程内容：

```text
恢复原 Checker 任务，不是新 CELL，也不改变原 D1 目标。

收到该令牌后，请在本次激活中直接开始：
检查 CELL n/N

Run：<RUN-ID>；当前持有令牌：<Tnnn>；未投递令牌：<Tnnn+1>
GO：<GO-ID>
CELL：n/N
Worker 任务 ID：<WORKER-THREAD-ID>
根记录：<SLK-RUN文件绝对路径>

以下是 Worker 原始 D1 交付原文，请按原内容继续：
<Worker 原始 D1 交付原文>
```

Worker 原始 D1 交付沿用 `$slk-execute-cell` 的干净输入：CELL与D1目标、候选身份和位置、客观变更范围、运行候选所需事实及回复目标。Supervisor 不加入 D0 结果、Worker 判断过程、建议关注点、返工历史或 Supervisor 自己的结论。通讯故障过程写入根记录，不进入恢复信封。

原令牌在可见 Checker 对话真实出现后，通讯恢复即完成。Checker 在该次激活中独立执行 D1，再按 `Checker → Worker` 返回 D1 结果；Supervisor 结束本次激活，不读取Checker的D1过程。

创建接管 Checker 属于极端恢复。只有任务 ID 不存在、平台明确显示任务失败或取消且无法继续，或者真实激活操作明确返回该任务不可用时，才把原 Checker 视为明确失效，并调用 `$slk-manage-team` 建立接管 Checker。

如果平台整体缺少可用的真实激活操作，保留原 Checker 和通讯故障事实；后台聊天记录不用于假装恢复，也不凭投递失败创建接管成员。

## 成员恢复

明确失效后调用 `$slk-manage-team`。接管 Checker 读取根记录和当前候选，再与 Supervisor、Worker 完成双向通讯测试。

## 完成后

在根记录追加原令牌编号、通讯情况、尝试方式、恢复成员和实际结果。通道恢复后回到同一 CELL 的原定节点；若本次激活了 Supervisor，恢复完成后由其交还 Checker并结束本次激活。
