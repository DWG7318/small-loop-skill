# Observe a confirmed pause

仅中央已确认PAUSED时使用；REQUESTED不是停稳。保留原scope/native UNKNOWN，不伪造pending/start。

从中央最后RUN_PAUSED读原census/pause_id，沿原暂停operation取得准确Host/config，使用[标准生命周期取证命令](../../../docs/transport/SLK-TRANSPORT.md#run-lifecycle)生成本轮fresh quiescence；cycle只引用这份原件和原Host的路径/hash。

原admin现场重核当前同Run/pause/revision、全部旧调用和角色登记。全部确实静止才CLEAR；旧writer复活、身份漂移或缺证仍如实ANOMALY/UNKNOWN报告。施工暂停不暂停OW、20分钟核验或其他Run。
