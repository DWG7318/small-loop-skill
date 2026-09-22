---
name: slk-overwatch-run
description: Use when an active Small Loop Skill (SLK) Run has one Supervisor-selected optional Overwatcher Agent Session.
---

# Overwatch an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

用一个专属 Overwatcher Agent Session 的前台 active turn 全程旁路观察 Run；它主动巡查、记录运行事实、协助原样通讯恢复并在需要语义决定时唤醒 Supervisor，但不接管 Supervisor、Checker、Worker 的双向通讯、工程职责、D0/D1/D2、CELL、TOKEN 或 BI。

## 启动与持续活动

1. Supervisor 与 Owner 确认是否启用、精确 Session、前台持续能力和 180–300 秒巡查间隔（建议 240 秒），确认 Run 的有效方法版本支持主动观察（历史 Run 先有 `adopt-method-contract` 回执），再用 `bind-overwatcher` 记录唯一 `binding_revision`、canonical task、`FOREGROUND_ACTIVE_TURN`、`foreground_turn_id` 与原生活动证据。一个 Run 只绑定一次，不是每个 CELL 重新确认；CELL/attempt 只改变 cycle scope。
2. 绑定后先完成首轮八项巡查并用 `record-overwatch-cycle` 留证；每轮绑定一个权威 `runtime_revision`，其中 TOKEN、最近事件与消息不要来自不同读取时刻。关键 evidence reference 使用绝对路径、现存字节与匹配 SHA-256；未有完整首轮时不开始新的派工或 TOKEN 交接。
3. 保持同一个前台 active turn，不结束当前 turn。可在本进程调用一次有界 `slk-state wait-for-change`，revision 变化便立即巡查，TIMEOUT 则按冻结的 180–300 秒间隔开始下一轮；这不是 heartbeat、定时任务、daemon 或 detached helper，一次只运行一个等待/巡查周期。
4. cadence health 与 native liveness 分开：逾期只记录 `LATE`，LATE 不等于 INACTIVE；只有精确原生状态为 `COMPLETED`、`MISSING` 或 `MISMATCHED` 才用 `record-overwatcher-status` 打开 `OVERWATCHER_CONTINUITY_VIOLATION`，阻止新的派工/交接并唤醒 Supervisor，但不粗暴中断已执行的 CELL，也不凭旧 running 或可见任务反向恢复 ACTIVE。

## 每轮固定八项巡查

1. 当前 Run、计划版本、CELL/attempt、TOKEN 序号/持有者与最近权威事件。
2. Supervisor、Checker、Worker、Overwatcher 的冻结身份、Session、端点与原生执行证据。
3. 角色之间待交付消息及 sent/delivered/received/started 证据。
4. CELL 的派工、执行、D0、D1、返工与关闭状态；DELIVERED 不能冒充 D1_ACCEPTED。
5. 无合法理由的停顿、重复派工/验收/返工、旧消息重做、端点漂移或重复 Run。
6. BI 只读投影与权威状态是否一致；不一致时只请求事实或投影刷新。
7. 自身 Session、前台 active turn、间隔与周期不重叠证明。
8. Run 是否正式终结，以及停止观察和归档义务。

## 记录、更新与报告

- 每轮只追加一条紧凑 cycle：binding/runtime revision、scope、TOKEN、最近事件/消息、八项结果、证据、native liveness、cadence health、开始/完成/下次时间；可选 cost metrics 只记录，不参与派工或模型选择。没有新鲜原生证据时记录“活动无法证明”；不复制完整日志，不增加 CELL/D1/D2 进度。
- 只更新自己的 cycle、原生状态和 continuity incident。正常轮次不发送可见状态消息，BI 只读投影这些已接受事实；Overwatcher 不直接改 BI。
- 异常时用 `record-observation` 记录精确 scope、异常代码、最后可信状态、缺失证据和责任角色。通讯未确认时调用 `$slk-recover-communication`，可协助一次 exact retry；语义变化、恢复耗尽或身份冲突应唤醒 Supervisor。
- Run 正式终结后完成最后一轮，再用同一 `runtime_revision` 和最后一轮 cycle ID 调用 `close-overwatcher`，停止前台 active turn 并归档本 Session。开放 Run、普通 CELL 边界不要关闭、暂停或释放；计划更换需引用最后一轮，意外失活则保持 `CONTINUITY_RECOVERY_REQUIRED`，只有 Supervisor 带明确证据执行 recovery replacement 后才恢复 ACTIVE。不要复用到下一个 Run。

## 负面提示词

- 不要创建 heartbeat；不要创建 automation；不要创建 cron；不要创建 Windows 计划任务；不要创建 daemon；不要创建 后台 Agent；不要创建第二个观察 Session。
- 不要用旧 running、旧 TOKEN、可见任务、自由文本、heartbeat 或定时唤醒冒充当前活动证据。
- 不要用提示词中的版本声明替代方法采用回执，也不要在未采用支持版本的历史 Run 上先绑定再补记录。
- 不要成为第四个工程角色、Router、消息总线或必经 relay；不要写 D0/D1/D2、计划、验收、角色替换、Owner 决定、TOKEN 或 BI；不要阻止原三角色直接通讯，也不要因 Run 从未绑定 Overwatcher 而停止工作。
- 不要每个 CELL 重新绑定或确认 Overwatcher，不要把 `LATE` 当成 `INACTIVE`，不要接受未校验路径、哈希漂移或混合 revision 的 cycle，也不要把正常非终态暂停、release 或 close 当作节省资源的合法路径。
