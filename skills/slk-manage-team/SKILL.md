---
name: slk-manage-team
description: Use when an active Small Loop Skill (SLK) Run is establishing, recovering, replacing, or retiring its registered role endpoints.
---

# Manage the SLK Team

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

在任何 CELL 开始前完成本 Run 唯一的团队登记与准备：Supervisor、Checker、Worker、Overwatcher 都有可验证的原生 Agent 身份、Session、设备、模型、端点、适配器、能力和生命周期；BI 已打开，Temporal 已就绪，必要通讯腿已由真实发送者和接收者演练。

## 建立成员组

Supervisor 由 Owner 明确确认；其余成员由 Supervisor 按计划创建或指定。创建不是登记的替代：`RUN_TEAM_REGISTRY` 分开记录 agent identity、runtime、session locator、message endpoint、transport/status adapter、delivery success signal、device identity、model/reasoning、Skill/工具版本和登记 revision，不凭标题、窗口名或历史位置猜测。

Owner 已授权本 Run 启动准备且准备未完时，Supervisor 先查询当前 Goal；核对并续用同一未完成准备 Goal，不重复建立。没有未完成 Goal 才创建；若已有其他任务的未完成 Goal，报告冲突，不占用或伪称完成。目标只到真实预检和首 CELL 交接，不是整个 Run。`$slk-plan-run` 已完成原对话 ↔ Supervisor 测试且身份/通道未变时复用结果，随后按顺序进行：

1. 打开可见 BI 1.1.0，绑定设备与当前 SLK Run 身份；核对实际安装路径/版本、原生模型权限下的工作区、Skill、OCRV、DSH 和工具。角色凭据由准备宿主通过 `prepare-role-credential` 认证、DPAPI 密封并重新用保存后的消费者认证，不能把 `credential-out` 的明文误当密封文件；确定性失败先纠正，不自动轮换全部凭据。
2. 登记 Owner 已确认的 Supervisor，并登记 OCRV Checker、DSH Worker 与 Supervisor 指定的 Overwatcher；四个 role instance 彼此唯一，模型和 reasoning 来自本 Run 冻结策略。
3. 用标准 headless 入口演练七条必要腿：`slk-conformance/<SLK-CONFORMANCE-run_id>` 证据根绑定独立 clean/no-remote 样本 Git 和单 CELL，经 `preflight-conformance-sample` 实走 `Supervisor → Checker → Worker → Checker`、FAIL 的 `Checker → Supervisor → 同一 Worker`、PASS 的 `Checker → Supervisor` 及 `Overwatcher → Supervisor`，再以 `seal-normal-chain-source` 密封。产品改走 `preflight-new-run`，核验初始 TOKEN、四角色/端点/消费者、BI、Temporal 和不同来源；预设 JSON/echo、假 D1/D2 或代发不合格。
4. 做角色理解确认：Checker 解释日常派发、隔离 D1、FAIL 上报与 PASS 后缀；Worker 解释施工、D0 与候选交付；OW 解释真实性核查、UNKNOWN 和只向对应 Supervisor 报告。回答模糊时先纠正再复测受影响项；Worker 不重复完整方法问答。
5. 使用 `$slk-manage-temporal` 得到共享服务和本 Run 两工作流的 readiness 收据；四角色、BI、Temporal 或必要通讯任一未闭合时保持 `NOT_READY`。

提示型角色绑定前通过 `SLK-ROLE-EVAL.v1` 八题。OCRV 没有任意提示/chat 入口，不伪造回答；用 `ocr llm test`、wrapper/capability哈希与隔离样本 headless preview/D1 作为等价证据，首次 review 前以 `runtime_root` + host + endpoint version 定位 stateless harness，实际 review Session 写入 native start/result。Supervisor 为每个 Run 绑定独立角色实例和 `FOREGROUND_ACTIVE_TURN`；同一精确 OW Session 可服务多个 Run，但 scope、cycle、Supervisor 端点分别登记，并固定 Agent/runtime/model/reasoning/native address 与 600 秒 cadence。它不是 heartbeat、定时任务或第四工程角色。

准备宿主用 `supervisor-admin` 注册并密封角色：Supervisor 凭据只注册 Checker 和绑定 OW；Worker 注册先验证 Supervisor，再只用密封 Checker 凭据写状态。随后冻结 Host 路径/哈希；凭据不进模型。身份或端点变化时追加 revision 并复测，Supervisor 替换回 Owner；准备 Goal 只认真实工具、权限、消费者、演练、OW/Temporal 和能力证据，不接受预设 JSON。

可恢复错误、一次失败、上下文压缩或未完成步骤不是完成理由：从最后可信进展做最小合法纠正并续接；不重复已完成工作、不盲目派发、不升级模型或新增后台自唤醒。恢复只读当前 Goal、简明准备记录和最新事实；记录已完成项、具体阻塞、最后真实动作、下一合法动作，不倒灌长历史。

仅全部预检通过、CELL01 原生启动与合法 TOKEN 互证、OW 已真实观察且无未闭合准备交接时，完成准备 Goal，Supervisor 随后退出常态在线。Goal 不是自动重启或宿主永不退出保证；工具不可用、缺权限或不能安全继续时如实报告，遵守宿主实际阻塞/预算/完成规则，不能擅自暂停或伪造完成。Owner 明确暂停／取消优先，已开始动作和证据保留；不把 Goal 扩到正常施工、D0/D1、返工、OW 或 D2。

正式工程成员对应已登记、可精确寻址并通过通讯测试的原生 Agent 端点；未登记端点的内部 subagent、隐藏执行或文字角色声明不作为正式成员。Overwatcher 使用单独 binding 与独立凭证，不要伪装 Supervisor、Checker 或 Worker。

成员创建或更换时，上一级用 `slk-state register-role` 或 `replace-role` 登记真实 Agent、模型、reasoning、session 与端点并领取一次性写凭证。团队、BI、Temporal 与通讯演练收据闭合后，Supervisor 用当前权威序列的下一枚单调递增 `SLK TOKEN` 把首个未启动 CELL 交给 Checker；恢复既有 Run 时先核实已有首轮施工、合法 TOKEN 与未闭合后缀，已有首轮交接不重派首 CELL。成员完成当前节点和必要交接后结束活动，不使用 `wait_threads`。Supervisor 不接收逐 CELL 噪音，只在 D1 FAIL、异常、规划决定或最终 D2 时激活。

## 恢复或接管

成员发生问题时，由现有直连和上一级成员优先恢复原成员；OW 只核实事实并报告 Supervisor，不代发施工消息或执行恢复。缺少回执不等于失效；创建接管成员属于确认原成员明确失效后的极端恢复：

- Worker 异常时，由 Checker 先恢复原 Worker，明确失效后再安排接管 Worker；
- Checker 异常时，由 Supervisor 先恢复原 Checker，明确失效后再安排接管 Checker；
- Supervisor 异常时，由原对话联系 Owner 并优先恢复原 Supervisor，明确失效后再协助建立接管 Supervisor。

明确失效可以依据任务 ID 不存在、平台显示失败或取消且无法继续，或者真实激活操作明确返回任务不可用。暂时没有回复不作为更换成员的依据。

接管成员可以先用 `slk-bi-query` 读取 Run、当前计划、候选和未完成交接，再进行双向通讯测试。恢复原成员时重发原令牌编号并复用原消息身份；只有同一角色实例的会话 rebound 时用 `slk-state rebind-session` 退役旧端点并保留凭证，密封 Supervisor 权限经 hash-bound `supervisor-admin` 消费。OW 的 Desktop endpoint 修正由该入口为同一 OW role instance 与同一 Session 追加更高 endpoint version；不能替换 OW、借用 OW 写权限或手改数据库。接管新成员确认后则用 `replace-role` 退役旧凭证与端点、保留退役旧记录，再把当前节点交给新任务 ID，使旧令牌失效并保留身份历史。

计划拆分后，用密封 `revise-plan` 写入新 revision 并冻结新 Host；首个后继仍走标准 `Supervisor → Checker CELL_DISPATCH`，不直派 Worker。

Overwatcher 的一次性完整写凭证丢失、或调用方误存非秘密 `overwatcher_credential_id` 时，不构成角色/Session/turn/binding 失效。当前 Supervisor 使用精确当前身份、revision 与哈希证据执行 `slk-state rotate-overwatcher-credential`；响应中的 `overwatcher_write_credential` 只显示一次，应立即保存并用 `authenticate-role` 验证。不要用 credential ID 认证、伪造 cycle/continuity violation、替换原 Session 或直接改数据库。

## 收尾归档

D2 通过后按 `$slk-close-run` 完成 terminal snapshot、OW final cycle、`close-overwatcher` 和 `RUN_CLOSED`。终态完整后，Supervisor 用 hash-bound `supervisor-admin close-role` 归档准确的 Worker/Checker，消费者内部调用 `slk-state close-role`；TOKEN、身份、终态或凭证不符即拒绝，凭据只在消费者内解封。成功仅追加 `ROLE_CLOSED`、令角色 `lifecycle=exited`、退役 `active endpoint` 并撤销凭证，不创建继任者、不移动 TOKEN、不改写 D1/D2/`RUN_CLOSED`；相同请求可重放。再用 `slk-bi-query roles` 确认二者均为 `display_state=archived`。Supervisor 保留。

`supervisor-admin close-overwatcher` 同时消费密封 Supervisor/OW 凭据：在 `D2_PASSED` 后、`RUN_CLOSED` 前记录本 Run 最后 cycle，再以同一 runtime revision 解除绑定。Session 仍服务其他 Run 时继续 active；全部解除后也在 Supervisor 确认停止及退出 Hook 二次回报后归档。更换与恢复保留旧绑定历史。

## 完成后

建立或恢复完成后，日常工作回到 Checker 与 Worker 的中断前节点，Supervisor 结束本次激活；收尾归档完成后，把结果交还 `$slk-close-run`。

## 负面提示词

- 不要把内部 subagent 或文字中的角色当成项目可见成员；不要只凭发出操作便声称创建、恢复或归档已完成；不要凭暂时无回复更换成员，也不要为防遗漏让 Supervisor 全程盯成员施工。
- 不要创建 Codex Checker 或 Codex Worker，不要用提示词把 Codex 对话伪装成 OCRV/DSH，也不要把已登记的 DSH、OCRV 原生端点误写成隐藏成员；不要用标题、角色名称或一次启动命令代替精确身份与真实激活证据。
- 不要把 D1 返工例外扩成 Supervisor 的一般 Worker 派工权，也不要用它绕过 OCRV 的 D1 或 Checker 通讯恢复。
- 不要缺少、重复绑定或混淆 Overwatcher；不要因共享 Session 就共享 Run scope、cycle 或 Supervisor 端点，也不要让它成为通讯中继、TOKEN 持有者、工程裁决者或 BI 写入者；不要用正时长 `wait_threads` 维持工程角色在线，也不要用 heartbeat/定时任务冒充 OW 的前台 active turn。
- 不要以 OW/脚本补救成功代替开工前由真实责任成员完成的必要通讯演练；不要在 BI、Temporal、工具更新或任一必需端点仍未证明时写 READY。
- 不要把计划归档、原生 Session 结束或发出命令当作已经归档；没有中央 `ROLE_CLOSED` 收据且仍显示 active/ready 时，应如实报告未归档，不能用自由文本覆盖事实。
