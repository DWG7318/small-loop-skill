# Pause/resume request and proof

仅在构造或核对生命周期调用时读取。业务边界与次序以父 Skill 为准，字段以现有 `slk.run-lifecycle/v1` 合同为准，不另建协议。

- 外层为 `slk.supervisor-admin/v1`，operation=`pause-run` 或 `resume-run`，hash-bound 原件由密封消费者执行；凭据不进模型或普通 shell。
- 暂停 operation request：run_id、role_instance_id、唯一 pause_id、binding_path/binding_sha256、adapter_config_path/adapter_config_sha256、绝对 evidence_root、准确 coordinator_started_path（无该调用为 null）。绑定原 RoleHost、原 Temporal pair、原施工与通知 attempt roots，不扫其他 Run 或共享目录。
- 恢复 request 保留 pause_id，绑定现在的 Host/config，并增加原 pause_request_path/pause_request_sha256，使旧 roots 同时可查。换协调调用不能复用原豁免。
- 只有 REQUESTED、尚未 PAUSED 的暂停若决定撤回，仍走密封 `resume-run`，明确 `cancel_requested: true` 和撤回原因，保留原 pause_id 与原请求路径/hash；这是撤回未生效请求，不是证明已停稳或允许改参数，不伪造静止证明、不重置 TOKEN/责任时间、不解除其他故障保护。重复调用续同一原件，迟到的 PAUSED 不得重新暂停已撤回请求。
- proof 是不可变、路径/hash绑定的 `slk.run-quiescence/v1`；旧调用的真实原生终态/不再写证据均保留，不能以 transport completed、归档标签、adapter 名称或另一 Run 活动替代。执行入口见 [Transport生命周期](../../../docs/transport/SLK-TRANSPORT.md#run-lifecycle)。
- 原 checkpoint v2 可以合法 IDLE，无须伪造 pending。中央/Temporal 半提交都按自己的准确生命周期事件续后缀，不换请求绕过失败。

例：20分钟工作 + 60分钟已确认暂停 + 10分钟工作仍到30分钟提醒。成员在暂停中才接手，只扣其责任开始后的重叠时间；重复恢复不重置历史。
