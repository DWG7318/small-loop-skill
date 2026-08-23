---
name: slk-close-run
description: Use when all planned SLK CELLs are accounted for and the Supervisor is ready for D2 and Run closure.
---

# Close an SLK Run

## 当前目标

所有计划 CELL 都有明确处理结果后，Supervisor 判断全部成果合起来是否正确。通过后完成记录、成员归档和 Owner 结论；发现组合问题时，把工作送回最近的正常节点。

## 激活与 D2 交接

所有计划 CELL 都有明确处理结果后，Checker 用一条 D2 交接激活 Supervisor。每个 CELL 的结果是 `D1 PASS` 或 `Supervisor 豁免`；两者分别记录，不把豁免改写为完成。初始交接聚焦原始 Run/GO 目标、最终候选、端到端入口和必要的客观环境信息，不先展开 Worker 判断与详细 D1 历史。

## 检查对象隔离

1. Supervisor 先从 Run 目标、GO 结果、最终候选和端到端入口开始，检查真实组合结果。
2. 集中检查 GO 与 CELL 的衔接、主要端到端路径、关键风险、相关回归、副作用和剩余限制。
3. 形成初步 D2 判断后，随后读取详细 D1 记录、D0、返工、豁免和证据位置，核对 CELL 是否完整、是否出现遗漏事实以及记录是否与候选一致。
4. D1 PASS 不作为 D2 通过证明；它只说明单个 CELL 的 D1 结果。D2 结论仍由组合、衔接和端到端证据支持。

建议最终核对：

1. 所有计划 CELL 都有明确处理结果：当前 D1 结果或单独列出的 Supervisor 豁免；
2. 每个 GO 产生了约定结果；
3. GO 与 CELL 之间的衔接符合实际工作流；
4. 主要端到端路径可以运行或得到足够证明；
5. 关键风险、相关回归、副作用和剩余限制已经说明；
6. 最终候选与根记录中的结果一致。

D2 可以复用客观证据，但不复用 D0、D1 的通过结论；重点仍是组合、衔接和 Run 风险，减少逐项重复 D1。

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

Owner 可以根据结论继续查询；Supervisor 保留最终交接、D2结论和根记录路径，需要时再查阅详细工程历史。
