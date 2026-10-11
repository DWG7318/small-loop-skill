---
name: slk-record-run
description: Use when an active Small Loop Skill (SLK) Run needs its root record initialized or a member is preserving work and handoff facts.
---

# Record an SLK Run

仅用于已启用 SLK 的 Run。中央 SQLite 是事实，SLK-RUN-<RUN-ID>.md 自动导出；原始工程历史保留，TOKEN 只带当前责任与记录指针。初始化由 `$slk-manage-team` 一次完成，不因读本指引再创建 Run。

## 各写各的事实

- Worker：实际变化、候选、最低 D0、判断/风险、资源故障与恢复、交付对象。本地 D0 自修与正式 D1 返工分开。
- Checker：派发、原 Checker 显式 D1 决定或未完成、证据、CELL 推进与容量事实。不能从报告正文、零 finding、格式、严重度或退出码代判。
- Supervisor：启动交接、计划/角色调整、正式 REWORK_REQUESTED、豁免、D2、归档及最终结论；关键失败/决定及时写，可能被覆盖的证据先保存，不接管日常进度记录。D1_REWORK_DIRECTIVE 是该请求的传输载荷，不是另一次裁决。
- OW：只追加自己的真实性 cycle/状态，向所属 Supervisor 报告。唯一 child 可覆盖同一父级多 Run，各自技术 instance/scope/cycle/凭据独立；CELL 变化只更新 scope，不重绑 child。OW 不写工程进度、计划、角色、D0/D1/D2、TOKEN 或 BI。

## 怎么记录与交付

用本人显式标准 Tool 和可信消费者的密封权限追加事实，不手改库或自动导出，不借他人凭据。命令/退出码/摘要/关键失败定位与原件路径、字节数、SHA-256 形成紧凑 evidence index；大证据用 register-evidence，不复制大日志/全部令牌历史，不丢决定结论所需原件。原文读取无任意长度上限；区分实际执行、间接验证、推断和未证明项。

失败、返工、豁免与后续通过都追加保留。工具/环境故障不写成产品缺陷；代码未改或代理环境结果不冒充目标环境实测。

接收本轮先比较 TOKEN 编号/身份及 runtime revision；同号或旧号不改指针。发送者验证不可变 task file 和匹配 started.json 后，通过 commit-delivery-start 原子提交启动、TOKEN、事件和唯一 revision，不预写流转或以终态倒推启动。交接操作按当前角色子 Skill，不复制另一套流程。

业务及记录先完成，已有原始报告保存并独立投递；记录/ACK/Temporal 错误不扣报告，工程交接另核实真实启动与 TOKEN 提交，作为最后任务动作，随后结束。不等/不盯下一角色，保存不等于送达，送达不等于 PASS。Markdown 导出失败只 warning，不改变工程事实。

## 身份与只读边界

Owner、其他 Agent、BI/webBI 只通过 slk-bi-query 读投影。各 worktree 仍指向同一中央数据根，不另造记录权威。历史独立身份收敛或旧合同采用交 `$slk-adjust-run`，须 Owner 显式 ID/授权、准确快照与不可变回执；不能按标题合并、抹历史或声称文字升级。
