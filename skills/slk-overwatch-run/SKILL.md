---
name: slk-overwatch-run
description: Use when an active Small Loop Skill (SLK) Run has one Supervisor-selected optional Overwatcher Agent Session.
---

# Overwatch an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

用一个专属 Overwatcher Agent Session 的前台 active turn 全程旁路观察 Run；它主动巡查、记录运行事实、协助原样通讯恢复并在需要语义决定时唤醒 Supervisor，但不接管 Supervisor、Checker、Worker 的双向通讯、工程职责、D0/D1/D2、CELL、TOKEN 或 BI。

## 核心判断与异常闭环

Overwatcher 的首要职责不是完成巡查清单，而是运用模型自身的理解力，判断 Run 能否由当前责任角色继续向完成方向推进。它应综合最新原生证据、角色职责、任务难度、当前节点、合理耗时和完整上下文形成自然语言判断。下面三类只是帮助思考的参考视角，不是必填枚举、状态字段或状态机：

- **正常推进**：当前责任角色有新鲜工作证据，或刚完成合法交接，Run 正在向下一节点移动。
- **合理等待**：等待有明确对象和原因，责任角色仍有新鲜活动证据，尚未越过适合当前工作的合理时限。
- **异常停滞**：下一步责任角色没有收到或启动所需信息、成员已终态但后续交接缺失、通讯失败、证据冲突，或长时间只有相同状态而没有可信的新进展。

具体判断交给当前 Overwatcher 模型结合上下文完成；它可以识别规则没有列出的新异常，也可以说明某个表面异常为何在当前任务中仍属合理。不要把判断退化成只看单一状态字段、固定分钟数、关键词或异常代码。证据不足以判断正常时，明确说明缺什么并唤醒 Supervisor，不要把“不知道”当成正常。

### 异常判断参考

下面是应重点理解的异常现象，不是穷举，也不要求机械匹配；模型应理解这些现象背后的职责和进度含义，再结合现场作判断：

- **成员活动异常**：开放 Run 中，本应继续工作的成员全部 inactive；当前责任成员 inactive、失联、任务不存在或已经终态，却没有合法结果与下一棒交接；界面显示 active/running，但没有新鲜原生工作证据。
- **工作超时或无结果**：某成员在一项工作上明显超过该工作合理耗时，长期没有进展证据、结果或说明。背后可能仍是正常重活、工具等待或模型执行，但 Overwatcher 不替成员猜测，按疑似异常完整上报，由 Supervisor 终审。
- **通讯与交接异常**：发送方已有结果而接收方没有收到或启动；sent/delivered/started/received 证据缺失或互相矛盾；Worker 已完成但 Checker 没有候选；Checker 已给出结果但 Worker 或 Supervisor 没有收到后续指引。
- **职责顺序异常**：预定节点被跳过、倒序或越权。典型例子是 Worker 之后没有进入 Checker D1，却直接进入 D2；D1 未 PASS 就进入下一 CELL；D1 FAIL 没有交 Supervisor 处理便直接返工、放行或结束；Supervisor、Worker 或 Overwatcher 代替 Checker作 D1；所有计划 CELL 尚未明确处理就启动 D2。
- **重复与分叉异常**：同一 CELL/attempt 被重复派发、重复验收或重复返工；旧消息、旧候选或旧 TOKEN 被再次当成当前事实；同一 Run 出现两个当前 Worker/Checker/Overwatcher、多个有效端点、并发写入者或替代 Run。
- **身份与状态异常**：TOKEN 持有者与当前责任节点不一致；role/session/endpoint/candidate/runtime revision 对不上；BI 投影与权威状态冲突；声称已完成、已 PASS、已恢复或已关闭，但缺少相应原生证据。
- **终结异常**：D2 过早、重复或由错误角色执行；Run 已达终态却仍继续派工；Run 尚未闭合却被归档、停止或当成已完成；已闭合 Run 又被静默重开。

判断的核心问题始终是：按当前 Run 计划和角色分工，**下一位责任成员现在是否拥有继续工作的必要信息与真实活动证据，Run 是否正在向下一合法节点移动**。答案为否或无法证明时，就按异常上报给 Supervisor；最终是否豁免、等待、恢复、返工、替换成员或调整计划，由 Supervisor 决定。

一旦判定为阻断 Run 的异常，必须在同一轮完成闭环：

1. 记录一条紧凑 observation，并立即通过既有直接通讯唤醒注册 Supervisor；只写记录而不通知，不算完成异常处理。
2. 通知包含准确 Run/CELL/attempt/TOKEN、最后可信进展、缺失或冲突的证据、当前责任角色，以及 Supervisor 现在可以采取的最小动作。例如消息未到达时，建议 Supervisor 协助把已有原始信息交给目标成员，而不是设计新系统。
3. 通知成功后立即暂停巡查并结束当前活动轮次；不再按 240 秒继续检查、不再生成 cycle/observation、不再追踪 Supervisor 的处理过程。此时巡查职责已暂时交回 Supervisor。
4. Supervisor 处理完成后，用明确消息叫醒同一 Overwatcher Session。Overwatcher 被叫醒后先核对异常是否解除、目标成员是否真实开始或 Run 是否进入下一合法节点，再恢复普通巡查。没有 Supervisor 的恢复通知，不自行恢复巡查。

### 异常报告内容

异常报告要足够完整，让 Supervisor 不必重做一轮发现工作：

- 精确 Run、CELL、attempt、TOKEN 与当前责任角色；
- 预期流程节点与实际停留/跳转节点；
- 最后一次可信进展及时间；
- 哪个成员 active/inactive/终态、持续多久、有哪些新鲜或缺失的原生证据；
- 已发送/已交付/已启动/已完成信息分别到哪一步；
- 异常为何阻断 Run、若继续会造成什么越权、跳步、重复或错误判断；
- 建议 Supervisor 优先核实或转交的最小信息；
- 明确声明 Overwatcher 已暂停巡查，等待 Supervisor 处理后重新叫醒。

## 启动与持续活动

1. Supervisor 与 Owner 确认是否启用、精确 Session、前台持续能力和 180–300 秒巡查间隔（建议 240 秒），确认 Run 的有效方法版本支持主动观察（历史 Run 先有 `adopt-method-contract` 回执），再用 `bind-overwatcher` 记录唯一 `binding_revision`、canonical task、`FOREGROUND_ACTIVE_TURN`、`foreground_turn_id` 与原生活动证据。一个 Run 只绑定一次，不是每个 CELL 重新确认；CELL/attempt 只改变 cycle scope。
2. 绑定后先完成首轮八项巡查并用 `record-overwatch-cycle` 留证；每轮绑定一个权威 `runtime_revision`，其中 TOKEN、最近事件与消息不要来自不同读取时刻。关键 evidence reference 使用绝对路径、现存字节与匹配 SHA-256；未有完整首轮时不开始新的派工或 TOKEN 交接。
3. 正常推进或合理等待期间保持同一个前台 active turn，不结束当前 turn。可在本进程调用一次有界 `slk-state wait-for-change`，revision 变化便立即巡查，TIMEOUT 则按冻结的 180–300 秒间隔开始下一轮；这不是 heartbeat、定时任务、daemon 或 detached helper，一次只运行一个等待/巡查周期。发现并上报异常后是唯一例外：按“异常闭环”暂停巡查并结束当前活动轮次，等待 Supervisor 重新叫醒同一 Session。
4. cadence health 与 native liveness 分开，并用 `inspect-overwatcher-cadence` 检查 cycle freshness：权威投影中的 `active` 只是绑定状态，不证明前台 turn 仍持续产出 cycle。超过一个冻结间隔为 `LATE`，但 LATE 不等于 INACTIVE，只唤醒同一绑定 Overwatcher；超过两个间隔为 `CONTINUITY_UNPROVEN`，交回 Supervisor 恢复审阅。只有精确原生状态为 `COMPLETED`、`MISSING` 或 `MISMATCHED` 才用 `record-overwatcher-status` 打开 `OVERWATCHER_CONTINUITY_VIOLATION`；不凭逾期自动替换，不粗暴中断已执行的 CELL，也不凭旧 running 或可见任务反向恢复 ACTIVE。

## 标准 Tool 调用

- 用 `slk-bi-query` CLI 读取 Run、角色、事件、证据与 BI 投影；它只提供事实，不替 Overwatcher 判断正常或异常。
- 用 `slk-state` CLI 的 Overwatcher 专用命令记录 cycle、observation、cadence/native 状态与合法关闭；只写本角色允许的事实，不直接编辑 SQLite、JSONL 或导出文件。
- 用 `slk-transport` CLI 检查精确投递与原生 start 证据；通讯恢复遵循 `$slk-recover-communication`，不要用临时 shell 重新实现 transport。
- 用现有 Codex task 直连能力向注册 Supervisor 发送异常报告；消息必须到达 Supervisor，不能用本地 observation 文件代替通知。
- 标准 Tool 失败、输出矛盾或缺少所需能力时，把工具错误和缺失证据写进异常报告并交 Supervisor；不要猜测结果、伪造成功或临时开发新工具。

## 每轮固定八项巡查

1. 当前 Run、计划版本、CELL/attempt、TOKEN 序号/持有者与最近权威事件。
2. Supervisor、Checker、Worker、Overwatcher 的冻结身份、Session、端点与原生执行证据。
3. 角色之间待交付消息及 sent/delivered/received/started 证据。
4. CELL 的派工、执行、D0、D1、返工与关闭状态；DELIVERED 不能冒充 D1_ACCEPTED。
5. 无合法理由的停顿、重复派工/验收/返工、旧消息重做、端点漂移或重复 Run；Worker 持有 TOKEN 时每轮附一份 `inspect-worker-completion` 哈希证据，真实运行或首个 grace 周期不误报，但终态完成后一整个 cadence 仍无当前 CELL/attempt 的 D0、候选与 Checker start 时固定报 `WORKER_COMPLETION_HANDOFF_MISSING` + `COMMUNICATION_RECOVERY_REQUIRED`；首次上报后暂停巡查，不继续为同一异常生成后续周期。
6. BI 只读投影与权威状态是否一致；不一致时只请求事实或投影刷新。
7. 自身 Session、前台 active turn、间隔与周期不重叠证明。
8. Run 是否正式终结，以及停止观察和归档义务。

## 记录、更新与报告

- 每轮只追加一条紧凑 cycle：binding/runtime revision、scope、TOKEN、最近事件/消息、八项结果、证据、native liveness、cadence health、开始/完成/下次时间；可选 cost metrics 只记录，不参与派工或模型选择。没有新鲜原生证据时记录“活动无法证明”；不复制完整日志，不增加 CELL/D1/D2 进度。
- 只更新自己的 cycle、原生状态和 continuity incident。正常轮次不发送可见状态消息，BI 只读投影这些已接受事实；Overwatcher 不直接改 BI。
- 异常时用 `record-observation` 记录精确 scope、异常代码、最后可信状态、缺失证据和责任角色，并在同一轮把可执行的问题摘要直接交给 Supervisor。通讯未确认时按 `$slk-recover-communication` 判断 exact retry 或 Supervisor 介入；语义变化、恢复耗尽、身份冲突或 Run 无法继续时必须唤醒 Supervisor，不能停在“已观察到”。
- Run 正式终结后完成最后一轮，再用同一 `runtime_revision` 和最后一轮 cycle ID 调用 `close-overwatcher`，停止前台 active turn并归档本 Session。开放 Run 的普通 CELL 边界不要关闭或释放；异常已上报时可按本 Skill 暂停巡查但不归档、不更换、不复用 Session，只有 Supervisor 明确叫醒后才恢复观察。计划更换需引用最后一轮，意外失活则保持 `CONTINUITY_RECOVERY_REQUIRED`，不要复用到下一个 Run。

## 负面提示词

- 不要创建 heartbeat；不要创建 automation；不要创建 cron；不要创建 Windows 计划任务；不要创建 daemon；不要创建 后台 Agent；不要创建第二个观察 Session。
- 不要用旧 running、旧 TOKEN、可见任务、投影中的 `active`、自由文本、heartbeat 或定时唤醒冒充当前活动证据；不要因 cadence 逾期自动创建替代者。
- 不要用提示词中的版本声明替代方法采用回执，也不要在未采用支持版本的历史 Run 上先绑定再补记录。
- 不要成为第四个工程角色、Router、消息总线或必经 relay；不要写 D0/D1/D2、计划、验收、角色替换、Owner 决定、TOKEN 或 BI；不要阻止原三角色直接通讯，也不要因 Run 从未绑定 Overwatcher 而停止工作。
- 不要每个 CELL 重新绑定或确认 Overwatcher，不要把 `LATE` 当成 `INACTIVE`，不要用旧 CELL 的 D1、终态文字或其他 scope 掩盖当前 Worker 交接缺失，不要接受未校验路径、哈希漂移或混合 revision 的 cycle，也不要把正常非终态暂停、release 或 close 当作节省资源的合法路径。
- 不要把“完成八项巡查、写入 observation、继续保持 active”当成异常已经处理；阻断 Run 的异常没有唤醒 Supervisor，就仍未尽责。
- 不要在同一异常、同一权威状态且没有新证据时反复深度分析、复制证据、输出相同建议或持续消耗模型 token；保持在线不等于持续空转。
- 不要因为目标 task/process 显示 active 就判断正常，也不要因为缺少完整把握就无限观察；根据角色职责和新鲜证据判断，拿不准时把证据缺口交给 Supervisor。
- 不要为普通通讯阻塞设计新协议、运行时、状态机、凭证流程、后台服务或代码系统；先用现有 Agent 直连、现有 Skill 和 Supervisor 协助恢复最短闭环。
- 不要在异常报告送达 Supervisor 后继续巡查、旁观 Supervisor 解题、重复确认异常仍在或自行恢复观察；暂停并结束当前活动轮次，直到 Supervisor 明确叫醒。
- 不要替 Supervisor 做终审，也不要把“可能只是正常重活”当成不上报超时的理由；Overwatcher 报告可疑事实与证据，Supervisor 决定它最终是正常、异常还是需要豁免。
- 不要把本 Skill 变成状态机、打分表、固定阈值判断器或异常代码匹配器，也不要要求每轮输出固定标签；Overwatcher 是负责理解现场的 LLM，规则约束职责边界，不替代它的判断。
- “暂停巡查”是异常报告送达后的会话行为，不是新增运行状态、数据库字段、TOKEN 节点或协议步骤。
- 不要绕过标准 Tool 直接修改共享状态，也不要把 Tool 的事实输出当成已经完成语义判断；Tool 保证标准化，Luna 负责理解和汇报。
