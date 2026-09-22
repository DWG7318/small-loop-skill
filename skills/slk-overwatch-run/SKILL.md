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

1. Supervisor 与 Owner 确认是否启用、精确 Session、前台持续能力和 180–300 秒巡查间隔（建议 240 秒），确认 Run 的有效方法版本支持主动观察（历史 Run 先有 `adopt-method-contract` 回执），再用 `bind-overwatcher` 记录 `FOREGROUND_ACTIVE_TURN`、`foreground_turn_id` 与原生活动证据。无法保持同一 Agent Session 和前台 active turn 时判定未就绪。
2. 绑定后先完成首轮八项巡查并用 `record-overwatch-cycle` 留证；未有完整首轮时不开始新的派工或 TOKEN 交接。
3. 保持同一个前台 active turn，不结束当前 turn。每隔冻结的 180–300 秒由本 Session 主动开始下一轮；真实事件可提前触发，但不能替代下一次主动巡查。一次只运行一个巡查周期。
4. 一轮逾期时立即自检并报告 `OVERWATCHER_ACTIVE_DEGRADED`；连续两轮逾期、turn 结束或活动证据失效时报告 `OVERWATCHER_INACTIVE`，阻止新的派工/交接并唤醒 Supervisor，但不粗暴中断已在执行的 CELL。

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

- 每轮只追加一条紧凑 cycle：scope、TOKEN、最近事件/消息、八项结果、证据、开始/完成/下次时间和活动证明；不复制完整日志，不增加 CELL/D1/D2 进度。没有新鲜原生证据时记录“活动无法证明”。
- 只更新自己的 `last_cycle_at`、`next_cycle_at`、`cycle_seq`、`last_seen_event_id` 与 active 状态。正常轮次不发送可见状态消息，BI 只读投影这些已接受事实；Overwatcher 不直接改 BI。
- 异常时用 `record-observation` 记录精确 scope、异常代码、最后可信状态、缺失证据和责任角色。通讯未确认时调用 `$slk-recover-communication`：已有 start 即停止，否则对同一身份执行 exact retry 一次；语义变化、重试耗尽或身份冲突应唤醒 Supervisor。
- Run 正式终结后用 `close-overwatcher` 记录归档证据，停止前台 active turn 并归档本 Session；不要复用到下一个 Run。

## 负面提示词

- 不要创建 heartbeat；不要创建 automation；不要创建 cron；不要创建 Windows 计划任务；不要创建 daemon；不要创建 后台 Agent；不要创建第二个观察 Session。
- 不要用旧 running、旧 TOKEN、可见任务、自由文本、heartbeat 或定时唤醒冒充当前活动证据。
- 不要用提示词中的版本声明替代方法采用回执，也不要在未采用支持版本的历史 Run 上先绑定再补记录。
- 不要成为第四个工程角色、Router、消息总线或必经 relay；不要写 D0/D1/D2、计划、验收、角色替换、Owner 决定、TOKEN 或 BI；不要阻止原三角色直接通讯，也不要因 Run 从未绑定 Overwatcher 而停止工作。
