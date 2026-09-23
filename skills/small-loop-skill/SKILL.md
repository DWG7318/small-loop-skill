---
name: small-loop-skill
description: Use when one bounded engineering Run has a single serial CELL path suited to SLK.
---

# Small Loop Skill

## 方法身份

SLK 是 Loop Engineering 的线性形态，面向中小型工程或大型工程中相对独立的中小范围；一个 SLK 对应一个 Run，Run 直接包含线性 CELL 路径。

它以 CELL Loop 重复派发、施工与 D0、候选交付、隔离 D1，帮助成员判断怎样继续：D1 FAIL 回到同一 CELL 返工，D1 PASS 前进，全部 CELL 处理后由 D2 闭合 Run。进入施工后的一个 Run 同时只有一个当前有效的 `SLK TOKEN`；同一 Run 最大且身份匹配的成功令牌才是当前事实。令牌本身不是新文件、角色、审批或外部状态系统，只在既有 Loop 节点边界流转，携带令牌编号、Run、CELL、当前节点、接收者、候选（如有）、下一动作和根记录路径；中央 SQLite 保存状态事实，`slk-state` 供三个角色按职责写入，`slk-bi-query` 供 Owner、其他 Agent 与未来 BI 只读查询。

## 成员与运行时

- Codex = Supervisor，在启动、上级协助、豁免和 D2 等边界按需激活。
- OCRV = Checker（Qwen3.8-Max），负责日常 CELL 推进、派发和隔离 D1。
- DSH = Worker（DeepSeek V4 Flash），完成当前 CELL，并在交付前执行最低程度 D0。
- Overwatcher 是可选的 Run 级 Agent Session：每 Run 最多一个、由 Supervisor 与 Owner 确认、不要跨 Run 复用；一个 Run 只绑定一次，不是每个 CELL 重新确认，一旦绑定便由同一 Session 保持前台 active turn，并每 180–300 秒主动完成固定巡查。它不是 heartbeat、定时任务或后台 Agent，只观察运行、协助通讯恢复并记录自己的 revision-bound cycle/operational observation，不接管三角色通讯、工程判断、`SLK TOKEN` 或 BI；从未绑定时不阻断原 Loop。

D0 提供交付前基本信心，D1 判断 CELL 是否达到约定目标，D2 判断全部成果合起来是否正确。

## Agent-first 轻方法原则

本原则统领全部 SLK 子 Skill 与方法仓工作。Supervisor、Checker、Worker、Overwatcher 都是能理解上下文并作出判断的 Agent，不是等待代码替它们思考的状态机。SLK 首先依靠清楚的角色分工、针对情境的子 Skill、必要的主 Skill 总则和 Agent 之间的直接通讯完成闭环。

- 角色误解、判断失准、该汇报却未汇报、该停止却继续空转等问题，先修改对应子 Skill；只有跨角色共性才在主 Skill 增补简短总则。
- 优先让 Agent 读取真实证据后判断，规则负责说明职责、边界、必须做什么和禁止做什么，不穷举所有现场，不把 LLM 降格为异常代码匹配器。
- 一次普通交接、超时、唤醒、异常汇报或恢复问题，先使用现有 Agent 直连与现有 Skill。能用提示词和职责解决，就不要新增 schema、状态字段、协议、凭证流程、恢复器、daemon 或大段运行时代码。
- 代码承担必须跨 Agent、跨进程保持一致的标准化基础能力：通讯信封与投递/启动证据、角色身份和端点校验、`SLK TOKEN` 的原子流转、中央记录、不可变证据与 BI 只读投影。这些确定性边界用代码约束是正确的，不能让 Agent 凭自由文本各自发挥。
- 这类代码能力必须封装成职责单一的标准 Tool，并至少提供 CLI、MCP 或 API 中一种稳定入口；不要让 Agent 拼接隐藏脚本、直接操作数据库或复制实现逻辑。主 Skill 说明共同行为与选择原则，使用该能力的子 Skill 说明何时调用、必需输入、可信输出、失败边界和禁止替代方案。
- Tool 输出确定性事实，Agent 负责理解这些事实并作语义判断。Tool 不应内置项目判断、替角色决策或靠不断增加规则模拟 LLM；Agent 也不能跳过 Tool 去猜测 TOKEN、身份、投递、证据或 BI 状态。
- 标准 Tool 保持小、稳、长期可维护：一个能力尽量只有一个权威实现和一个首选入口。若为了一个能力开始需要大量调度、持久计时、复杂重试、分布式恢复或重型状态机，停止扩写并向 Owner 比较 Temporal 等成熟开源方案，不在 SLK 内勉强自研。
- 代码不替 Agent 做语义判断、项目管理或角色协作决策。判断“当前是否异常、某项工作是否超时、该唤醒谁、是否应暂停、采用什么最小解决办法”等上下文问题，优先由对应角色依据 Skill 和真实证据完成。新增确定性基础能力时仍保持最小范围，并取得 Owner 对明显工程扩张的明确同意。
- 若需求真正需要长期持久计时、分布式事务、复杂重试、调度和故障恢复，应把“是否采用 Temporal 等成熟工作流引擎”作为独立架构决定交给 Owner；不要在 SLK 内逐步重造一个更重、更差的工作流系统。
- Prompt-only 修正保持 prompt-only：用已发生的失败作为反例，做一次对应角色的行为验证即可；不要为短提示词补丁扩成数百行代码、长篇机制设计或庞大测试基础设施。

原对话与 Owner 选择 SLK，并明确 Run 目标、边界和 Owner 关心的结果。Agent 在创建 Supervisor 前结合项目整理 Run、初始 CELL 与分层检查方案。Supervisor 接管后，原对话退出工程工作，继续保留 Owner 联系和 Supervisor 异常恢复入口。

Supervisor 通过结构化角色 Eval 后，用 `slk-state init-run` 初始化中央状态与自动生成的 `SLK-RUN-<RUN-ID>.md` 导出。随后按 Supervisor 创建 Checker，Checker 创建 Worker 的关系建立成员；正常通讯保持 `Supervisor ↔ Checker ↔ Worker`，只有正式 D1 FAIL 才沿 `Checker → Supervisor → 同一 Worker` 发送结构化返工指引。通讯测试完成后，Supervisor 用 `T001` 把第一个待派发 CELL 的责任交给 Checker；此后当前持有者在完成既有节点时单调增加编号，并用真实激活操作把完整 `SLK TOKEN` 消息投递到已登记的目标原生 Agent 入口。DSH/OCRV 只读取不可变 task file；与消息匹配的原生启动证据才证明流转，`started.json` 应在终态结果前独立形成。4.2.5 的发送者用 `commit-delivery-start` 将启动回执、TOKEN、事件和 fresh `runtime_revision` 原子提交，不增加令牌专用回执，不能用终态结果倒推启动成功或再调用旧式分步 `handoff`。若 DSH 工程工作终态完成却漏掉 Worker D0/候选/Checker 交接后缀，Supervisor 只向原注册 OCRV Checker 投递闭合恢复信封；该原生 Checker 认证自身后才可精确恢复同一 DSH Session，由 Worker 在自己的进程内完成后半段，其他角色不直接恢复或代写。明确失败时仍持有当前令牌；空闲目标的 exact retry 只复用同一 message、信封、端点和 scope 一次，活跃 Supervisor writer 则使用绑定准确 active turn 的新消息，任何其他语义变化交 Supervisor。旧 running、旧 TOKEN、可见消息或 heartbeat 都不证明正在工作，投影中的 active 也不证明 cycle 正在继续；Supervisor、Checker、Worker 不使用正时长 `wait_threads`，完成节点与交接后结束当前活动。Overwatcher 缺席不阻断工作；一旦绑定则按自己的前台 active turn 合同持续巡查，可用有界同进程 `wait-for-change` 观察权威 revision，但仍只旁路观察与协助恢复。状态与通讯边界见 [`docs/state/SLK-STATE.md`](../../docs/state/SLK-STATE.md) 和 [`docs/transport/SLK-TRANSPORT.md`](../../docs/transport/SLK-TRANSPORT.md)。

同一实际 Run 应复用其 run_id；历史独立根需要收敛时，只接受 Owner 明确指定的 canonical/source ID、闭合授权证据和精确快照，由 canonical 当前 Supervisor 追加身份对账回执。旧 Run 采用新方法语义需要另有方法采用回执，不能靠标题、提示词或可见对话推断。

## 按当前情境选择指导

- 新 Run 与初始 CELL 方案：`$slk-plan-run`
- Cargo 或其他明显独占资源的隔离与恢复安排：`$slk-guard-resources`
- Supervisor、Checker、Worker 的模型能力选择：`$slk-select-models`
- Supervisor 开工前理解确认：`$slk-grill-supervisor`
- 建立、恢复、更换或归档成员：`$slk-manage-team`
- 可选 Overwatcher 的观察、告警和原样恢复：`$slk-overwatch-run`
- Checker 派发前校准并交付既定 CELL：`$slk-dispatch-cell`
- Worker 施工与最低 D0：`$slk-execute-cell`
- Checker 隔离执行 D1：`$slk-check-cell`
- 各成员写入共享 Run 记录：`$slk-record-run`
- D1 未通过后的普通返工：`$slk-rework-cell`
- Supervisor 处理升级决策、返工路线、能力安排、Owner 授权建议或豁免：`$slk-adjust-run`
- Worker 向 Checker 交付后缺少当前 CELL 的接收证据：`$slk-recover-communication`
- 所有计划 CELL 明确处理后的 D2、归档和 Owner 结论：`$slk-close-run`

通常读取当前情境对应的指导即可；新的情况出现时，再补充相关 Skill。

## 负面提示词

- 不要把 SLK Run 绑定到任何由单个对话持续工作到底的 Goal 模式，也不要让这类 Goal 驱动或续作 Run；这不限制目标定义，天然冲突来自固定对话与 `SLK TOKEN` 在 Supervisor、Checker、Worker 之间逐节点流转不能同时成为执行主线。
- 不要把 D1 INCOMPLETE 当成 FAIL 或返工，不要把正式 D1 FAIL 的受限 Supervisor 指引扩成普通 Worker 派工或 D1 裁决。
- 不要把针对某个 CELL、某类工作或一次经验形成的容量估计、数字边界或经验规则，泛化为所有 CELL、整个 Run 或其他项目共同遵守的一刀切定额；不要为了平均、整齐或便于管理，要求每个 CELL 满足相同指标。这不排除根据具体 CELL 的目标、难度、依赖、模型、电脑和余量，形成只适用于该 CELL 的、有事实依据的容量边界。
- 不要把 SLK TOKEN、SQLite、BI 或 Overwatcher 当成逐条命令队列、常驻运行时、裁决者或额外确认层；不要让 Owner、Overwatcher、其他 Agent 或 BI 越权改写工程事实、TOKEN 或只读投影，不要让相同或更旧的令牌编号创建新工作、回退指针或重开 CELL；不要把 Checker 的 D1 交给 Supervisor，把 DELIVERED 当成 D1_ACCEPTED，按标题合并 Run，在同一实际 Run 的继续过程中另造 run_id，或让三工程角色用正时长 `wait_threads`、旧状态和 heartbeat 代替真实交接与活动证据。
- 不要直接编辑 SQLite、伪造失效的旧角色凭证、新建替代 Run、用自由文本静默升级方法合同，或借身份对账改写 CELL、D0/D1/D2、角色、证据与 TOKEN；Overwatcher 只在有效版本或显式采用回执之后绑定。
- 不要用终态结果倒推启动成功，不要把旧信封作为新消息重放，不要混合多个 `runtime_revision`，不要由 Supervisor/Overwatcher/普通 shell 直接启动 Worker completion continuation，不要在原 Checker 原生 invocation 认证前标记 authorized recovery，不要用 projected active 冒充 Overwatcher cycle 正在继续；不要为恢复自动升级模型或静默改变 reasoning，也不要加入 BoM 触发器、route、角色或运行时；BoM 保持禁用。
- 不要让 Codex 冒充 OCRV Checker 或 DSH Worker，不要把运行时名称、提示词角色声明或可见对话当成实际角色绑定；不要把零 finding、没有报错或与验收目标无对应关系的一般测试通过直接等同于 D1 PASS，也不要用 Supervisor 后补证据替代 Checker 的 D1；不要把候选可能正确、D1 已通过和 D2/Run 已关闭合并成一个结论，或把间接验证写成未实际执行的目标环境验证。
- 不要把角色理解或协作问题首先改造成代码问题，不要用“更可靠”作为增加状态机、协议层、恢复运行时或数百行代码的理由；先把对应子 Skill 和必要的主 Skill 提示写清楚，让 Agent 履行职责。
- 不要把 SLK 方法仓发展成自制工作流引擎；若问题规模已经自然要求 Temporal 一类能力，停止堆叠机制并请 Owner 作独立架构选择。
- 不要反向把跨 Agent 通讯、身份校验、TOKEN 原子流转、中央记录或 BI 一致性退回自由文本约定；这些共享事实与传输边界应继续由小而明确的代码合同保证。
- 不要新增只有作者知道如何运行的一次性脚本或隐藏代码路径；需要长期复用的确定性能力必须成为有文档调用规则的标准 Tool，做不到轻量稳定时就不要继续堆代码。
