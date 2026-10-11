# 关闭操作（条件参考）

仅在封装 D2 开始/关闭请求、核对停稳 proof 或 Cargo lease 时读相应段。工程判断和关闭顺序以 `slk-close-run` 为准；精确机器字段的权威是原合同/消费者，不另造关闭协议。

## D2 的原请求

原 Supervisor 的密封 [admin 请求](../../../docs/contracts/slk-supervisor-admin.schema.json)使用 `operation=start-d2`；其 hash-bound operation file 仅绑定 `run_id`、`role_instance_id`、`binding_path`、`binding_sha256`、`source_attempt_path`。来源是当前冻结 RoleHost 与收到的原 D2_READY attempt，不猜 outgoing/recovery 目录。Host 核对原生 caller/start、计划/TOKEN/已提交交接；`D2_STARTED` 在实际开始时记录，重放不改时间。

组合回修后的 D2 再检查使用新收到的准确 D2_READY attempt 与当前冻结 Host，在实际开始时由同一标准入口记录属于该来源的一次开始；旧开始/失败历史保留，不复用旧来源的开始证明，不自己编 event ID，也不把重放同一开始当作新轮次。

## 当前 revision 的停稳与 close-run

沿原 [Transport 生命周期](../../../docs/transport/SLK-TRANSPORT.md#run-lifecycle)由 Host 生成 proof，不手写 JSON：

```powershell
slk-transport inspect-run-quiescence --binding <原Host绝对路径> --sha256 <哈希> --adapter-config <原Run配置绝对路径> --adapter-config-sha256 <哈希> --pause-id <本次唯一inspection-id> --output <新proof绝对路径>
```

确需排除当前协调调用时只加 `--coordinator-started <准确当前Supervisor的started.json>`，并通过原 current-thread/start proof。按原中央 `native_invocations`、construction/notification roots 与 output/continuation 子路径检查全部旧调用；OCRV launcher 退出不等于 executor 退出。缺证 UNKNOWN，QUIESCENT/exit 0 与 NOT_QUIESCENT/exit 3 如实保留。

原 `RUN_CLOSED` details 绑定真实 `terminal_snapshot_path/terminal_snapshot_sha256`、新 `quiescence_path/quiescence_sha256`、原 Temporal-enabled Supervisor 的 `close_binding_path/close_binding_sha256`。先 snapshot、末轮 OW/本 Run close-overwatcher，再取当前 revision census，最后密封 close-run；消费者核对全套原 native receipts。close-run 的中央写入与精确 workflow-pair 关闭都成功才缓存完成；中途失败重放同一原请求续后缀，不再做 D2 或新建关闭事件。

同一请求可安全重放；同 event ID 不得改内容。角色和 OW 凭据/端点/收据的操作按 `$slk-archive-members`，这里不维护第二份归档规程。

## 本 Run Cargo 清理

仅清此项目/Run 的精确 runtime/lease，参数读 `slk-cargo --help`。先核实 lease 的真实 owner、PID/创建身份及相关命令退出；活 owner 不清。旧 lease 缺精确存活证明时保留诊断与归档证据，不猜死、不删共享缓存根。原 `slk-cargo cleanup` 遇任何 lease 会拒绝，不绕过或扩大范围。不得删除源码 Git、提交、验收原件或共享 evidence。
