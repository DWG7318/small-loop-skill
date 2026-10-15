# Small truthful cycle

构造cycle或核对来源时读本节，不额外检查工程质量。

- inspect-native-activity 的 started 路径取原Host/transport结果，run_id/state-command取准确登记，保存 slk.overwatch-scope-inspection/v1 小收据。所有责任角色由admin重查本次窗口/权威范围与原生来源；Worker持TOKEN时使用同一 scope 返回的 worker_completion，不另查旧 started 覆盖当前续作，也不手填完成事实。
- DSH原绑定hook按分钟看真实registry，OCRV按原输入标记关联Session/实际executor；launcher存活不算审查。全工具探针的覆盖范围以实际返回为准，缺证UNKNOWN，不把局部绑定观测声称全Session采集。
- 自身采用登记的 slk.subagent-overwatcher-proof/v1，准确parent/child/当前activation与原始采样时间；旧Desktopattestation只解释显式旧合同。不复制对话、原日志或私密正文，存储预算不限制原件读取。
- 当前scope receipt 的 cycle_mechanics 给出 revision/计划/TOKEN/message/attempt；直接采用工具字段，路径/hash由真实文件计算，不手抄猜填。cycle引用本次scope、自身proof、可用started原件及同次Worker completion。原件可来自历史，但本轮实时查询不能复用旧样本、手填时间或用重读续命。
- CLEAR/ANOMALY/UNKNOWN是给Supervisor的报告结论，cycle没有顶层verdict。checklist仅CLEAR/ANOMALY/NOT_APPLICABLE；应查但缺证的项写ANOMALY并加ACTIVITY_UNPROVEN，不用NOT_APPLICABLE掩盖未知。探针原始error保留在scope原件和报告中，不塞进cycle的anomaly_codes枚举。
- native_liveness与checklist.active_session只描述OW自身。自己有当前IN_PROGRESS证据时，成员UNKNOWN不会把自己变成UNKNOWN/MISSING。native_liveness不接受UNKNOWN；自身缺证时不照抄IN_PROGRESS，也不改填MISSING冒充已证实失活。保留UNKNOWN观察并向父级报告，不能生成有效cycle就说明未记录及真实原因，等待父级恢复可信取证，不伪造字段使写入通过。
- 已证实 Worker 完成却缺交接时，stall_and_duplicates 必须为 ANOMALY，并保留 WORKER_COMPLETION_HANDOFF_MISSING 与 COMMUNICATION_RECOVERY_REQUIRED；不能只写异常代码却填 CLEAR。cycle 写入失败只证明记录失败，不抹掉观察到的异常，向父级同时报告事实与写入错误。
- overwatcher-admin仅在可信消费者内解封本角色凭据。端点纠正由当前Supervisor的supervisor-admin对同一role instance/child追加endpoint version，不因revision变化重绑OW；具体字段按[现有合同](../../../docs/transport/SLK-TRANSPORT.md)。

## 成员缺证、OW正常的例子

本例其余项目均已核实正常、Run尚未收尾，唯独Checker真实活动无法核实。将以下字段合入本轮cycle；其余身份/时间/证据用本轮原件，不照抄别人的值。实际未核实项目不能照抄CLEAR。

```json
{
  "native_liveness": "IN_PROGRESS",
  "checklist": {
    "run_position": "CLEAR",
    "role_bindings": "CLEAR",
    "direct_handoffs": "CLEAR",
    "cell_lifecycle": "CLEAR",
    "stall_and_duplicates": "ANOMALY",
    "bi_projection": "CLEAR",
    "active_session": "CLEAR",
    "terminal_closure": "NOT_APPLICABLE"
  },
  "anomaly_codes": ["ACTIVITY_UNPROVEN"]
}
```

向父级报告“发现异常，请查验。Checker真实活动UNKNOWN，原始错误OCRV_NATIVE_SESSION_UNPROVEN；OW自身IN_PROGRESS”，附准确Run/CELL/attempt/message及scope路径/hash。缺证不等于停机或已证实空转；照常继续巡查，不代修。
