---
name: slk-grill-supervisor
description: Use when an active Small Loop Skill (SLK) Run has a newly assigned Supervisor who needs to demonstrate practical understanding before engineering begins.
---

# Grill the SLK Supervisor

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

确认 Supervisor 能用自己的话解释 SLK，并能把方法应用到当前 Run。这里检验理解，不追求固定题数或背诵原文。

## 问答方式

- 一次只问一个问题，根据回答继续追问。
- 问题数量随理解程度变化；清楚的回答可以快速通过，模糊回答值得继续澄清。
- 回答偏离时，先解释容易混淆的地方，再换一种问法确认。
- 问题结合当前 Run，让 Supervisor 说明自己准备怎样做。

## 建议覆盖

1. SLK 的适用范围，以及一个 Run、线性 GO、线性 CELL 的含义。
2. Supervisor、Checker、Worker 的职责和创建关系。
3. D0、D1、D2分别解决什么问题，以及检查如何减少重复。
4. CELL 大小怎样参考模型、电脑、累积工程量和余量。
5. Worker 与 Checker 的隔离、通讯和返工关系。
6. 通讯异常、成员异常、连续返工和 D2 发现组合问题时如何恢复施工。
7. 根 Run 记录由谁创建，各成员怎样记录和传输。
8. Supervisor 在哪些边界按需激活：启动、Checker升级求助、通讯或成员恢复、计划与豁免决定，以及全部 CELL 后的 D2 交接。
9. 日常 CELL 为什么由 Checker 与 Worker 直接推进，Supervisor 为什么按需激活；任何角色为什么不使用`wait_threads`或观察其他成员施工过程，并在交付后结束当前活动。
10. 收到 D2 交接后，怎样先检查 Run/GO、最终候选和端到端结果，再核对详细施工历史。
11. 面对允许误差或豁免时，怎样说明影响与剩余问题、安排补偿或后续 CELL；豁免不等于 D1 通过。
12. 什么情况可以由 Supervisor 在一次激活中解决后交还 Checker；确实需要 Owner 掌握的资源或业务权限时，怎样先形成推荐方案和最低必要授权请求，而不是把问题原样交回 Owner。

## 完成后

当 Supervisor 能稳定解释这些关系并给出当前 Run 的可行处理方式时，先使用 `$slk-record-run` 在项目根目录初始化本 Run 的共享记录，再使用 `$slk-manage-team`：Supervisor 创建 Checker，Checker 创建 Worker。
