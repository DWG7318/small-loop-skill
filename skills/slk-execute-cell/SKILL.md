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
3. 选择最低 D0，为交付提供基本信心，例如目标测试、构建或直接 smoke。D0 的规模与本次变化和风险相称。
4. 汇总候选身份、实际变化、D0 命令与结果、未覆盖风险和建议的 Checker 关注点。
5. 把自己的施工事实写入根记录，作为本轮工作的倒数第二项，建议调用 `$slk-record-run`。
6. 把候选发送给 Checker 作为最后一项，使用类似格式：`已完成，请检验：CELL n/N`。随后结束本轮 Worker 工作。

## Checker 未被激活时

先查看目标对话状态和消息是否可见。通常可以进行三次不同方式的唤醒尝试；每次都保留原 CELL、候选和进度信息。仍不清楚时，建议调用 `$slk-recover-communication`，由 Supervisor 协助恢复 Checker 通道。

## 完成后

Checker 使用 `$slk-check-cell` 对同一候选执行隔离 D1。

