---
name: slk-manage-temporal
description: Use when an active Small Loop Skill (SLK) Run needs its shared Temporal service and per-Run continuity workflows prepared, checked, repaired, or closed.
---

# Manage shared Temporal

仅用于已启用 SLK 的 Run。Supervisor 管一套本地共享headless服务，每Run独立SLK.Start/SLK.Run pair及计时/恢复；不按Run另装服务/端口/数据库。Temporal保存通讯保障，不裁决工程、模型、角色、TOKEN或BI。

## 当前准入，不是工程演练

1. 核对登记地址/namespace/task queue、执行进程与持久库可达。以本Run准确角色、OW直属child、当前runtime revision构造已有StartSlkRequest，新Run方法450，旧Run用其显式合同；不猜版本/混绑定。
2. 标准worker用--standard-config-root，无须项目自写adapter。<run>.bootstrap.json核对当前初始登记，稳定RunID只创建一次pair，取得真实workflow identity。AWAITING_ADMISSION拒绝所有派工；PAIR_CREATED不等于READY。
3. identity存在后冻结RoleHost、<run>.json与OW proof。450用真实parent/child/current activation的slk.subagent-overwatcher-proof/v1；执行attest-subagent-overwatcher校验原件/hash，不假造child turn或用parent turn代替。
4. 普通PRODUCT用preflight-new-run及slk-temporal-admit的唯一slk.prepare_run，核验当前绑定一次OW ACTIVE，不要求cadence/cycle/首CELL。真实READY/IDLE才交readiness；同ID改参数不重建/覆盖。构造参数时读[准入字段](references/admission.md)。历史隔离样本/旧Desktop合同不加回普通准备。

## 交接、两种计时与故障guard

- 原角色经hash-bound continue-staged-handoff把原operation/message/双方/CELL/attempt/payload hash/revision交已绑定workflow。单个Activity唯一物理启动，Host不同时直发。匹配slk.native-start/v2后，原Host用原发送者密封权限提交中央TOKEN；已有HostACK只补commit，外部已有request绑定路径/hash只补原ACK+commit，不再启动。
- ACK超时只请求一次exact恢复，保持原发送者/接收者/payload，不重做工程。机械优先，Supervisor可选择并观察人工或机械修复，不把短RPCtimeout当工程turn死亡线。
- 接收者真实启动起算责任，达到1800秒独立直接通知登记Supervisor一次，只请排查；不判断有没有进展/长测试是否合理，不依赖OW。只扣已确认PAUSED的责任重叠时间，REQUESTED不扣，恢复不重置已用时。
- 每1200秒用inspect-native-activity核对准确OW当前原生证据及fresh中央projection；450用同一start+subagent proof/hash，旧版本沿旧Desktop分支。不以旧running、重读时间或自报续命。缺证UNKNOWN/guard不等于退出；恢复可信当前证据不强制重启child。
- 真退出沿宿主实际提供的原生观察/Hook与Temporal保障报告父级；文档存在不代表Hook自动注册。停止只有所属Supervisor二次确认。通知accepted不是已读/接管/修复，不套工程ACK/TOKEN，不承诺父回合结束后自动唤醒。
- Activity失败/无效证据/保障故障保持runtime guard，已有候选/报告保留交出，修复前不派下一CELL。一个Run的关闭/重放/计时不影响其他Run。

## 暂停、维修、结束

施工暂停走 `$slk-pause-run` 原密封入口：REQUESTED挡新工作，原结果/ACK/commit-only继续；PAUSED须全部旧调用停稳。原checkpoint v2可IDLE，不造pending。原operation/TOKEN/D0D1/故障guard都保留，恢复只续原pending；中央/Temporal半提交不变新失败恢复。OW巡查及1200秒核验继续。

健康看真实describe RUNNING且无close time，query可读或旧receipt不证明运行。Supervisor自主修复既有可逆故障；新增费用/账号/破坏性改变仍交Owner。运行代码漂移用hash-bound reload-temporal-worker保留pair；确为FAILED的两执行按[原闭合执行恢复](../../docs/runtime/SLK-TEMPORAL.md#closed-execution-recovery)保留历史/checkpoint、版本化恢复同Runpair，再重载新Host/config，不重发/重审/重置历史。

工程终结后关闭本Run SLK.Run与SLK.Start，仅取消该Run计时/待处理操作；共享服务仅在没有活动Run后由运维正常停止。服务/worker均headless，不弹控制台，准备BI仍可见。
