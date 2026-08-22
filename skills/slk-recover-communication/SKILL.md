---
name: slk-recover-communication
description: Use when an SLK delivery, activation, or reply between visible members is missing or unclear.
---

# Recover SLK Communication

## 当前目标

判断消息处于什么状态，恢复原来的成员通道，并让 Run 回到中断前的工作节点。

## 先看真实状态

- 消息可见且目标对话正在活动：通常表示已经送达并开始处理。
- 消息可见但目标对话空闲：可以发送一条简短激活消息，指向原始交付。
- 消息未出现：重新发送完整原始交付，保留 Run、GO、CELL n/N 和候选信息。
- 目标对话异常或长期无变化：请其上一级成员协助恢复。

Worker 向 Checker 交付后，可以结合对话状态进行三次不同方式的唤醒尝试。尝试之间保留同一原始交付，不逐步缩减任务内容。仍未恢复时，采用应急路径：

```text
Worker → Supervisor → Checker
```

Supervisor 转交原始交付并协助恢复 Checker，D1 仍由 Checker 完成。

## 成员恢复

发现成员本身异常时，建议调用 `$slk-manage-team`。上一级成员可以恢复原成员，或建立接管成员；接管后读取根记录和当前候选，再完成双向通讯测试。

## 完成后

在根记录追加通讯情况、尝试方式、恢复成员和实际结果。通道恢复后回到原来的派发、施工、D1或D2节点。
