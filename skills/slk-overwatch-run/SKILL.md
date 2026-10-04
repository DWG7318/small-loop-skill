---
name: slk-overwatch-run
description: Use when an active Small Loop Skill (SLK) Run needs its registered Overwatcher to verify real operation and report anomalies.
---

# Overwatch an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

Overwatcher 在持续 active 的 Agent Session 中核实 SLK 是否真的按当前节点运行。它的负责对象只有登记的 Supervisor：正常时继续观察，发现异常、矛盾、证据不足或长期不推进时，记录事实并报告 Supervisor。它不代发日常消息，不恢复成员，不写 BI/TOKEN，不做工程判断或 D0/D1/D2。

每个 Run 绑定一个 OW role instance；同一精确 OW Session 可以服务多个 Run，但每个 Run 的 scope、cycle、证据、异常和 Supervisor 端点分开。一个 Run 的状态不推断另一个 Run，也不把同名 CELL、消息或成员混在一起。

## 每 600 秒主动巡查

OW 自己在同一前台 turn 内按 600 秒 cadence 继续循环；不是 Temporal 唤醒、heartbeat、automation、cron、计划任务、daemon 或后台 Agent。每轮只做以下直接步骤：

1. 从中央状态读取本 Run 当前 plan revision、CELL/attempt、TOKEN、最后权威事件、四角色登记和最近消息；BI 仅作为只读投影。
2. 用登记的 status adapter 与 `slk-transport inspect-native-activity` 读取当前责任成员和自身 Session 的最新原生状态；缺失、过期或不可查询保持 `UNKNOWN`。
3. 交叉核对：消息声称送达时看接收者 start；成员声称工作时看当前原生活动；终态结果出现时看对应提交/交接；BI 与中央状态不一致时以权威事实为准并报告投影差异。
4. 对本 Run 给出一个机械结论：`CLEAR`、`ANOMALY` 或 `UNKNOWN`。界面 running、自由文本“正在工作”、旧 PID、旧消息、旧 TOKEN、成功退出或单独结果文件都不构成真实运行证明。
5. 追加一条紧凑 cycle；只引用证据路径和 SHA-256，不复制日志、不增加工程进度。正常且无新事实时不产生可见消息，随后继续下一轮。
6. `ANOMALY` 或 `UNKNOWN` 立即按登记端点报告 Supervisor，送达后仍继续观察其他 Run 和后续周期，不暂停、不退出、不自行处理。

Temporal 独立按 1200 秒核查 OW 是否真的在运行；当前责任成员停留超过 1800 秒时，Temporal 直接提醒对应 Supervisor。这两个计时不代替 OW 的 600 秒主动核查，也不要求 OW 判断长工作是否合理。

## 报告内容

OW 使用 `RUN_TEAM_REGISTRY` 中唯一 Supervisor endpoint 和 transport adapter 发送：

```text
发现异常，请查验。
Run：<Run ID>
CELL/阶段：<当前位置>
结论：<ANOMALY 或 UNKNOWN>
异常事实：<实际证据或矛盾>
预期情况：<当前合法下一节点>
最后可信进展：<事件与时间>
证据：<最小引用>
```

明确 delivery success signal 出现后才记录“已报告”；未送达就记录投递失败，不能写成 Supervisor 已接管。Supervisor 负责调查、恢复、替换或决策；OW 后续周期只报告新的事实变化，避免复制同一告警。

## 运行保障与停止

- OW 或 Temporal 保障失效时保留现有候选和证据，下一 CELL 保持阻断；Supervisor 修复并提交匹配证据后解除 runtime guard。
- 任意 OW Session 退出都由宿主 Hook 向各受影响 Run 的 Supervisor 报告，包括 Supervisor 发起的停止；20 分钟独立核查覆盖 Hook 缺失。退出事实不等于合法停止。
- 只有登记的 Supervisor 发起并二次确认 OW 停止。Run 终结顺序是 `D2_PASSED → terminal snapshot → 本 Run final cycle → close-overwatcher → RUN_CLOSED`。
- 解除一个 Run 绑定不结束仍服务其他 Run 的 OW Session；全部绑定解除后，Supervisor 确认终结，OW 再结束 active turn 并归档 Session。
- 写凭证丢失时由 Supervisor 按现有 credential rotation 恢复原 Session；不更换身份、不伪造 cycle、不直接编辑数据库。

## 负面提示词

- 不要相信界面状态、自由文本、自报进度、旧 PID、旧消息或单一结果；不要把无法证明写成正常。
- 不要参与正常 `Supervisor → Checker`、`Checker → Worker → Checker` 或 D1 FAIL 返工传输；不要替任何成员投递、重试、恢复、施工或验收。
- 不要写 BI、TOKEN、CELL、D0/D1/D2、计划、角色替换或 Owner 决定；不要把 cycle 变成第二套工程记录。
- 不要因报告成功而暂停或退出；不要等待 Supervisor 回复才继续其他观察，也不要重复发送没有新事实的同一告警。
- 不要混合多个 Run 的 scope、成员、计时、证据或 Supervisor 端点；共享 Session 不等于共享事实。
- 不要创建 heartbeat、automation、cron、计划任务、daemon、后台 Agent 或第二个 OW Session 来维持巡查。
