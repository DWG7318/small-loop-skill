---
name: slk-recover-communication
description: Use when an active Small Loop Skill (SLK) Run has an undelivered handoff or a Worker or Checker turn that ended before completing its current node.
---

# Recover SLK Communication

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

恢复真实交接或已中断的当前节点，保留原任务、原令牌编号、候选基线和有效修改；不把恢复变成新 CELL、工程验收或方法升级。

## 先区分现场

- **未投递：** 平台明确返回消息未创建、不可用或投递失败。原持有者保留当前令牌，以原拟发送编号重发完整原始令牌；结果不明确时先由 Supervisor 核对目标可见消息，避免重复激活。
- **已投递但未完成：** 目标收到当前令牌后，只 ACK、读文件或部分实现便 completed/error=null，或实际出现失败/容量终止，没有候选、结论或后继交接。由 Supervisor 现场核对后恢复原节点；真实阻碍先解决，不记录成 D1 FAIL。
- **仍在执行或无法确认：** 无新输出不等于停工。先用原生等待/精简状态辨明活动回合与外部任务；旧回合仍 active 时不并发重派，状态未知就记录未确认，不虚构失效。

## 真实恢复动作

回合结束不等于 Cargo、测试或其他外部任务结束。恢复前，Supervisor 按原任务 ID、命令、工作目录与进程/作业归属核对已有外部任务；仍在运行就等待并取得原结果，已结束则取回原结果继续。确需结束遗留任务时，只处理已确认属于本节点且可安全终止的那个任务并记录；不全局结束 Cargo/测试进程。未知状态先查清再重跑可能冲突的命令，不因一次无输出或统一时限重启施工。

1. Supervisor 核对根记录当前摘要、准确任务 ID、最新真实令牌及回合终态，避免拿旧快照重开已交付或 CLOSED 节点。
2. 明确本次唯一恢复发送者；交给 Supervisor 后原发送者停止自行重试，先核对已有投递/排队消息，再使用当前平台能继续原目标对话的真实激活操作，如 Codex Desktop 的 `send_message_to_thread`。后台聊天记录或旧 running 标记不证明恢复。
3. 未投递时沿用原拟发送编号；已收到但未完成时沿用目标当前持有编号，明确从已记录边界续做，不清除有效修改或只重复受领。附原 CELL/节点目标、授权范围、基线、候选（如有）、下一动作和根记录位置，必要背景用准确引用而非整段历史。
4. 分别记录操作受理、目标可见消息、实际续作和最终交付证据；可见消息只证明投递，不能写成工作完成。恢复信封不是令牌所有权转移，Supervisor 不登记为当前持有者，也不代写成员的工程结论。

Worker 与 Checker 在交付失败时，将当前持有令牌、未投递的完整下一令牌、目标任务 ID 和调用结果交给 Supervisor；正常成功交接仍作为它们的最后动作，发送后结束当前活动。Supervisor 持续观察并负责恢复，必要时直接向原 Worker 或原 Checker 补送原任务，注明实际补送者；不另外创建角色或回执轮次。

## 保持干净的 D1 恢复输入

典型未送达路线仍为 `Worker → Supervisor → Checker`。令牌未真实投递不等于 Checker 失效；优先恢复原 Checker，向原任务 ID 重发同号的未投递令牌，成功后由 Checker 登记流转。

```text
恢复原 Checker 任务，不是新 CELL，也不改变原 D1 目标。
收到该令牌后，在本次激活中直接检查 CELL n/N。
Run/GO/CELL、原令牌编号、当前节点与候选：<真实原值>
Worker 任务 ID 与回复目标：<真实原值>
根记录：<绝对路径>
Worker 原始 D1 交付原文：<干净原文或可准确读取的位置>
```

这是干净的 D1 恢复信封：保留完整原任务、已授权范围澄清、候选与必要客观运行事实；Supervisor 不加入 D0 结果、Worker 判断过程、建议关注点、返工历史或 Supervisor 自己的结论。通讯故障过程留在自身记录，不夹进验收输入。Checker 独立 D1 后按 `Checker → Worker` 正常推进；Supervisor 只观察状态和必要事实，不读取Checker的D1过程来预判结果。

## 恢复仍不收敛

重复执行不完整或真实 model capacity 终止时，调用 `$slk-select-models` 分清能力与资源，按既有授权复核模型/任务范围，不机械重复同一无效提示。明确失效后才调用 `$slk-manage-team` 接管并重做受影响的双向通讯测试；平台整体缺少可用激活操作时如实保留阻碍，不靠创建接管 Checker 伪装通道恢复。

## 完成后

在根记录追加原节点、现场事实、恢复动作与实际结果，明确尚未核实的续作或交付。通道恢复后回到同一 CELL 的原定节点；Supervisor 继续低 Token 观察，不因发出一次恢复消息而退出。

## 负面提示词

- 不要把操作受理、completed 或 TOKEN 所有权当作施工/验收完成；不要在旧回合仍执行时重复派工，把中断虚计为 D1 FAIL，或用补送身份冒充原作者；不要让恢复裁剪掉原目标、授权范围或污染独立 D1。
