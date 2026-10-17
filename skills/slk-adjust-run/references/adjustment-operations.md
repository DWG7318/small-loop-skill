# 调整操作（条件参考）

只在发生下列迁移时读取相应小节。路线与工程语义由 `slk-adjust-run` 决定；此处不增加授权、审批或运行阶段。

## 旧 Checker 有限预算迁移

适用：原端点的有限 aggregate budget/timeout 导致 INCOMPLETE，Supervisor 已选择容量调整，且 Owner **未**冻结有限预算。不是自动升级模型或换 Session 的入口。

1. 按 [runtime-binding migration 合同](../../../docs/contracts/slk-runtime-binding-migration.schema.json)执行 `prepare-runtime-binding-migration`，冻结同一 Checker role instance、Session、模型、凭据、adapter/host、目标 RoleHost 和同一 Run Temporal config。普通 unlimited 值不改变 per-call token ceiling。
2. 原 Supervisor 执行一次 `migrate-runtime-binding`；只在 `RUNTIME_BINDING_REBOUND_AWAITING_PLAN_REVISION` 后执行已冻结的密封 `supervisor-admin revise-plan`。
3. 原样重放同一 `migrate-runtime-binding`，核对准确 revision/结果并发布目标 config。任何失败、半提交或不匹配保留 dispatch guard，不派下一 CELL；修复后续做原阶段，不换新 workflow pair。

保留旧 endpoint/Host/config 备份、attempt、结果和失败历史，不由迁移消费者写产品计划。命令与原请求字段按[Transport 的迁移说明](../../../docs/transport/SLK-TRANSPORT.md)定位，不猜写 JSON 或凭据。

## 历史 Run 身份收敛及合同采用

适用：同一项目已有多个独立初始化身份，Owner 明确 canonical/source Run ID。先取得闭合 Owner 授权证据及各 Run 精确快照，由 canonical 当前 Supervisor 使用 `reconcile-run-identities`；需要新方法语义时再显式 `adopt-method-contract`，分别保留真实收据。

不按标题、最近时间、摘要或自由文本猜身份；不能因对账改写 CELL、D0/D1/D2、角色、证据或 TOKEN，不能重建 Run、伪造凭证或用终态倒推启动。中途失败保留原请求/证据，只续未完成后缀。原公开入口与身份合同见 [Transport](../../../docs/transport/SLK-TRANSPORT.md)。

## D2 真实缺陷的尾部修复 CELL

全部原 CELL 已接受而真实 D2 FAIL 暴露组合缺陷时，Supervisor 可用既有 `revise-plan` 的 `d2_repair_cell_append`，绑定准确 `source_d2_failed_event_id` 与 `expected_plan_revision`，在最后 GO 尾部追加一个最小修复 CELL（`go_id/cell_id/ordinal/title/objective`）。保留原验收、失败、计划和 TOKEN 历史；不是重开已通过 CELL，也不以复测本身充作 CELL。新范围仍沿 Checker → Worker → Checker 完成真实 D0/D1，再做受影响的 D2。
