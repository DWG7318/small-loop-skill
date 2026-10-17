---
name: slk-grill-supervisor
description: Use when an active Small Loop Skill (SLK) Run has a newly assigned Supervisor who needs to demonstrate practical understanding before engineering begins.
---

# Confirm Supervisor understanding

仅用于已启用 SLK 的 Run。由已确认 Supervisor 完成简明角色定位与现有 Eval；误解只纠正受影响内容，不全文背诵、重复考试或施工演练。

## 理解哪些边界

- 日常链 Supervisor → Checker → Worker → Checker；正式 FAIL 才由 Checker → Supervisor → 同一 Worker，第二连续 FAIL 调查并拆分。原 Checker 独立 D1、Worker 最低 D0、Supervisor 组合 D2，INCOMPLETE/工具故障不是产品 FAIL。
- 方案按实际 Worker（推荐 DSH）的能力和依赖细分，检查不列施工 CELL；复用有效事实，不重复检验体系。资源、权限与 Owner 决定保持；推荐品牌不授予权限或替代能力验证。
- 自己是现场临时补漏和记录的第一责任人：可用自己身份代交确已存在的原件、纠正位置或续机械后缀，不等源码维修；不冒充原作者、不编造未有资料或代判 D1。异常的具体处置可按事实改变，必要权限与真实验收不变。
- 自己的唯一 OW 直属 child 覆盖自己的全部 Run，不跨 Supervisor；600秒主动核验，只写自身观察/向父级报告，报告后继续，不干预工程。accepted 不等于接管，UNKNOWN 不等于退出，停止需父级二次确认。
- 原件位置/hash、原生真实启动、原角色显式认证动作和 TOKEN 提交各自留证；交接是最后工程动作，Worker/Checker 随后结束本次激活。Supervisor 项目期间保持 active，以有界原生等待接收结果，不逐 CELL 代工或发 final 等待 OW 唤醒；Temporal 也不替代父级在线。关键失败/决定及时追加，已有报告不被维护故障扣住。
- Temporal 共享服务/每 Run 工作流负责通讯保障、1200秒 OW 核验与1800秒责任提醒，不代替工程判断。自己按需介入异常、规划、FAIL/豁免及最终 D2，不逐 CELL 盯工。

## 轻量 Eval

按 `$slk-manage-team` 先建立准确 Run/project/plan revision，然后使用主 Skill 的 [现有案例包](../small-loop-skill/assets/SLK-ROLE-EVAL.v1.json)，只取 Supervisor 的8个 runtime-critical 场景，沿 `scripts/validate_role_eval.py` 校验当前身份/revision/case-pack SHA-256 和完整结构化回应。缺/多/重复题、错角色/答案/schema/hash/revision 或答案变体不冒充通过。

失败只解释错点并更新本版本回应。变化只重新确认受影响理解；未变理解及答案可复用，在准备记录说明来源，但完整回应仍绑定当前 revision，不能把旧 artifact 改头冒充新实测。完整案例包是开发/发布验证，不是运行时额外考试。

确认后回团队准备只补缺项，不重复 init-run 或创建成员；自由文本“理解了”不替代现有证据。OCRV 没有聊天入口不假造回答，其原生等价能力处理见团队指引。
