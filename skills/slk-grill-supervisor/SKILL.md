---
name: slk-grill-supervisor
description: Use when an active Small Loop Skill (SLK) Run has a newly assigned Supervisor who needs to demonstrate practical understanding before engineering begins.
---

# Grill the SLK Supervisor

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

用版本化封闭 Eval 确认 Supervisor 对当前 SLK 语义的理解，避免仅凭自由文本、自称理解或不同项目里的临场解释进入施工。

## Eval 方式

- 使用 `small-loop-skill/assets/SLK-ROLE-EVAL.v1.json` 中 Supervisor 的 8 个 runtime-critical 场景；响应要绑定当前 Run、project、plan revision、角色与 case-pack SHA-256，并通过 `scripts/validate_role_eval.py`。
- 缺题、多题、重复题、错角色、错答案、错 schema/hash、大小写或首尾空白变体、旧 plan revision 都失败关闭；“我理解了”不替代结构化答案。
- 失败时只解释对应易错规则，再生成同一版本 Eval 的新响应；不新增 Agent、不扩成开放式长问答。完整 40-case pack 是版本发布门禁，运行时只付 8 题成本。

## 建议覆盖

1. SLK 的适用范围，以及一个 Run 直接包含线性 CELL 的含义。
2. Supervisor、Checker、Worker 的职责、原有双向通讯和可选 Overwatcher 的只观察边界。
3. D0、D1、D2分别解决什么问题，怎样优先复用现有入口和有效客观证据、减少重复，以及检查工具故障为什么不等于产品缺陷。
4. CELL 大小怎样参考模型、电脑、累积工程量和余量；本 Run 涉及 Cargo 或其他明显独占资源时采用什么隔离、恢复与清理安排。
5. Worker 与 Checker 的隔离、通讯和返工关系。
6. 通讯异常、成员异常、连续返工和 D2 发现组合问题时如何恢复施工。
7. 根 Run 记录由谁创建，各成员怎样记录和传输。
8. Supervisor 在哪些边界按需激活，以及 Overwatcher 何时只做原样重试、何时转交 Supervisor。
9. 日常 CELL 为什么由 Checker 与 Worker 直接推进；任何角色为什么不使用正时长 `wait_threads`，旧 running/TOKEN/heartbeat 为什么不证明活跃。
10. 收到 D2 交接后，怎样先检查 Run 目标、各 CELL 结果、最终候选和端到端结果，再核对详细施工历史。
11. 面对允许误差或豁免时，怎样说明影响与剩余问题、安排补偿或后续 CELL；豁免不等于 D1 通过。
12. 什么情况可以由 Supervisor 在一次激活中解决后交还 Checker；确实需要 Owner 掌握的资源或业务权限时，怎样先形成推荐方案和最低必要授权请求，而不是把问题原样交回 Owner。

## 完成后

Eval 对当前 Run 与 plan revision PASS 后，先使用 `$slk-record-run` 初始化共享记录，再使用 `$slk-manage-team`：Supervisor 创建 Checker，Checker 创建 Worker；角色或 plan revision 变化后重新绑定并复测，不静默沿用旧结果。
