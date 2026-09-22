---
name: slk-manage-team
description: Use when an active Small Loop Skill (SLK) Run is establishing, recovering, replacing, or retiring its registered role endpoints.
---

# Manage the SLK Team

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

让 Supervisor、Checker、Worker 以登记的原生 Agent 端点存在；需要额外运行观察时，由 Supervisor 选择一个专属 Agent Session 作为可选 Overwatcher，并保持清楚的身份、端点、权限和归档状态。

## 建立成员组

推荐的创建关系是一条向下交接链。原对话创建 Supervisor；Supervisor 接管后的后续顺序如下。

`$slk-plan-run` 已完成原对话 ↔ Supervisor 通讯测试时，任务 ID 与通道没有变化就复用已记录结果，不重复测试。接着建议按顺序进行：

1. Codex Supervisor 启动并登记 OCRV Checker（Qwen3.8-Max），确认 `ocrv-checker` 精确端点可真实激活；
2. 完成 Supervisor ↔ Checker 的双向通讯测试；
3. 做一次 Checker 理解确认，让 Checker 用当前 Run 说明日常 CELL 派发、D1 隔离、CELL 一分为二、返工和激活 Supervisor 的边界；回答模糊时先解释再确认；
4. OCRV Checker 启动并登记 DSH Worker（DeepSeek V4 Flash），确认 `dsh-worker` 精确端点可真实激活；
5. 完成 Checker ↔ Worker 的双向通讯测试；
6. 验证 `Supervisor → Worker` 默认拒绝，仅绑定当前正式 D1 FAIL 的 `D1_REWORK_DIRECTIVE` 可达。

每个角色绑定前先通过 `SLK-ROLE-EVAL.v1` 中本角色的 8 个 runtime-critical 场景。若启用 Overwatcher，Supervisor 用 `slk-state bind-overwatcher` 绑定精确 Session 与端点：每 Run 最多一个、同一 Session 不跨 Run 复用，可以是 Codex 或其他可持续工作的 Agent；它不是第四个工程角色，也不改变上述三角色直连。未启用 Overwatcher 时 Run 正常开工。

相邻通道服务于正常工作；Supervisor 可协助恢复 Checker 通讯，但不绕过 Checker 直接派工。成员建立以运行时返回的真实身份、准确任务 ID 或会话 ID、精确角色端点和真实回复为依据；端点记录 Run、角色实例、原生地址与版本，成员或会话更换时登记新版并退役旧版。Worker 不重复完整方法问答；Checker 创建 Worker 时只交付其施工、最低 D0、记录和回传所需规则。

正式工程成员对应已登记、可精确寻址并通过通讯测试的原生 Agent 端点；未登记端点的内部 subagent、隐藏执行或文字角色声明不作为正式成员。Overwatcher 使用单独 binding 与独立凭证，不要伪装 Supervisor、Checker 或 Worker。

成员创建或更换时，上一级用 `slk-state register-role` 或 `replace-role` 登记真实 Agent、模型、reasoning、session 与端点并领取该角色一次性返回的写凭证。成员组与通讯通道建立后，Supervisor 用首枚 `SLK TOKEN T001` 把第一个待派发 CELL 和日常循环交给 Checker；成员完成自己当前 Loop 节点和必要交接后结束当前活动，不使用`wait_threads`也不读取其他成员内部状态。Supervisor 不接收逐 CELL 汇报，需要上级协助或最终 D2 时再激活。

## 恢复或接管

成员发生问题时，通常由现有直连和上一级成员优先恢复原成员；绑定的 Overwatcher 可旁路检查证据、协助一次 exact retry 或唤醒 Supervisor，但不自动接管。缺少回执不等于失效；创建接管成员属于确认原成员明确失效后的极端恢复：

- Worker 异常时，由 Checker 先恢复原 Worker，明确失效后再安排接管 Worker；
- Checker 异常时，由 Supervisor 先恢复原 Checker，明确失效后再安排接管 Checker；
- Supervisor 异常时，由原对话联系 Owner 并优先恢复原 Supervisor，明确失效后再协助建立接管 Supervisor。

明确失效可以依据任务 ID 不存在、平台显示失败或取消且无法继续，或者真实激活操作明确返回任务不可用。暂时没有回复不作为更换成员的依据。

接管成员可以先用 `slk-bi-query` 读取 Run、当前计划、候选和未完成交接，再进行双向通讯测试。恢复原成员时重发原令牌编号并复用原消息身份；只有同一角色实例的会话 rebound 时用 `slk-state rebind-session` 退役旧端点并保留凭证，接管新成员确认后则用 `replace-role` 退役旧凭证与端点，再把当前节点交给新任务 ID，使旧令牌失效并保留身份历史。

## 收尾归档

D2 通过且最终记录完整后，按准确身份归档 Worker、Checker 与本 Run 的 Overwatcher；Overwatcher 先记录关闭和归档证据，再归档自身 Session，绝不转给下一 Run。Supervisor 继续保留，方便 Owner 后续查询。

## 完成后

建立或恢复完成后，日常工作回到 Checker 与 Worker 的中断前节点，Supervisor 结束本次激活；收尾归档完成后，把结果交还 `$slk-close-run`。

## 负面提示词

- 不要把内部 subagent 或文字中的角色当成项目可见成员；不要只凭发出操作便声称创建、恢复或归档已完成；不要凭暂时无回复更换成员，也不要为防遗漏让 Supervisor 全程盯成员施工。
- 不要创建 Codex Checker 或 Codex Worker，不要用提示词把 Codex 对话伪装成 OCRV/DSH，也不要把已登记的 DSH、OCRV 原生端点误写成隐藏成员；不要用标题、角色名称或一次启动命令代替精确身份与真实激活证据。
- 不要把 D1 返工例外扩成 Supervisor 的一般 Worker 派工权，也不要用它绕过 OCRV 的 D1 或 Checker 通讯恢复。
- 不要强制创建、重复创建或跨 Run 复用 Overwatcher，不要让它成为通讯中继、TOKEN 持有者、工程裁决者或 BI 写入者；不要用正时长 `wait_threads` 维持任何成员在线。
