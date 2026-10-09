---
name: slk-rework-cell
description: Use when an active Small Loop Skill (SLK) Run has a D1 FAIL and the same CELL needs focused rework.
---

# Rework a CELL

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

由 OCRV Checker、Codex Supervisor 与同一 DSH Worker 根据正式 D1 FAIL 修复当前 CELL，并保持原验收目标和清楚的返工历史；Worker 在交付前的 D0 草稿自修单独记录为本地尝试。

## 建议做法

1. 原 OCRV Checker 通过绑定的 `slk_checker_decide(FAIL, message?)` 明确记录自己的 `D1_FAILED`；同一次标准工具调用内部发送 `D1_FAILURE_ESCALATION` 与 TOKEN 给 Supervisor，不再使用 `--slk-post-d1` 或由宿主解析报告代判。绑定失败事件、候选哈希、返工轮次、CELL 目标和验收条件，附带原有发现/证据而不凑字段。空闲 Supervisor 走正常直达；仅当普通发送与一次 exact retry 都因 active Desktop writer 未解析而失败、返回 `DESKTOP_BRIDGE_REQUIRED` 时，Desktop 宿主才原样投递并保留真实 host receipt。密封 Checker 凭据只在所属可信 Tool 内部解封；匹配当前 D1/candidate/attempt 和真实 Supervisor start 后原子提交 TOKEN，不重跑或重判 D1。正常成功与补救成功分开记录，已有报告不因行动失败而扣留。调用合同见 [`docs/transport/SLK-TRANSPORT.md`](../../docs/transport/SLK-TRANSPORT.md)。
2. Supervisor 不重做或接管 D1、不改变验收目标；第一次正式 FAIL 只基于冻结 CELL 与 OCRV 当前 `D1_FAILED` state event 写入 `REWORK_REQUESTED`，逐字绑定同一 Run/CELL/attempt、失败事件 ID、候选 SHA-256 与下一合法 round，再形成 `D1_REWORK_DIRECTIVE` transport payload，给出一个根因假设、一个最小实验、最小修复边界和回归目标。旧失败、跨 CELL/attempt、错误 candidate、重复 round 或 Checker 自写均失败关闭。
3. Supervisor 把 `D1_REWORK_DIRECTIVE` 与 TOKEN 直接交给同一 DSH Worker 后结束本轮；这是 `Supervisor → Worker` 唯一合法情形，不构成一般派工通路。
4. Worker 继续处理同一 `CELL n/N`，自行判断和施工；原因仍不清楚时可调用 Debug Skill，例如 `$superpowers:systematic-debugging`。同一 CELL 第二次连续 D1 FAIL 时应停止普通返工：Supervisor 对照两轮事实调查后，用 `$slk-adjust-run` 把尚未接受的工作进一步拆分为依赖明确、可独立 D0、独立 D1 的多个中小后继 CELL，再经 Checker 使用 `$slk-dispatch-cell` 派发；不改变原目标和验收强度，不清除两次失败，不自动替换 Worker。若无法继续合理拆分则保持阻断并决定其他路线，不发起第三次普通重试。
5. Worker 完成修改和最低 D0 后，使用 `$slk-execute-cell` 的记录与交付方式重新提交。
6. OCRV Checker 使用 `$slk-check-cell` 针对修复目标、受影响范围和相关回归重新执行 D1，保留未受影响且仍有效的已完成工作与客观证据，不复用通过结论；本轮事实通过 `slk-state` 追加，不覆盖前轮记录，不重复施工未受影响且仍有效的已完成工作。

## 收敛目标

规划目标是绝大部分 CELL 首轮 D1 PASS，单个 CELL 原则上最多一次常规 D1 FAIL；这不是篡改 Checker 结论，而是要求 Supervisor 在第二次连续 D1 FAIL 后修正颗粒度。工具错误、D1 INCOMPLETE、重复回执和非产品失败不计入连续次数。

## 负面提示词

- 不要把 D0 草稿自修或 Checker 自建检查器故障计入 Worker 的 D1 返工次数；不要在初始施工、D1 PASS、D1 INCOMPLETE 或工具故障时创建 `D1_REWORK_DIRECTIVE`，不要把 `Supervisor → Worker` 扩成普通派工，也不要让 Supervisor 重判 D1、直接改代码或替 Worker 施工。
- 不要让 Overwatcher 提出修复假设、执行返工或判定回归；它只观察通讯与运行证据。不要在第二次连续 D1 FAIL 后重复原返工内容、让 Worker 私自拆 CELL，或用新 ordinal/plan revision 隐藏原失败历史。
