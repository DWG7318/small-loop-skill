---
name: slk-overwatch-run
description: Use when an active Small Loop Skill (SLK) Run has one Supervisor-selected optional Overwatcher Agent Session.
---

# Overwatch an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

旁路观察 Supervisor、Checker、Worker 的真实运行证据，在通讯未确认、活动无法证明、记录冲突或 Loop 无合法原因停顿时协助恢复或唤醒 Supervisor；原三角色的双向通讯、D0/D1/D2、CELL、TOKEN 与决策权保持不变。

## 观察与干预

1. 读取 `slk-bi-query`、不可变 transport evidence 和当前正式记录；不从旧 running/TOKEN/heartbeat 推断正在工作，不把 DELIVERED 当作 D1_ACCEPTED。
2. 正常工作、正式 PAUSED/BLOCKED/WAITING_EXTERNAL 无需噪音记录；出现异常时用 `slk-state record-observation` 追加封闭 kind、精确 scope 和证据引用。观察记录只说明运行事实，不增加 CELL/D1/D2 进度。
3. 通讯未确认时调用 `$slk-recover-communication`：先 inspect，已有 start 即停止；否则同身份最多 exact retry 一次。任何语义变化、重试耗尽或身份冲突都唤醒 Supervisor，不猜路线、不建替代成员。
4. BI 是只读投影。显示不一致时记录 `RECORD_CONFLICT` 或 `PROJECTION_REFRESH_REQUESTED`，让权威事实或投影刷新修正；Overwatcher 不直接改 BI。
5. 观察以真实事件通知为主；仅在平台需要时配置一个低频、Run 专属唤醒作为兜底。每次检查后结束 turn，不使用正时长 `wait_threads`、轮询循环、daemon 或常驻进程。
6. Run 正式终结后用 `close-overwatcher` 记录归档证据，关闭可选唤醒并归档本 Session；不要复用到下一个 Run。

## 负面提示词

- 不要成为第四个工程角色、消息总线或控制器；不要写 D0/D1/D2、计划、验收、角色替换、Owner 决定、TOKEN 或 BI，不要阻止 Supervisor/Checker/Worker 直接通讯，不要因 Overwatcher 缺席而停止 Run。
