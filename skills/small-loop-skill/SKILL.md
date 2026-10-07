---
name: small-loop-skill
description: Use when one bounded engineering Run has a single serial CELL path suited to SLK.
---

# Small Loop Skill

## 方法身份

SLK 4.4.2 是 Loop Engineering 的线性形态，面向中小型工程或大型工程中相对独立的中小范围；一个 SLK 对应一个 Run，Run 直接包含线性 CELL 路径。

它以 CELL Loop 重复派发、施工与 D0、候选交付、隔离 D1，帮助成员判断怎样继续：D1 FAIL 回到同一 CELL 返工，D1 PASS 前进，全部 CELL 处理后由 D2 闭合 Run。进入施工后的一个 Run 同时只有一个当前有效的 `SLK TOKEN`；同一 Run 最大且身份匹配的成功令牌才是当前事实。令牌本身不是新文件、角色、审批或外部状态系统，只在既有 Loop 节点边界流转，携带令牌编号、Run、CELL、当前节点、接收者、候选（如有）、下一动作和根记录路径；中央 SQLite 保存状态事实，`slk-state` 供三个角色按职责写入，`slk-bi-query` 供 Owner、其他 Agent 与未来 BI 只读查询。

## 成员与运行时

- Codex = Supervisor，在启动、上级协助、豁免和 D2 等边界按需激活。
- OCRV = Checker（Qwen3.8-Max），负责日常 CELL 推进、派发和隔离 D1。
- DSH = Worker（DeepSeek V4 Flash），完成当前 CELL，并在交付前执行最低程度 D0。
- Overwatcher 是每个 Run 都登记的运行观察角色：一个 Run 只绑定一个，由 Supervisor 选择并经准备门禁确认；同一精确 Agent Session 可以按 Run 分别登记并服务多个 Run。它保持前台 active turn，每 600 秒主动核实一次真实状态；不是 heartbeat、定时任务、通讯中继或工程角色，只记录自己的观察并把异常、矛盾和 UNKNOWN 交给对应 Supervisor，不改 BI、`SLK TOKEN` 或 D0/D1/D2。

D0 提供交付前基本信心，D1 判断 CELL 是否达到约定目标，D2 判断全部成果合起来是否正确。

## Agent-first 轻方法原则

Supervisor、Checker、Worker、Overwatcher 是 Agent，不是状态机。Worker 与 Checker 工作前做角色本地轻量预检，按范围、证据和工具能力顺序合理化；内部段不并行，不能把内部顺序段当成正式 CELL 或 D1，也不新增 TOKEN。Supervisor 不提前接管，只在成员或 Overwatcher 上报异常时处理并恢复原成员。角色问题先修子 Skill；普通交接与恢复先用直连，不因提示词问题新增协议、daemon 或大段运行时。

- 共享事实由标准 Tool 保证。准备时登记角色、BI、工具和端点。首份来源用 `slk-conformance/<SLK-CONFORMANCE-…>` 证据根绑定独立 clean/no-remote 单 CELL 样本 Git，经 `preflight-conformance-sample` 实跑且不承载产品；产品/续接分别用 `preflight-new-run`/`preflight-admission`，不伪造事实或猜身份。
- Tool 输出事实，Agent 负责语义判断。项目超时、异常、唤醒、暂停和最小处理方式由对应角色结合真实证据决定，不靠规则穷举现场。
- Temporal 管理子 Skill 负责共享本地服务；每个 Run 使用独立的 `SLK.Start`/`SLK.Run` 工作流记录通讯、成员停留和运行保障，不重写工程 Loop。只有匹配 `slk.native-start/v2` 才证明启动，后续活动用标准 `inspect-native-activity` 查询；缺失、过期、身份不符或权限不足都保持 `UNKNOWN`，不裁决 D0/D1/D2、`SLK TOKEN`、角色、模型或 BI。
- Prompt-only 修正保持 prompt-only：用真实失败作反例并验证对应角色，不扩成数百行代码或庞大测试设施。

原对话与 Owner 选择 SLK，并明确 Run 目标、边界和 Owner 关心的结果。Agent 在创建 Supervisor 前结合项目整理 Run、初始 CELL 与分层检查方案。Supervisor 接管后，原对话退出工程工作，继续保留 Owner 联系和 Supervisor 异常恢复入口。

Supervisor 通过结构化角色 Eval 后用 `slk-state init-run --credential-out` 初始化状态和根记录 `SLK-RUN-<RUN-ID>.md`，再密封消费者。正常链为 `Supervisor → Checker`、`Checker → Worker → Checker`；PASS 派下一 CELL，最终交 `D2_READY`。正式 FAIL 才走 `Checker → Supervisor → 同一 Worker → Checker`；第二次起旧 Host 拒绝普通返工，Supervisor `revise-plan` 拆分并冻结新 Host。INCOMPLETE 不伪造 FAIL/返工；Checker 用 `D1_INCOMPLETE_ESCALATION` 把 TOKEN 和原因交给 Supervisor，后者只选机械恢复、等待或容量/环境调整，D1 仍归原 Checker。RoleHost 通过已登记的目标原生 Agent 入口做真实激活操作，用原发送者密封凭据执行后缀；原生启动证据与 TOKEN 提交分别核实，exact retry 只原样一次，已有 start 只补提交。标准入口含 `commit-delivery-start`、FAIL `--slk-post-d1`、PASS `--slk-complete-d1` 和 INCOMPLETE `--slk-manage-incomplete`。三工程角色不用正时长 `wait_threads`；真实 native start 后不把启动/RPC timeout 当工程死亡线。OW 自行巡查，Temporal 每 1200 秒核查 OW、成员停留超过 1800 秒直报 Supervisor；保障失效先修复再派下一 CELL。边界见 [`docs/state/SLK-STATE.md`](../../docs/state/SLK-STATE.md) 和 [`docs/transport/SLK-TRANSPORT.md`](../../docs/transport/SLK-TRANSPORT.md)。

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

- 不要把 Goal 用于启动准备／预检之外；该阶段允许 Supervisor 按团队准备子 Skill 启动或续用；不要把例外扩到正常 CELL、D0、D1、返工、OW 巡查、D2，或让 Worker/Checker/OW 使用 Goal；不要用一个对话的 Goal 驱动整 Run、替代逐节点 `SLK TOKEN` 流转或保证自动重启。
- 不要把 D1 INCOMPLETE 当 FAIL/返工或留在 Checker 死等；应使用闭合管理交接让 Supervisor 处理真实容量/环境原因。正常 OCRV 默认 aggregate budget/timeout 均为 `0`（原生不限）；只有 Owner 明确冻结有限预算时才保留它，旧有限预算证据仍只用身份绑定的标准恢复 Tool，不手填请求或改全局预算；补审 PASS/FAIL 回原 Checker 既有后缀。
- 不要把针对某个 CELL、某类工作或一次经验形成的容量估计、数字边界或经验规则，泛化为所有 CELL、整个 Run 或其他项目共同遵守的一刀切定额；不要为了平均、整齐或便于管理，要求每个 CELL 满足相同指标。这不排除根据具体 CELL 的目标、难度、依赖、模型、电脑和余量，形成只适用于该 CELL 的、有事实依据的容量边界。
- 不要把 SLK TOKEN、SQLite、BI 或 Overwatcher 当成逐条命令队列、常驻运行时、裁决者或额外确认层；令牌不构成真实运行证明，界面 running 或无法证明的活动也不是；不要让 Owner、Overwatcher、其他 Agent 或 BI 越权改写工程事实、TOKEN 或只读投影，不要让相同或更旧的令牌编号创建新工作、回退指针或重开 CELL；不要把 Checker 的 D1 交给 Supervisor，把 DELIVERED 当成 D1_ACCEPTED，按标题合并 Run，在同一实际 Run 的继续过程中另造 run_id，或让三工程角色用正时长 `wait_threads`、旧状态和 heartbeat 代替真实交接与活动证据。
- 不要编辑 SQLite、伪造凭证/Run、文本升级合同，或借身份对账改写 CELL、D0/D1/D2、角色、证据与 TOKEN；OW 按合同绑定，不要先写 `RUN_CLOSED` 后补 final cycle/close。
- 不要用终态倒推启动，或以旧 Session/PID、wrapper ACK、第一 OCRV segment PID、可见文本、旧 attempt/candidate 冒充当前活动；不要把旧信封换成新消息、混 revision、在 active writer 前 resume 或延迟自唤醒。凭据仅由可信 Tool 内部消费，宿主不代判。不要把投递失败写成 D1 FAIL、INCOMPLETE 改成 completed、accepted/turn started 写成接管，或用 projected active 替代 OW cycle。长材料用路径、字节数和 SHA-256，控制消息保持紧凑；不要用无依据字符门槛或静默截断，不自动换模型、reasoning 或 Session。
- 不要让 Codex 冒充 OCRV Checker 或 DSH Worker，不要把运行时名称、提示词角色声明或可见对话当成实际角色绑定；不要把本地顺序段升级成正式 CELL、多次 D1、并行工作或新 TOKEN，也不要让 Supervisor 预排内部步骤；不要把零 finding、没有报错或与验收目标无对应关系的一般测试通过直接等同于 D1 PASS，也不要用 Supervisor 后补证据替代 Checker 的 D1；不要把候选可能正确、D1 已通过和 D2/Run 已关闭合并成一个结论，或把间接验证写成未实际执行的目标环境验证。
- 不要因协作问题加状态机。上下文压缩或续作后按中央状态、当前 Run 记录、计划和当前 TOKEN 重验 `run_id`、CELL/attempt、下一动作；摘要、旧话题或对话记忆冲突时停止串题。
- 不要让 Temporal 裁决工程、切换模型、写 BI/TOKEN 或重复副作用；服务或 OW 保障失效时不要继续派下一 CELL。
- 不要反向把跨 Agent 通讯、身份校验、TOKEN 原子流转、中央记录或 BI 一致性退回自由文本约定；这些共享事实与传输边界应继续由小而明确的代码合同保证。
- 不要在 Run readiness 不是 `READY`、四角色/BI/Temporal/必要通讯腿未验证、任一角色被提示词替代、任务超过该角色容量，或 Ponytail/RTK/Probe CLI 任一可选项未明确时开始施工；未登记功能不能靠任意 ON/OFF 字段进入能力清单；不要把可选工具缺失误写为工程角色不兼容。
- 不要新增只有作者知道如何运行的一次性脚本或隐藏代码路径；需要长期复用的确定性能力应成为有文档调用规则的标准 Tool，做不到轻量稳定时就不要继续堆代码。
