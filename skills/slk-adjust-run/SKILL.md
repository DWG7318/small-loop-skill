---
name: slk-adjust-run
description: Use when an active Small Loop Skill (SLK) Run needs a Supervisor decision after repeated D1 failure, D2 findings, or changed resources.
---

# Adjust an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

由 Supervisor 选择一条能让 Run 继续的调整路线，同时保持计划、进度和未解决问题透明。

## 常见触发

- 同一 CELL 第二次连续 D1 FAIL，应停止普通返工并进一步拆分；
- 当前 D1 为 INCOMPLETE 且 Checker 已用闭合管理交接提交容量、环境、工具或原生执行阻碍；这不是产品 FAIL，也不要求先凑两次失败；
- D2 发现 CELL 之间的衔接问题；
- 当前固定角色能力、电脑、环境、依赖或独占资源与原计划差异较大；资源占用先按需读取 [`slk-execute-cell/references/resource-contention.md`](../slk-execute-cell/references/resource-contention.md) 恢复同一节点；
- CELL 变化已经影响后续 CELL、技术路线、验收目标或 Owner 需求。
- 同一项目留下多个独立初始化的 Run 身份，且 Owner 已明确 canonical/source Run ID；这时先取得闭合 Owner 证据与各 Run 精确快照，由 canonical 当前 Supervisor 使用 `reconcile-run-identities` 收敛身份，再按需使用 `adopt-method-contract` 显式采用当前合同。

## 建议选择

Supervisor 在现有工程权限和资源范围内给出能继续施工的具体方案。电脑、工具授权、账号或受控测试环境属于 Owner 掌握的资源时，由 Owner 授权后再变化；Supervisor 负责先把解决路线设计清楚，而不是把问题原样交回 Owner。

Supervisor 可以按实际原因组合以下办法：

1. 在现有权限内补充信息、资源或验证方式；INCOMPLETE明确选择等待、容量、环境或机械修复等处理，不依赖固定动作枚举或旧partial自动续审；先交已有报告，再由原角色执行明确行动；
2. D2 返工仍使用固定角色绑定；能力不足时调整 CELL 或路线，不由 Supervisor 临场升级、降级或替换模型；
3. 调整当前或后续 CELL、施工顺序或技术路线，让已验证成果继续被继承；第二次连续 D1 FAIL 时把未接受范围拆成多个中小后继 CELL，各自独立 D0、独立 D1，并保留原目标、验收强度和失败历史；
4. 解决方案需要 Owner 掌握的电脑、工具、账号、测试环境或业务权限时，提交推荐方案、预期影响、可行替代和最低必要授权；
5. 同一 CELL 经重新规划仍未收敛时，Supervisor 可以记录本 CELL 的豁免、实际影响和未来恢复条件，再把当前 Run 的后续 CELL 交还 Checker 继续推进。

这类豁免发生在 D1 返工边界，不是 D2。豁免作为独立结果保留，不改写为 D1 PASS。最终报告分别列出 D1 通过数和 Supervisor 豁免数。

## 更新与回到施工

调整通常保持原 Run 目标和已约定验收目标；Owner主动改变目标时，再更新相应定义。Supervisor 把原因、选择、影响、CELL n/N变化和未决风险写入根记录。

首次正式 D1 FAIL 可沿 `$slk-rework-cell` 给同一 Worker 一次普通返工。第二次及以后工具不代做拆分裁决；Supervisor 对两轮证据做 AGGRESSIVE 调查，用密封 `supervisor-admin revise-plan` 版本化拆分，冻结新 revision RoleHost，并更新标准 Temporal Run 配置的 Host 路径/哈希。计划调整沿 `Supervisor → Checker` 用 `SLK TOKEN` 和标准 `CELL_DISPATCH` 回到 `$slk-dispatch-cell`，再由 Checker 派首个后继 CELL；不能直接发给 Worker或开始第三次普通返工。原角色宿主核验 native start 并提交 TOKEN。结束处置前确认正确成员真实接手、OW 已恢复本 Run 巡查；否则保留明确未解决项和下一动作。

旧 Checker 端点的有限 aggregate budget/timeout 导致 INCOMPLETE，且 Supervisor 选择容量调整时，使用 `prepare-runtime-binding-migration` 按 [`slk-runtime-binding-migration.schema.json`](../../docs/contracts/slk-runtime-binding-migration.schema.json) 冻结同一角色、Session、模型、凭据、目标 RoleHost 与同一 Run Temporal config；Owner 明确冻结有限预算时不要迁移。Supervisor 先执行一次 `migrate-runtime-binding`，只在结果为 `RUNTIME_BINDING_REBOUND_AWAITING_PLAN_REVISION` 后执行既有 `supervisor-admin revise-plan`，再原样重放 `migrate-runtime-binding` 核验并发布目标 config。任一步失败或结果不匹配都保留 dispatch guard，不要派发下一 CELL；旧端点、历史 attempt 和结果不改写。

不要在线等待或持续介入普通 CELL；Overwatcher 只核实并报告运行证据，不能替 Supervisor 恢复成员、决定路线、修改计划、TOKEN 或 BI。INCOMPLETE 管理决定不能改写成 PASS/FAIL、普通返工或 Supervisor 代做 D1；同一 CELL 第二次正式 D1 FAIL 起，对照两轮 findings、candidate diff、实际步骤、复现/回归证据和环境假设做 `AGGRESSIVE` 调查，结果应进入版本化拆分或其他明确路线，不能只重复普通建议、接管 D1，或直接开始第三次普通返工。

不要按标题、最近时间或自由文本猜 canonical Run；不要直接编辑 SQLite、伪造凭证、新建替代 Run、用终态补造启动、自动升级模型，或借对账改写 CELL、D0/D1/D2、角色、证据和 TOKEN。参数变更只在已证实 PAUSED 后按原管理入口版本化；REQUESTED 不等于停稳，恢复不清故障 guard 或重做已完成工作。
