---
name: slk-recover-communication
description: Use when an active Small Loop Skill (SLK) Run has an exact delivery without matching native start evidence.
---

# Recover SLK Communication

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

区分保存、受理、真实接收启动、工程判断与TOKEN提交；恢复已有通讯，不审核报告，也不重新施工或审查。沿原发送者的原有直连恢复，Overwatcher不做必经 relay，只报告事实，Supervisor处理真实异常；保障失效时不派下一CELL，但已有结果照常交出。

## 恢复顺序

1. 用 `slk-transport inspect`、`inspect-native-activity` 与只读状态核对准确Run/CELL/attempt/message_id、角色实例/endpoint version、payload SHA-256 与 native-request SHA-256。未知、过期、冲突保持UNKNOWN；保存、可见文字、终态、旧PID或TOKEN不是接收启动证明。
2. 已有普通、精确重试或Desktop桥接的匹配 `started.json` native start，沿同一 `message_id` 和同一 candidate/message/attempt 读取，不重复发送。旧Host回执或暂存交接存在时先核对原端点/信封及真实接收证据；证明不足报未确认，不能换新消息掩盖；不 handoff、不重复激活。
3. 确认原投递无启动且目标空闲时，`retry-exact`最多原样重试一次；保留原失败与恢复证据，不改身份、端点、scope或正文。
4. Codex已受理但平台回读缺失时，仅对原attempt用`consume-desktop-readback`读取平台证据，不再发送；确需active-turn bridge时用既有prepare/complete入口，保持原operation和实际新消息各自身份。PowerShell 用 `python <slk-transport.pyz>`，不要用 `& <slk-transport.pyz>`；`--attempt-root` 是 attempts 根目录，不是 `<run_id>/<message_id>`。
5. 明确工程行动由原责任角色显式调用标准入口，Supervisor只在精确登记Session用`submit-supervisor-decision`；不等整个turn终结。状态/ACK失败与报告投递分别记录，报告原件不变，不补造D0/D1/D2、启动、接手或TOKEN。
6. Temporal按同一operation核对ACK与既有恢复；保障故障由Supervisor按`$slk-manage-temporal`修复，不新建身份或重跑审查。重试耗尽、证据冲突、真实激活返回端点不可用或明确失效时交登记Supervisor，按`$slk-manage-team`恢复；`SUPERVISOR_DECISION_REQUIRED` 保持阻断，没有活动接收者时由 Owner/Main 真实激活，不猜接管；说明已保存内容、实际投递事实和未完成动作。

## 负面提示词

- 不要使用已退役的结果格式补交、pre-D0补交、partial/context/terminal自动判定或自动消费后缀；历史证据只读，不能改FAIL为PASS/INCOMPLETE，不能为模板重跑Agent。
- 不要猜地址、换消息ID/Session/模型或endpoint/receiver、争夺active writer、后台自唤醒、daemon、轮询循环或无限 retry；不要在 active writer 前 resume；每次操作结束当前 turn，三工程角色不用正时长wait_threads；不改旧证据，不用post-turn延迟脚本或固定秒数承诺自动恢复。
- 不要借用他人凭据、编辑SQLite、由Supervisor/OW代写Worker/Checker事实，或让报告正文隐式触发副作用；一次性Worker进程不托管OCRV长审查。
