---
name: slk-rework-cell
description: Use when an active Small Loop Skill (SLK) Run has a D1 FAIL and the same CELL needs focused rework.
---

# Rework a CELL

仅用于已选择 `$small-loop-skill` 的当前 Run。正式 FAIL 链为 **原 Checker → Supervisor → 同一 Worker → 原 Checker**；Supervisor 指引修复，不重做 D1、不改代码或替 Worker 施工。

质量目标是绝大部分 CELL 首轮 D1 PASS，单 CELL 原则上最多一次常规 D1 FAIL；靠合理拆分及改进实现，不是通过率配额，不影响 Checker 的真实判断。

## 第一次正式 FAIL

1. 原 OCRV Checker 用绑定的 `slk_checker_decide(FAIL, message?)` 显式产生 `D1_FAILED`；先封存本人结果/退出，再由同一标准入口的机械后缀发 `D1_FAILURE_ESCALATION` 与 TOKEN 给登记 Supervisor。绑定原失败事件、候选、D1 attempt、CELL 目标与验收条件，附真实发现/证据，不凑字段；不解析报告代判，不用旧 `--slk-post-d1`。
2. Supervisor 只根据冻结 CELL 和当前 `D1_FAILED` 追加 `REWORK_REQUESTED`，精确绑定 Run/CELL/attempt、失败事件 ID、candidate SHA-256 和下一合法 round。形成 `D1_REWORK_DIRECTIVE`：当前失败的根因假设、最小实验、修复边界和直接受影响下游；明确已替代的旧限制，不把上一 CELL 指令带进新范围。不改变验收目标或强度。旧失败、跨 CELL/attempt、错误候选、重复 round 或 Checker 自写指引均不能授权返工。
3. 保存本人的事实、原报告与证据后，以标准入口把指引/TOKEN **直接交同一 Worker，作为本次最后任务动作**。这是 Supervisor → Worker 唯一合法例外，不是普通派工路。仅所属可信入口消费本人的密封权限；核实精确消息/payload 哈希、真实 `slk.native-start/v2`，原子提交 TOKEN 与唯一 `runtime_revision` 后结束，不等 Worker、不轮询或留 post-turn/background 动作。

原报告独立保存/投递，不因 ACK/TOKEN/动作失败而扣留；受理、后台文字或终态不是启动/接手证明。明确投递故障才按 `$slk-recover-communication` 恢复原消息，不重判 D1；正常直达无需排障或 Desktop 桥接。

Worker 自主处理同一 `CELL n/N`，原因不明时按需使用 Debug Skill；依 `$slk-execute-cell` 完成修复、最低 D0 和候选交付。原 Checker 依 `$slk-check-cell` 重新执行隔离 D1，覆盖修复目标、受影响范围和相关回归。未受影响且仍有效的完成工作/客观证据保留，不重复施工，也不复用旧通过结论。所有事实追加，不覆盖失败历史。

## 第二次连续正式 FAIL

停止普通返工。Supervisor 对照两轮事实调查，再用 `$slk-adjust-run` 将尚未接受工作拆为依赖明确、可独立 D0/D1 的中小后继 CELL，经 Checker 用 `$slk-dispatch-cell` 派发；不削弱原目标，不清除两次失败、不用新 ordinal/revision 隐藏失败、不自动替换 Worker，也不让 Worker 私拆。不能合理拆分时保留阻断并决定其他路线，**不发第三次普通重试**。

D0 草稿自修、工具/检查器故障、重复回执和 D1 INCOMPLETE 不计连续产品 FAIL。初始施工、PASS、INCOMPLETE 或工具故障都不创建 `D1_REWORK_DIRECTIVE`；INCOMPLETE 走管理返回原 Checker，不冒充返工。

REQUESTED/PAUSED 不派新返工，只依原暂停边界闭合精确在途动作，保留失败/候选/operation。OW 只观察并报告 Supervisor，不提修复假设、不执行返工/回归、不代投递、重试或写 TOKEN；runtime guard 仅阻断下一 CELL，不停止当前 CELL 或扣留已有报告。
