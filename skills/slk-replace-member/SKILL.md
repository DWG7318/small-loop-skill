---
name: slk-replace-member
description: Use when an active Small Loop Skill (SLK) Run must restore a registered member, rebind its session, or replace a demonstrably unavailable member.
---

# Restore or replace a member

仅用于已启用 SLK 的 Run。Supervisor 负责本 Run 可逆修复；更换 Supervisor 必须由 Owner 确认。没有回复、证据 UNKNOWN 或凭据丢失本身都不是成员失效。

## 先恢复，再决定是否替换

1. 从中央状态和准确原生端点核对当前成员、计划、TOKEN、候选、未完成 operation 与最后真实进展；保留原件。Worker 由 Checker 优先恢复，Checker 由 Supervisor 优先恢复；Supervisor 故障由原对话联系 Owner。OW 只报告，不承担修复。
2. 已有精确消息但缺接收证据，转 `$slk-recover-communication`，不重做工程。需要修改运行参数时，先沿 `$slk-pause-run` 证明受影响 Run 已停稳；REQUESTED 不等于 PAUSED。
3. 原成员可以继续，就保留身份和原 operation。恢复原投递复用原令牌编号与消息身份，已有 native start 只续未完成后缀。任务确实不存在、平台明确失败/取消且无法继续，或真实激活返回不可用，才考虑新成员。
4. 接管者先只读 Run、计划、候选和未完成交接；按 `$slk-manage-team` 完成受影响角色的简明定位、Eval/理解确认与当前能力核对。端点改变只验证受影响的正常直连，不用补救成功代替正常可用。

## 版本化变更

- 同一角色实例的 Session rebound 用密封 `supervisor-admin rebind-session`：退役旧端点、保留凭据和历史。OW 只允许同一直属 child、role instance、adapter、Host 的端点纠正，追加更高 endpoint version；不能借此跨 Supervisor 或更换 OW。
- 确认新工程成员后由合法上游用 `replace-role` 退役旧凭据/端点并保留旧记录，再把当前节点交给新实例；不是 OW 更换入口。角色/模型选择仍遵守 Owner 权限，不静默覆盖登记或自动升级模型。
- 真正更换直属 OW 用密封 `supervisor-admin` 的 `replace-overwatcher`：原请求绑定当前父级、旧 binding revision、新 child/role/proof，`issued_role=overwatcher`、新 instance 和密封目标必须一致；不先 close 再 bind、不复用旧凭据。新 child active 不等于中央已更换。若提交成功后响应/密封/收据失败，保留同一 operation 原件/hash/event 重入，仅补缺失密封认证后缀；不第二次换员。已有密封件损坏时保留它，显式选新密封目标/结果路径再续原 operation，不覆盖或伪造认证成功。逐 Run 更新受影响绑定，不中断其他 scope。
- 计划拆分用密封 `revise-plan` 追加 revision 并冻结新 Host；首个后继仍由 Supervisor → Checker `CELL_DISPATCH`，不是直接派 Worker。
- OW 完整写凭据丢失、误存非秘密 `overwatcher_credential_id` 时，由当前 Supervisor 对准确身份/revision/hash 执行 `rotate-overwatcher-credential`。一次返回的 `overwatcher_write_credential` 立即密封保存并由消费者 `authenticate-role` 复验；不是重建 child 或伪造 cycle 的理由。

凭据只由可信消费者解封。登记与凭据细节按需读 [角色管理合同](../../docs/transport/SLK-TRANSPORT.md)，不手改 SQLite。修改后保留修复事实、旧版本和实际复验结果；只闭合原节点，不丢候选、D0/D1 或失败历史。

## 不做什么

不凭标题猜端点，不凭一次创建命令声称接管完成，不因暂时无回复换人。不增加角色、第二 Worker/Checker 或常驻恢复代理；不让 Supervisor/OW 补写 Worker/Checker 工程事实。新增范围、费用、账号或破坏性变化仍交 Owner。
