# Current admission parameters

仅构造/核对准入时读，采用现有合同，不添加准入轮次。

bootstrap验证中央初始登记和StartSlkRequest，建立真实pair identity后才冻结RoleHost、OW proof与标准adapter config。不能在工作流不存在时伪造identity/readiness，也不能用启动依赖未创建child形成循环。

- 450原生proof由Supervisor沿实际创建/查询记录形成，经 attest-subagent-overwatcher --request <json> --sha256 <hash> --evidence-root <dir> 验证。准确parent/child/currentactivation与原始采样不能替换成读者PID、parentturn或猜造childturn。
- slk.temporal-standard-adapter/v2保留现有attestation路径/hash字段，引用该proof；明确admission_kind=PRODUCT或ISOLATED_CONFORMANCE_SAMPLE及admission_path，同一当前binding/revision。普通PRODUCT不读历史conformance；开发样本仍走严格preflight-conformance-sample专用入口。
- 1200秒核验使用原start、--subagent-overwatcher-proof与--subagent-overwatcher-proof-sha256、新鲜中央projection。旧合同的attest-desktop-overwatcher/slk.desktop-overwatcher-attestation/v1及真实read_thread分支仅解释旧版本，不能要求450child套用Desktop线程。
- 未就绪/未知字段/混版/重复角色/缺OW拒绝派工；真实READY/IDLE才可开始。既有ACK或commit后缀沿原operation续接，不因为准入再启动接收者。

完整命令见[共享Temporal模板](../../../docs/runtime/SLK-TEMPORAL.md)，技术字段见[标准adapter合同](../../../docs/contracts/slk-temporal-standard-adapter.schema.json)。这里只定位已有入口，不让普通准备先读全部维修历史。
