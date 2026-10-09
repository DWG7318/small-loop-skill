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

1. 先做 Worker 本地轻量预检：核对已通过的 Run readiness 中 DSH runtime/model/adapter/endpoint、上下文与任务容量、所需 Skill/Tool，再核对不可变 task file、SHA-256、当前 `runtime_revision` 和 `SLK TOKEN` 的 `CELL n/N`、目标、实现范围、依赖、工具能力、证据负荷、D1 验收目标及候选基线；接收令牌不结束当前 CELL 施工。可把实现、测试和证据整理成顺序内部段，但不能自行拆成多个正式 CELL、并行 Worker 或新 TOKEN。启动前通过有界 Git 预检，确认 repo root、Git worktree、common-dir、objects/refs 与沙箱内可写边界；支持独立可写 clone/simple layout，common-dir 在沙箱外的 linked worktree 应在施工前拒绝。实例 ID 保持确定且不超过 64 字符。预检失败或范围明显超能力时，保留已有输出并明确说明实际限制，不伪造 candidate；相同或更旧的令牌编号 不重开 CELL。
2. 在同一次当前 CELL 施工中连续完成所需编辑、命令、测试和最低 D0；Worker用本次原生调用绑定的`SLK_WORKER_ACTION_COMMAND`调用`submit-worker-action --event WORK_STARTED|D0_COMPLETED|CANDIDATE_SUBMITTED --details <本人的JSON动作文件>`明确记录自身事实；候选动作含`candidate`，不是从最终报告猜取。入口内部只用Worker密封权限和密封 Checker endpoint/envelope，不向模型泄露凭据或中央库；报告可为自由文本，保存后同一标准消息交原Checker并原子交接。正式 D1 FAIL 返工只接受绑定当前失败事件、候选和 round 的 `D1_REWORK_DIRECTIVE`。命令、工具结果或中间进展不构成 CELL 交付边界。独占资源阻塞时按需读取 [`references/resource-contention.md`](references/resource-contention.md)，恢复同一 CELL 而不把占用算成返工。
   Owner 已为本次 Run 启用效率工具时，Worker 可先用 Probe CLI 定位再精准读取，用 RTK 获取测试、构建或 Git 输出的低噪声首轮结果，并在适用时遵循 Ponytail 减少过度施工；完整原始输出仍应可追溯，出现失败、截断、疑义或需要核心代码事实时，读取保留原文或回退原生命令。
3. 选择最低 D0，为 Worker 自己的交付提供基本信心，例如目标测试、构建或直接 smoke。建议围绕本次变化和风险选择低成本检查，不提前重复 D1/D2 的完整验收。
4. 把实际变化、D0、判断和风险作为倒数第二项交所属宿主通过 `slk-state write` 记录；大证据用 `register-evidence` 保存，交给 Checker 的默认入口是紧凑 `evidence index`（命令、退出码、摘要、关键失败尾部、原始日志路径、字节数与 SHA-256），不是整份重复编译日志；原始日志仍可追溯。随后自动导出，建议调用 `$slk-record-run`。
5. 初始 D1 交付的业务载荷只包含 `CELL n/N`、候选身份与访问位置、客观变更范围和运行候选所需的必要事实，此外保留主 Skill 定义的统一令牌头。D0 结果、判断过程和建议关注点不进入初始 D1 交付。
6. **代码完成与保存报告不等于交付。** Worker → Checker 原样交出实际变化、候选位置、D0和限制；结果描述器仅作指导，非JSON、嵌套/缺项/多字段或非零退出不触发格式补交。可信Host保存完整原件并独立发给Checker；候选缺失时披露原生Checker无法审查的真实限制，不能编造workspace候选。D0/candidate及工程交接只通过原Worker显式标准行动记录，宿主不由报告合成结论。报告投递不等TOKEN/Temporal维护，工程推进另核实恰好一次当前 CELL/attempt/candidate 的真实接收，不增加接收回执轮次，完成后结束当前活动。

## Checker 未被激活时

跨 Agent 交付由 `slk-transport` 进入 Checker 的原生 Agent 入口，而不是只把文字写入后台聊天记录或按标题寻找对话。Worker 在原生启动证据完成原子提交后结束当前活动，不继续停留或读取 Checker 状态；平台明确返回未启动、目标不可用或投递失败时，调用 `$slk-recover-communication`。Overwatcher 只核实交付与启动证据是否矛盾并向 Supervisor 报告，不替 Worker 交付、提交 TOKEN、exact retry 或等待 D1。

## 完成后

Checker 使用 `$slk-check-cell` 对同一候选执行隔离 D1。

## 负面提示词

- 不要以接收令牌、代码完成、提交存在、测试变绿、单条命令结束或中间结果代替完整 CELL 候选交付，也不要重复执行相同令牌、重复 Worker→Checker handoff 或自行进入未派发 CELL；不要提前把完整 D1/D2 当成 D0，也不要把 D0 结论或判断过程塞入初始 D1 交付；不要在交付后等待或读取 Checker 检查过程。
- 不要接受缺少正式 D1 FAIL 锚点的返工指引，不要把 Supervisor 指引当成 D1 裁决；顺序内部段只用于完成同一正式 CELL，不要自行拆分正式 CELL、并行施工、替换 Worker、改变验收目标、跳过 Git workspace 预检、把 `completed.json` 当成 Checker start，或让别的角色补写 Worker 的 D0/候选事实。
