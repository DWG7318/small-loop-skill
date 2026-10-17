# 正式运行异常：按原因取用

这些是既有合同的定位线索，不是新的恢复流程或自动裁决。适用于当前已登记的 SLK；4.4.x 历史按原合同读取，4.5.x OW 使用同 Supervisor 唯一直属 child 的原生 proof。只读相关小节；原角色权限、原请求/hash 与候选不变。

## 报告已保存，但交接未闭合

可能是尚未投递、已受理无 start、已有 start 无中央提交，或只缺回读；不能只凭界面归成同一种重试。

用原发送者登记的 endpoint/envelope/attempt root 只读定位：

```powershell
slk-transport inspect --endpoint <原endpoint> --envelope <原envelope> --attempt-root <原attempts根>
slk-transport inspect-native-activity --started <准确原started.json>
```

核对 Run/CELL/attempt/message、payload/native-request hash 和当前 TOKEN；需要 completed/failed 时只引用同一调用的原件。后续只按 `$slk-recover-communication` 选择原样一次重试、回读或缺失提交后缀；这里不复制操作规程。匹配 start/提交出现后只读复用，不新建 message、改 endpoint 或重做施工。无原投递则先恢复准备条件，不制造消息来套恢复。

## 原生状态 UNKNOWN / 成员疑似失活

Worker 原生返回只有进度/checkpoint、没有可验收候选时，保存原报告并直接交 Supervisor 处置，不进入 Checker D1、不提交候选 TOKEN；已封存的旧投递按原地址续交，不改写消息。服务商明确 429/拒绝与证据缺失是运行事实，不改判 D1 FAIL。OCRV 读取外部 D0 原件须使用证据目录中的准确路径与哈希；缺件记 UNAVAILABLE，不用一份新清单冒充已读。

先核对当前精确登记/native start/最新真实采样时间与原调用结束或 executor 证据。旧 running、重读时间、其他 Session、OCRV launcher 退出均不能补缺证。保留最后可证动作及 UNKNOWN 原因；Supervisor 按 `$slk-replace-member` 选择恢复/替换，不猜 PID 杀进程、不借他人凭据。修复后核实同一目标的真实启动/端点/职责与必要通讯，只重验改变部分。

## TOKEN、候选或 revision 对不上

重读同一 Run 的中央 query、当前计划/RoleHost、原请求和已记录交接。区分旧摘要、在途原子提交、合法新 revision 与真实冲突，不直接编辑 SQLite、覆盖候选或换新 Run。需要变更时先 `$slk-pause-run` 证明全部旧调用停稳，再沿原版本化入口；部分提交保留原 operation/event/native identity，续未完成后缀，修复事实后再确认当前唯一 TOKEN。不把 REQUESTED 当 PAUSED，也不靠 resume 清故障 guard。

## 资源占用

只在锁/独占资源阻塞当前命令时读[资源恢复](../../slk-execute-cell/references/resource-contention.md)。定位实际占用者，优先已有隔离与同节点继续；不能证明 stale 就不删除，不杀无关进程、不绕到下一 CELL。这是环境事实，不自动成为 D0/D1/D2 FAIL。该参考保有资源取证、恢复及回退的唯一操作说明。

## OW / Temporal 保障失效

Supervisor 核对本 Run 当前绑定、原生 parent/child/当前激活、真实 cycle 时间与原工作流 pair 的实际 status/close time；query 可读不等于 workflow 运行，另一个 Run 正常不掩盖本 Run UNKNOWN。沿 `$slk-overwatch-run` / `$slk-manage-temporal` 的原生证据、同 Run 恢复及 guard 操作，不重新创建 child/pair 来遮住未知。可信证据恢复不必强制重启 child；保障恢复前不派下一 CELL，已有报告照常交出。共享服务及其他 active/PAUSED Run 不停，OW 报告后继续。未知是待定位，不是死亡/修复成功。

## 暂停或关闭只成功了一半

暂停/恢复按 `$slk-pause-run` 保留中央/Temporal 成功部分与原请求，从同一 operation 继续；D2/末轮 OW/Run close/角色归档按 `$slk-close-run` 原顺序只补未完成后缀。不重跑验收、不变 event ID、不把中央终态写入或 planned archive 当作清理完成。回读原最终收据及精确原生目标才报告完成；否则列明真实已做/未做和下一动作。

## 证据不符合任何预案

交 Supervisor 真实已知/未知、原件位置、影响和最小可逆取证建议；允许继续按实际原因定位。修复无效就保留结果、改变路线，不盲目重复旧方案。需要 Owner 权限则说明推荐路线与最小授权；不得把未知变成新统一门槛。记录已验证的原因/动作/结果/版本与必要回退，未验证建议不写成已修复。
