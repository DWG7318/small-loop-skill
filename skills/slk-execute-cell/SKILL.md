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

1. 重新确认 `CELL n/N`、目标、范围、D1 验收目标和当前候选基线。
2. 在约定范围内施工。新的发现可以记录下来；明显影响当前目标时，先请 Checker 澄清或由其联系 Supervisor。
3. 选择最低 D0，为 Worker 自己的交付提供基本信心，例如目标测试、构建或直接 smoke。D0 的规模与本次变化和风险相称。
4. 把实际变化、D0 命令与结果、判断过程和未覆盖风险写入根记录的 Worker 分区，作为本轮工作的倒数第二项，建议调用 `$slk-record-run`。
5. 初始 D1 交付只包含 `CELL n/N`、候选身份与访问位置、客观变更范围和运行候选所需的必要事实。D0 结果、判断过程和建议关注点不进入初始 D1 交付。
6. 把候选发送给 Checker 作为最后一项，使用类似格式：`已完成，请检验：CELL n/N`。采用能够真实激活目标对话的操作，发送后结束本轮Worker工作，不使用`wait_threads`也不读取Checker状态；Checker 先用真实消息回复明确回执，该回执异步重新激活Worker并闭合交付。

## Checker 未被激活时

在 Codex Desktop 中，使用 `send_message_to_thread` 这类会继续目标对话的真实激活操作，而不是只把文字写入后台聊天记录。Worker 发送后结束当前活动，不继续停留或读取 Checker 状态；Checker 收到后先用真实消息回执。平台明确返回不可用，或 Worker 后来被其他真实消息重新激活仍未见当前 CELL 回执时，调用 `$slk-recover-communication`，通过 Supervisor 优先恢复原 Checker。

## 完成后

Checker 使用 `$slk-check-cell` 对同一候选执行隔离 D1。
