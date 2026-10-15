---
name: small-loop-skill
description: Use when one bounded engineering Run has a single serial CELL path suited to SLK.
---

# Small Loop Skill

SLK 4.5.3 是线性 Loop Engineering：一个 Run 直接包含顺序 CELL，适合中小工程或大工程的独立范围。仅 Owner 明确选择本方法后启用；不要按任务规模自动启动。

## 谁负责什么

- Codex Supervisor：Owner 确认的人选，负责方案、异常决策、正式 FAIL 的改进指引、豁免及最终 D2；也是现场临时补漏、核验与记录的第一责任人，不能以等待 SLK 源码修复代替可行的现场处置。可打破不适用的流程安排，但不伪造事实、借他人权限或接管 Checker D1。项目未结束时保持 active，以有界原生等待接收结果和 OW 报告，不退出等待自己的 child 唤醒。
- OCRV Checker：派发既定 CELL、隔离 D1、PASS 后推进下一 CELL；DSH Worker：施工当前 CELL、最低 D0、交候选。真实型号/reasoning 与原生端点必须登记，不以 Codex 对话冒充二者。
- OW：Supervisor 的唯一直属 subagent，覆盖其全部 Run，不跨 Supervisor 共用。每 Run 分开登记 scope/证据/观察凭据；用 Owner 确认的高效低推理开销模型，gpt-6-luna high/xhigh 仅推荐。持续 active，每600秒核验真实运行、记录自身观察、只向父级报告异常/疑似/UNKNOWN，报告后继续。只观察，不干预、不代发工程消息、不重试/修复，不写 BI/TOKEN/工程事实。仅所属 Supervisor 可决定并二次确认停止；单 Run 暂停/关闭不停止其他 Run 的观察。

时段仅建议（北京时间 UTC+8，不随时区变）：DSH 18:00–次日08:00，OCRV 22:00–次日08:00；Supervisor 与 Owner 按紧迫度商定启动时间，不作开工/派发门槛或到点停工要求。

## 准备与正常工作

先与 Owner 确认 Run 目标、最小合理工程、初始 CELL 与分层检查，再创建已确认 Supervisor。后者一次初始化 Run/根记录，轻量确认角色理解与既有 Eval，补齐成员登记、必要组件/Skill/权限、可见 BI、共享 Temporal 与本 Run 工作流、一次真实 OW ACTIVE 核验。只修真实缺项、复核变化；普通准备不现场编译、不重演历史全链，不等待首 CELL 或首 cycle。兼容更新/查新失败、未选择 RTK/Probe CLI/Ponytail 等可选增强只作提示，不挡基本准备。

准备 Goal 由 Supervisor 按需使用，只承载本次准备，不占用无关 Goal、不驱动整个 Run。基本条件闭合即结束准备（如用了 Goal，此时完成），再派首 CELL；不设固定准备分钟数、背诵、重复考试或首次施工成功门槛。未来项目真正必需的能力可由 Supervisor 补充，缺失仍要修复。

正常链：**Supervisor → Checker → Worker → Checker**。首个及重新规划后的派工经 Checker；D1 PASS 由 Checker 交精确下一 Required CELL，全部处理后交 D2_READY。正式 FAIL：**Checker → Supervisor → 同一 Worker → Checker**；Supervisor 只给绑定失败的整改指引。第二次连续 D1 FAIL 必须调查并细分尚未接受的范围，不做第三次普通返工。INCOMPLETE 是检查未完成，不是产品 FAIL，不计返工。

D0 是 Worker 交付前的基本信心；D1 是原 Checker 对完整候选的独立判断，初始输入不夹带 Worker D0 结论/推理；D2 是 Supervisor 对组合成果的最终检查。测试/复核/验收本身不列施工 CELL，不重复搭检验体系。CELL 按 DSH 实际能力、依赖和余量细分，不用统一数量、时长或容量定额。

## 共用事实与交接边界

中央 SQLite 是工程事实，SLK-RUN-<RUN-ID>.md 自动导出；成员只用自己显式认证的标准动作记录各自事实，BI/webBI 只读投影，OW 只写自身观察。记录追加，保留失败、豁免与原始证据；导出 warning 不改工程结论。长材料传准确位置、字节数、SHA-256，接收者按需完整读原件，不设任意字符上限或静默截断。

施工中同一 Run 只有一个当前有效 SLK TOKEN：单调编号及 Run/CELL/节点/接收者/候选/下一动作/根记录指针。相同或更旧 TOKEN 不重开工作。不可变 payload/task file 与匹配 slk.native-start/v2 确认真实原生启动后，原发送者的密封消费者原子提交 TOKEN/runtime revision；界面 running、文字、旧 PID、终态或发送成功都不是启动证明。

保存、投递受理、原生启动、工程判断、TOKEN 提交彼此分开。已有报告先原样保存并独立交出，不因格式、长度、退出码或 ACK/TOKEN/Temporal 错误扣留；不从正文、零 finding 或严重度代判 D0/D1/D2。业务与证据整理先结束，**真实交接及其必要原子提交是当次工程处置最后的任务动作**；Worker/Checker 随后结束本次激活，不交接后施工或盯接收者。Supervisor 交接后保持 active，使用有界原生等待，不接管普通 CELL。未闭合只续原交接，不重跑工程或新 ID 重发。Worker/Checker 不等待后继；所有角色不用后台自唤醒或 post-turn 延迟脚本。

Temporal 是一套共享 headless 服务、每 Run 独立 SLK.Start/SLK.Run；其1200秒独立核验 OW、成员责任停留1800秒直接提醒 Supervisor，不代替 OW 的600秒巡查。UNKNOWN 不等于退出，accepted 不等于已读/接管/修复；保障失效先修复再派下一 CELL，已有结果仍保存交出。故障优先机械恢复，由 Supervisor 决定并观察；不新增中继/管理底座。真实原件、权限、事务合同不得退回自由文本。

## 按情境只读当前指引

- Run 方案与初始 CELL：`$slk-plan-run`
- 明显独占资源：`$slk-guard-resources`
- Owner 的模型决定：`$slk-select-models`
- Supervisor 理解确认：`$slk-grill-supervisor`
- 当前团队与基本准备：`$slk-manage-team`
- 成员恢复/更换：`$slk-replace-member`
- 真实终态成员归档：`$slk-archive-members`
- 准备缺项排障：`$slk-troubleshoot-preflight`
- 正式施工异常排障：`$slk-troubleshoot-run`
- OW 主动核验与报告：`$slk-overwatch-run`
- 共享 Temporal 与每 Run 工作流：`$slk-manage-temporal`
- Supervisor 暂停/恢复施工：`$slk-pause-run`
- Checker 派工：`$slk-dispatch-cell`
- Worker 施工与 D0：`$slk-execute-cell`
- Checker 隔离 D1：`$slk-check-cell`
- 各成员记录：`$slk-record-run`
- 首 FAIL 普通返工：`$slk-rework-cell`
- Supervisor 调整/豁免/显式身份或版本采用：`$slk-adjust-run`
- 已有精确消息的恢复：`$slk-recover-communication`
- 最终 D2 与收尾：`$slk-close-run`

不是每个角色先读整套；仅随新情境补读对应指引及需要的参考。

## 负面提示词

不手改 SQLite、借他人凭据、猜角色端点或 canonical Run，不用标题合并身份或另造 Run 掩盖历史。同一实际 Run 续用 run_id；旧独立身份收敛/合同采用须 Owner 显式证据与不可变回执。不自动换模型、升级 reasoning 或 Session。

不将检验本身当施工 CELL，不把内部顺序段升级成 CELL/额外 D1/TOKEN 或并行 Worker。不把发送/零 finding/D0/间接验证当 D1 PASS，不把豁免当 PASS，不由 Supervisor/OW 代写 Worker/Checker事实。正常链由原责任人直接完成，不用补救或 OW relay 冒充正常成功。

不把经验数字、统一时间/大小、可选增强、历史演练或格式补交变成新门槛；保留必要授权、原生证据和验收。压缩续作后先回读中央 Run、计划、TOKEN、CELL/attempt 与下一动作，摘要冲突不串题。不新增作者私用脚本、隐藏代码路径、heartbeat/cron/daemon 维持角色；长期确定性能力走已文档化 Tool。

Supervisor 不发 final 后声称自己或 child 仍会持续工作。Owner 叫停优先；真实宿主中断如实记录，不能承诺 child 必会存活或唤醒父级。所负责范围全部收尾、OW 停止经确认后才能正常结束父级。临时恢复成功不是永久修复；产出成功不等于接收者能读，必须核验真实消费者。
