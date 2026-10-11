# Current role credentials

构造/验证登记时才读本节。沿既有 prepare-role-credential 认证、DPAPI 密封、保存后的消费者 authenticate-role 复验；非秘密 ID 与 credential-out 未密封文件不等于可交给模型的凭据。

准备宿主沿 hash-bound supervisor-admin：Supervisor 权限注册 Checker、绑定 OW；Worker 注册先验证 Supervisor，再由已认证 Checker 消费密封凭据写状态。三个工程成员各用本人的一次性写凭证，OW用独立观察凭据，不伪装工程成员。密封权限只在可信 Tool 内解封，不放提示、公开包或普通 shell。

冻结当前 Host 路径/hash、角色/端点/revision，并复验保存后的实际消费者；确定性失败先纠正配置，不自动轮换全部凭据。登记变化追加 revision，旧记录保留，只复核受影响项。完整命令与闭合字段见[现有 Transport 合同](../../../docs/transport/SLK-TRANSPORT.md)，不用手写另一套协议。丢失/换Session/恢复用 slk-replace-member，不重跑整套准备。
