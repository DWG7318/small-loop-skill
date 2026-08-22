---
name: slk-close-run
description: Use when all planned SLK CELLs are accounted for and the Supervisor is ready for D2 and Run closure.
---

# Close an SLK Run

## 当前目标

Supervisor 判断全部成果合起来是否正确。通过后完成记录、成员归档和 Owner 结论；发现组合问题时，把工作送回最近的正常节点。

## Supervisor D2

建议集中检查：

1. 全部 CELL 都有当前 D1 结果，豁免项目单独列出；
2. 每个 GO 产生了约定结果；
3. GO 与 CELL 之间的衔接符合实际工作流；
4. 主要端到端路径可以运行或得到足够证明；
5. 关键风险、相关回归、副作用和剩余限制已经说明；
6. 最终候选与根记录中的结果一致。

D2 复用已有 D0、D1 证据，重点增加组合、衔接和 Run 风险检查，减少逐项重复 D1。

## D2 发现问题

Supervisor 描述组合问题和受影响范围，建议调用 `$slk-adjust-run` 选择相关 CELL。修复路径回到：

```text
Checker → Worker → Checker
```

相关 D1 更新后，Supervisor 再检查受影响的 D2 部分。

## D2 通过后的收尾

1. 调用 `$slk-record-run` 汇总最终 CELL 数、D0结果、D1通过数、Supervisor豁免数、D2结论、限制和证据位置。
2. 调用 `$slk-manage-team`，建议依次归档 Worker、归档 Checker，并保留 Supervisor 对话。
3. 向 Owner 发送一个简洁结论，例如：Run 已完工，D0/D1/D2结果、豁免数量、已知限制和根记录路径。

Owner 可以根据结论继续查询；Supervisor 保留完整工程上下文供后续说明。
