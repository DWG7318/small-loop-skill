---
name: slk-pause-run
description: Use when an active Small Loop Skill (SLK) Run needs authorized construction pause, safe parameter changes, or resumption from its original node.
---

# Pause and resume construction

仅用于已启用 SLK 的 Run。只有 Supervisor 可授权暂停/恢复本 Run 施工；不抢 Worker/Checker 的 TOKEN，不暂停 OW、共享服务或其他 Run。模型与其他 Owner 权限、故障 guard 和验收要求保持。

## 请求不等于停稳

1. 保留原 Run/计划/runtime revision、TOKEN、全部 pending operation/message、候选、D0/D1、日志和 blocker。用自己的密封管理入口 `slk-transport pause-run --request <request> --sha256 <hash>`，保存原请求/hash。
2. `RUN_PAUSE_REQUESTED` 先挡新 CELL、新审查/返工派发，再设置原 Temporal 闸门。一侧失败仍停派。原结果、Checker→Supervisor 管理回传、ACK 与 commit-only 可闭合；原明确 D1 不撤回、不重审，下一步 operation 保留。
3. 核对本 Run **全部旧原生调用/writer**，包括旧端点、非 TOKEN 持有者、OCRV executor 与残留子进程；中央 native receipt 和原施工/通知两个 attempt roots 都要查。让精确调用到安全停点或自然退出，必要隔离须证明不能再写本 Run；没有通用 stop adapter，不猜 PID、不杀共享进程。
4. 缺原生结束/executor 证据或仍活动，保持 `SUPERVISOR_ADMIN_PENDING/pause_requested`，列出缺项，不能改参数或称已暂停。仅本次准确协调 Supervisor 调用可收尾，不豁免其他调用，也不把有真实终态的旧调用永远当活动。
5. 全部停稳才保存 hash-bound `slk.run-quiescence/v1`、中央 `RUN_PAUSED` 与原 Temporal PAUSED，回读同一 pause/event。只有成功最终收据缓存完成；半提交重试**原请求**补原后缀，不换 identity/revision，不重做工程。

构造请求和停稳 proof 时按需读 [生命周期字段](references/lifecycle-proof.md) 与[标准取证入口](../../docs/transport/SLK-TRANSPORT.md#run-lifecycle)。凭据仅在可信消费者内解封。

## 修改与恢复

已证明 PAUSED 后才版本化修改参数、端点或方法合同；不手改库/覆盖登记。Owner 决定型号变化，只复核受影响的团队能力和正常通讯，补救不算正常通过。旧 writer 已停、原 operation 可识别、OW/Temporal 保障有效后继续。

`resume-run` 保留同一 pause_id，绑定当前 Host/config 与原暂停请求。先确认 Temporal RESUMED，最后中央 `RUN_RESUMED` 释放闸门，再沿原恢复身份唤醒原 pending。一侧成功只补同一后缀；中央 PAUSED 时排队调用保留 pending，不转失败/超时、启动恢复或 busy-loop。

恢复原节点/operation，不重做工程/D0/D1，不重置 TOKEN、责任计时或解除真实 fault guard。成员30分钟只扣**已确认 PAUSED**与其责任区间重叠的时间；REQUESTED 不扣，重复 resume 不再扣。OW600秒巡查、Temporal1200秒核验及其他 Run 计时继续。

## 禁止混淆

停止派工、命令发出、UI标签或全局进程状态都不是停稳证明。暂停不是故障修复；Supervisor 不代写 Checker 决定。不丢原候选、交接或半提交，不宽泛绕过 stale revision。放弃沿原 RUN_ABANDONED/SUPERSEDED 路径，不假造 D2 PASS；不清其他 Run 的文件、计时或服务。
