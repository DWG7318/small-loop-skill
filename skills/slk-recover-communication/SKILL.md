---
name: slk-recover-communication
description: Use when an SLK delivery, activation, or reply between visible members is missing or unclear.
---

# Recover SLK Communication

## 当前目标

使用真实的对话激活操作恢复原成员通道，并让 Run 回到中断前的工作节点。

## 真实激活与接收证据

1. 确认准确的 Checker 任务 ID，并调用当前平台能够继续该对话的真实激活操作；Codex Desktop 使用 `send_message_to_thread`。读取或写入后台聊天记录只说明记录存在，不作为激活。
2. 激活内容保留同一份完整原始交付，包括 Run、GO、`CELL n/N`、候选身份和必要入口。
3. Checker 对当前 CELL 的明确回执，或者本次激活后新产生且对应当前 CELL 的工作状态变化，才构成接收证据。激活调用成功本身不等于已经接收。
4. 建议使用约两分钟的有界确认窗口；没有收到接收证据时，Worker 通过同样的真实激活操作把原始交付、Checker任务ID和调用结果交给 Supervisor。

应急路径保持为：

```text
Worker → Supervisor → Checker
```

## Supervisor 恢复原 Checker

缺少回执不等于 Checker 失效。Supervisor 核对准确任务 ID、平台状态和真实激活调用结果，优先恢复原 Checker，并再次向原任务 ID 发送完整交付。D1 仍由 Checker 完成。

Supervisor 发送一份干净的 D1 恢复信封，不重新解释工程内容：

```text
恢复原 Checker 任务，不是新 CELL，也不改变原 D1 目标。

收到后请先回复：
已收到，开始检查：CELL n/N

Run：<RUN-ID>
GO：<GO-ID>
CELL：n/N
Worker 任务 ID：<WORKER-THREAD-ID>
根记录：<SLK-RUN文件绝对路径>

以下是 Worker 原始 D1 交付原文，请按原内容继续：
<Worker 原始 D1 交付原文>
```

Worker 原始 D1 交付沿用 `$slk-execute-cell` 的干净输入：CELL与D1目标、候选身份和位置、客观变更范围、运行候选所需事实及回复目标。Supervisor 不加入 D0 结果、Worker 判断过程、建议关注点、返工历史或 Supervisor 自己的结论。通讯故障过程写入根记录，不进入恢复信封。

Checker 回复 `已收到，开始检查：CELL n/N` 后，通讯恢复即完成。Checker 独立执行 D1，再按 `Checker → Worker` 返回 D1 结果；Supervisor 结束本次激活，不等待或参与 D1。

创建接管 Checker 属于极端恢复。只有任务 ID 不存在、平台明确显示任务失败或取消且无法继续，或者真实激活操作明确返回该任务不可用时，才把原 Checker 视为明确失效，并调用 `$slk-manage-team` 建立接管 Checker。

如果平台整体缺少可用的真实激活操作，保留原 Checker 和通讯故障事实；后台聊天记录不用于假装恢复，也不凭缺少回执创建接管成员。

## 成员恢复

明确失效后调用 `$slk-manage-team`。接管 Checker 读取根记录和当前候选，再与 Supervisor、Worker 完成双向通讯测试。

## 完成后

在根记录追加通讯情况、尝试方式、恢复成员和实际结果。通道恢复后回到原来的派发、施工、D1或D2节点；若本次激活了 Supervisor，恢复完成后由其交还 Checker并结束本次激活。
