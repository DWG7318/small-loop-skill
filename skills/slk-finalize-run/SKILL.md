---
name: slk-finalize-run
description: Use when an SLK Run already has its real final acceptance or termination decision and needs remaining closeout or archive steps completed.
---

# Finish an accepted SLK Run

仅用于 Owner 已选择 SLK 的 Run。原创建 Supervisor 负责本 Run 收尾。先读准确 Run、已有 D2/终止结论、原请求和成功回执；不重做准备、施工、D0/D1/D2，不以网页隐藏代替关闭。

## 只续尚未完成的部分

1. 沿 `$slk-record-run` 保存一份重要结项总结：成果、重要问题与现场措施、实际结果、剩余事项和必要来源。会推进 runtime revision 的工程记录先完成，再冻结 terminal snapshot；不能让新记录使已有末轮证明失配。
2. 对应终态快照主动请求原 OW 的真实 final cycle，不等下个600秒点。沿 `$slk-archive-members` 只解除本 Run 的绑定；真实已结束 child 走合法 ended-child 分支，不伪造末轮。历史从未绑定的 Run 跳过 OW 步骤，不能用此免除新 Run 的必要 OW。
3. OW 解绑改变 revision 后，沿 [现有关闭操作](../slk-close-run/references/close-operations.md)取得当前 `inspect-run-quiescence`。当前准确主管协调调用与旧调用分开，活跃/UNKNOWN writer 由 Supervisor 定向排障；不猜停止或全局 kill。密封原 `RUN_CLOSED`，再确认精确 `SLK.Run/SLK.Start` pair 的实际 COMPLETED 与 close time；只有两部分都完成才认该操作成功。
4. 中央终态后按 `$slk-archive-members` 对准确 Worker/Checker `close-role`，读回中央收据、`lifecycle=exited`、`display_state=archived` 及无 active endpoint。保留 Supervisor 对话、历史 TOKEN、候选和原件；不造 TOKEN_CLOSED 事件。只处理本 Run 确需释放的资源，在用或可安全保留的缓存不作为关工前提。
5. 读回桌面 BI 中本 Run 的已归档状态与总结，再单列云端保存结果。源未关闭就修关闭原因，不能要求 BI 隐藏；断网保留待上传，BI 下次打开续传，不重开工程，也不谎报云端成功。
6. 向 Owner 简报真实完成与未完成项、验收/豁免、限制和记录位置。不把「工程通过」「方法关闭」「本地归档」「云端已保存」混成一个完成状态。

## 重入、共享与停止

半提交保留原 event/operation ID、native identity、不可变请求和成功部分，只续未完成后缀。同一通知已投达但缺回执，用 `$slk-recover-communication` 消费原回读，不重发、不重验。相同已解释告警并入已有现场处置，新事实仍核验，不为周期提醒反复施工。

共享 OW 可能覆盖同一 Supervisor 的其他 active/PAUSED Run；解绑一个 Run 不停 child，Temporal 只关本 Run pair，不关闭共享服务。只有全部适用范围收尾后，所属 Supervisor 才可决定并二次确认 child 停止；父级此前保持 active，不 final 退出等待自己的 child 唤醒。

真正缺证保留未完成并明确下一动作。放弃/撤销沿原 `RUN_ABANDONED`/`SUPERSEDED` 合同，保留真实失败/豁免；暂停不是结束。无需为收尾新建 CELL、工作簿、角色或固定时间/资料大小门槛。
