---
name: slk-manage-team
description: Use when an active Small Loop Skill (SLK) Run needs its current team registered and its basic preparation completed or refreshed.
---

# Prepare the current team

仅用于已启用 SLK 的 Run。Supervisor 完成当前必要准备，不把它做成工程验收。使用本机已验完整成品，只补缺项，不现场编译。按需选准备 Goal，不占无关目标；建议耗时不是截止线。

## 按顺序补缺，不重复已完成项

1. Owner 已确认方案、Supervisor 与模型后，由该 Supervisor 一次 init-run/根记录，冻结 Run/project/当前 plan revision、中央数据根与自身准确身份，打开可见 BI 1.1.1。已有 Run 读回原身份，不重建。
2. 给 Supervisor 简明角色定位并沿 `$slk-grill-supervisor` 完成现有 Eval/理解确认。随后 Supervisor 建立/指定 OCRV Checker，由 Checker 建立/指定 DSH Worker，各自取得准确原生端点和本人权限；不创建 Codex Checker/Worker。
3. Supervisor 启动或复用自己唯一直属 OW child，覆盖自己的全部 Run，不跨 Supervisor；每 Run 单独绑定技术 instance、scope、cycle、观察凭据，实际 parent/child 相同。只给观察权，不继承父级工程权限。真实型号/reasoning 已确认，gpt-6-luna high/xhigh 仅推荐。
4. 建立本 Run 唯一 RUN_TEAM_REGISTRY，分开登记 agent identity、runtime、native/session locator、message endpoint、transport/status adapter、delivery success signal、设备、model/reasoning、Skill/工具版本及 revision。准确 Host 路径/hash 与密封权限匹配；不凭标题、窗口或历史位置猜地址。凭据操作按需读[认证说明](references/credential-preparation.md)。
5. 各角色只读本角色职责/禁区、真实交接对象和现有8个 runtime-critical 场景；纠正误解后确认，普通 CELL 切换不重复，变化只复核受影响理解。完整结构化回应绑定当前 revision，未变理解可复用但不伪装新实测。OCRV 没任意聊天入口时不假造 Eval；核对当前原生 config/工具/MCP 与已验等价能力，首次真实审查保留准确 runtime_root + host + endpoint version 的 harness、native start/result，不为准备另跑正式 D1。
6. 核对完整 SLK/Skill、必需组件、原生地址/状态、当前能力和消费者权限、BI；原责任链的端点必须真实可用，脚本/OW补救代发不算正常通路。4.5.x 普通新 Run 用 preflight-new-run，续接用 preflight-admission，不读取历史 conformance 或现场重演七腿。可选增强、兼容更新和查新失败仅提示；真实必需缺项保持 NOT_READY。
7. 沿 `$slk-manage-temporal` 准备共享服务/本 Run 工作流，冻结真实 workflow identity 与准确 Host/config/OW proof，并完成一次当前 OW ACTIVE 核验及准入；不要求先有 cycle 或首 CELL 已施工。

## 准备完成边界

基本准备真实闭合就完成；如用了准备 Goal，此时结束，不延伸到工程。首个未启动 CELL 仍由 Supervisor 以当前下一枚单调 TOKEN 交 Checker。已启动的旧交接只续原后缀，不重派。业务/记录结束后真实交接为最后工程动作；Worker/Checker 随后结束本次激活，Supervisor 仍保持 active，以有界原生等待接收结果和直属 OW 报告，不以准备完成为由退出。

冻结 CELL 所需的 Git 外原合同，在既有 RoleHost 的该 CELL `evidence_refs` 中登记绝对 `path`、原 `sha256`（可附 `bytes`），不用把材料塞进工程 Git 或 Worker payload。沿原交接进入 OCRV 索引供 `slk_read_evidence` 读取；仅发路径/摘要不算可读，缺失或变化保留为材料缺口，不重新认可新字节。

可恢复错误从最后可信进展续作，记录已完成项、阻塞、最后真实动作、下一合法动作；不重做已完成项、不盲目派工、不倒灌长历史。缺必需权限或不能安全继续就如实报告，Goal不保证自动恢复/永不退出；Owner暂停/取消优先。

准备缺项用 `$slk-troubleshoot-preflight`；已登记成员恢复/更换用 `$slk-replace-member`，终态归档用 `$slk-archive-members`，已有精确投递才用 `$slk-recover-communication`。这些不是正常准备新增阶段。

## 不做什么

不以历史演练、可选工具、固定分钟数、全文背诵、重复考试或首施工成功挡普通准备；不以轻量化取消角色理解、必要身份/权限和原生证据。未登记隐藏执行/文字声明不是成员，单次创建成功不等于 active。OW不 relay、不写 TOKEN/BI；单 Run 暂停/关闭不停止其他 Run 或共享 child/Temporal。Supervisor更换仍由Owner确认。
