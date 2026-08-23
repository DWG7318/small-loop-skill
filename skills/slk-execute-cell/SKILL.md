---
name: slk-execute-cell
description: Use when the SLK Worker has received one CELL and is ready to implement, self-check, record, and deliver it.
---

# Execute a CELL

## 当前目标

Worker 完成当前 CELL，形成可检查候选，并把 Checker 需要的信息清楚交付出去。

## 建议做法

1. 重新确认 `CELL n/N`、目标、范围、D1 验收目标和当前候选基线。
2. 在约定范围内施工。新的发现可以记录下来；明显影响当前目标时，先请 Checker 澄清或由其联系 Supervisor。
3. 选择最低 D0，为 Worker 自己的交付提供基本信心，例如目标测试、构建或直接 smoke。D0 的规模与本次变化和风险相称。
4. 把实际变化、D0 命令与结果、判断过程和未覆盖风险写入根记录的 Worker 分区，作为本轮工作的倒数第二项，建议调用 `$slk-record-run`。
5. 初始 D1 交付只包含 `CELL n/N`、候选身份与访问位置、客观变更范围和运行候选所需的必要事实。D0 结果、判断过程和建议关注点不进入初始 D1 交付。
6. 把候选发送给 Checker 作为最后一项，使用类似格式：`已完成，请检验：CELL n/N`。发送采用能够真实激活目标对话的操作，并等待 Checker 对当前 CELL 的明确回执；得到回执后结束本轮 Worker 工作。

## Checker 未被激活时

在 Codex Desktop 中，使用 `send_message_to_thread` 这类会继续目标对话的真实激活操作，而不是只把文字写入后台聊天记录。建议用约两分钟的有界窗口等待明确回执或本次激活后的 Checker 状态变化；调用成功本身不等于 Checker 已经接收。窗口内没有当前 CELL 的接收证据时，调用 `$slk-recover-communication`，通过 Supervisor 优先恢复原 Checker。

## 完成后

Checker 使用 `$slk-check-cell` 对同一候选执行隔离 D1。
