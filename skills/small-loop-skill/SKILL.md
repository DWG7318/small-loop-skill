---
name: small-loop-skill
description: Use when one bounded engineering Run has a single serial CELL path suited to SLK.
---

# Small Loop Skill

## 方法身份

SLK 4.4.0 是 Loop Engineering 的线性形态，面向中小型工程或大型工程中相对独立的中小范围；一个 SLK 对应一个 Run，Run 直接包含线性 CELL 路径。

它以 CELL Loop 重复派发、施工与 D0、候选交付、隔离 D1，帮助成员判断怎样继续：D1 FAIL 回到同一 CELL 返工，D1 PASS 前进，全部 CELL 处理后由 D2 闭合 Run。进入施工后的一个 Run 同时只有一个当前有效的 `SLK TOKEN`；同一 Run 最大且身份匹配的成功令牌才是当前事实。令牌本身不是新文件、角色、审批或外部状态系统，只在既有 Loop 节点边界流转，携带令牌编号、Run、CELL、当前节点、接收者、候选（如有）、下一动作和根记录路径；中央 SQLite 保存状态事实，`slk-state` 供三个角色按职责写入，`slk-bi-query` 供 Owner、其他 Agent 与未来 BI 只读查询。

## 成员与运行时

- Codex = Supervisor，在启动、上级协助、豁免和 D2 等边界按需激活。
- OCRV = Checker（Qwen3.8-Max），负责日常 CELL 推进、派发和隔离 D1。
- DSH = Worker（DeepSeek V4 Flash），完成当前 CELL，并在交付前执行最低程度 D0。
- Overwatcher 是每个 Run 都登记的运行观察角色：一个 Run 只绑定一个，由 Supervisor 选择并经准备门禁确认；同一精确 Agent Session 可以按 Run 分别登记并服务多个 Run。它保持前台 active turn，每 600 秒主动核实一次真实状态；不是 heartbeat、定时任务、通讯中继或工程角色，只记录自己的观察并把异常、矛盾和 UNKNOWN 交给对应 Supervisor，不改 BI、`SLK TOKEN` 或 D0/D1/D2。

D0 提供交付前基本信心，D1 判断 CELL 是否达到约定目标，D2 判断全部成果合起来是否正确。

## Agent-first 轻方法原则

Supervisor、Checker、Worker、Overwatcher 是 Agent，不是状态机。Worker 与 Checker 工作前做角色本地轻量预检，按范围、证据和工具能力顺序合理化；内部段不并行，不能把内部顺序段当成正式 CELL 或 D1，也不新增 TOKEN。Supervisor 不提前接管，只在成员或 Overwatcher 上报异常时处理并恢复原成员。角色问题先修子 Skill；普通交接与恢复先用直连，不因提示词问题新增协议、daemon 或大段运行时。

- 跨 Agent/进程的一致事实——信封、身份/端点、启动证据、`SLK TOKEN` 原子流转、中央记录和 BI 只读投影——由一个小而稳定的标准 Tool 实现。开工前由团队准备子 Skill 登记四角色、打开 BI、核对工具更新/环境/端点，并以真实接收者启动证据演练必要通讯腿；`slk-transport preflight-run` 只接受闭合 readiness。Agent 不拼隐藏脚本、不直改数据库，也不凭标题或文本猜身份。
- Tool 输出事实，Agent 负责语义判断。项目超时、异常、唤醒、暂停和最小处理方式由对应角色结合真实证据决定，不靠规则穷举现场。
- Temporal 管理子 Skill 负责共享本地服务；每个 Run 使用独立的 `SLK.Start`/`SLK.Run` 工作流记录通讯、成员停留和运行保障，不重写工程 Loop。只有匹配 `slk.native-start/v2` 才证明启动，后续活动用标准 `inspect-native-activity` 查询；缺失、过期、身份不符或权限不足都保持 `UNKNOWN`，不裁决 D0/D1/D2、`SLK TOKEN`、角色、模型或 BI。
- Prompt-only 修正保持 prompt-only：用真实失败作反例并验证对应角色，不扩成数百行代码或庞大测试设施。

原对话与 Owner 选择 SLK，并明确 Run 目标、边界和 Owner 关心的结果。Agent 在创建 Supervisor 前结合项目整理 Run、初始 CELL 与分层检查方案。Supervisor 接管后，原对话退出工程工作，继续保留 Owner 联系和 Supervisor 异常恢复入口。

Supervisor 通过结构化角色 Eval 后，用 `slk-state init-run --credential-out` 初始化状态、密封凭证和 `SLK-RUN-<RUN-ID>.md`。正常施工的精确链是 `Supervisor → Checker`（初始）以及 `Checker → Worker → Checker`；D1 PASS 后仍由 Checker 发下一 CELL，最终由 Checker 把 `D2_READY` 交给 Supervisor。正式 D1 FAIL 才由 Checker 标准 `--slk-post-d1` 后缀走 `Checker → Supervisor → 同一 Worker → Checker`，第二次同 CELL 正式失败起使用 `AGGRESSIVE` 调查指引；INCOMPLETE、工具错误和重复回执不增加失败轮次。持有者单调增加 TOKEN，以真实激活操作投递到已登记的目标原生 Agent 入口；匹配的原生启动证据才证明流转。正常交接由原发送者原子提交 start、TOKEN、事件和 revision；DSH 只密封候选，外部 headless OCRV 启动 Checker。失败由原角色负责；exact retry 只原样一次。三工程角色不用正时长 `wait_threads`；节点后结束活动。OW 自行巡查，Temporal 每 1200 秒独立核查 OW、当前责任成员停留超过 1800 秒直接报告 Supervisor；OW 或 Temporal 保障失效后先由 Supervisor 修复，再派下一 CELL。工具/传输失败留在同一 D1 attempt 并记 INCOMPLETE/`TRANSPORT_FAILED`。边界见 [`docs/state/SLK-STATE.md`](../../docs/state/SLK-STATE.md) 和 [`docs/transport/SLK-TRANSPORT.md`](../../docs/transport/SLK-TRANSPORT.md)。

同一实际 Run 应复用其 run_id；历史独立根需要收敛时，只接受 Owner 明确指定的 canonical/source ID、闭合授权证据和精确快照，由 canonical 当前 Supervisor 追加身份对账回执。旧 Run 采用新方法语义需要另有方法采用回执，不能靠标题、提示词或可见对话推断。

## 按当前情境选择指导

- 新 Run 与初始 CELL 方案：`$slk-plan-run`
- Cargo 或其他明显独占资源的隔离与恢复安排：`$slk-guard-resources`
- Supervisor、Checker、Worker 的模型能力选择：`$slk-select-models`
- Supervisor 开工前理解确认：`$slk-grill-supervisor`
- 建立、恢复、更换或归档成员：`$slk-manage-team`
- Overwatcher 的真实性核查、记录和异常报告：`$slk-overwatch-run`
- 共享 Temporal 服务和每 Run 工作流：`$slk-manage-temporal`
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
- 不要编辑 SQLite、伪造凭证/Run、文本升级合同，或借身份对账改写 CELL、D0/D1/D2、角色、证据与 TOKEN；OW 按合同绑定，不要先写 `RUN_CLOSED` 后补 final cycle/close。
- 不要用终态结果倒推启动成功，也不要用 legacy `started.json`、旧 Session/PID、wrapper ACK、第一 OCRV segment PID 或可见文本冒充当前活动，或用旧 attempt D1、其他 candidate/message 冒充当前交接；不要把旧信封作为新消息重放，不要混合多个 `runtime_revision`，不要在 active writer 前先 resume，不要用 sleep、延迟 PowerShell、post-turn 脚本、后台自唤醒或固定秒数承诺维持关键交接，不要由一次性 DSH 进程托管 OCRV 长审查，不要把传输/工具失败写成产品 D1 FAIL；不要让 Supervisor、Overwatcher 或普通 shell 接触角色凭证、代写 Checker D1 或把 wrapper start 当真实 review，不要在原 Checker 原生 invocation 认证前标记 authorized recovery，不要用 projected active 冒充 Overwatcher cycle 正在继续，也不要用新 Session 或未授权 turn 绕过同一 Overwatcher 绑定；不要为恢复自动升级模型或静默改变 reasoning，也不要加入 BoM 触发器、route、角色或运行时；BoM 保持禁用。
- 不要让 Codex 冒充 OCRV Checker 或 DSH Worker，不要把运行时名称、提示词角色声明或可见对话当成实际角色绑定；不要把本地顺序段升级成正式 CELL、多次 D1、并行工作或新 TOKEN，也不要让 Supervisor 预排内部步骤；不要把零 finding、没有报错或与验收目标无对应关系的一般测试通过直接等同于 D1 PASS，也不要用 Supervisor 后补证据替代 Checker 的 D1；不要把候选可能正确、D1 已通过和 D2/Run 已关闭合并成一个结论，或把间接验证写成未实际执行的目标环境验证。
- 不要因协作问题加状态机。上下文压缩或续作后按中央状态、当前 Run 记录、计划和当前 TOKEN 重验 `run_id`、CELL/attempt、下一动作；摘要、旧话题或对话记忆冲突时停止串题。
- 不要让 Temporal 裁决工程、切换模型、写 BI/TOKEN 或重复副作用；服务或 OW 保障失效时不要继续派下一 CELL。
- 不要反向把跨 Agent 通讯、身份校验、TOKEN 原子流转、中央记录或 BI 一致性退回自由文本约定；这些共享事实与传输边界应继续由小而明确的代码合同保证。
- 不要在 Run readiness 不是 `READY`、四角色/BI/Temporal/必要通讯腿未验证、任一角色被提示词替代、任务超过该角色容量，或 Ponytail/RTK/Probe CLI 任一可选项未明确时开始施工；BoM 不是可配置项，readiness 请求不声明它，出现时先移除；不要把可选工具缺失误写为工程角色不兼容。
- 不要新增只有作者知道如何运行的一次性脚本或隐藏代码路径；需要长期复用的确定性能力应成为有文档调用规则的标准 Tool，做不到轻量稳定时就不要继续堆代码。
