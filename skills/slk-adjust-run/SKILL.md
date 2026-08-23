---
name: slk-adjust-run
description: Use when an active Small Loop Skill (SLK) Run needs a Supervisor decision after repeated D1 failure, D2 findings, or changed resources.
---

# Adjust an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

由 Supervisor 选择一条能让 Run 继续的调整路线，同时保持计划、进度和未解决问题透明。

## 常见触发

- 连续 D1 返工仍未收敛；
- D2 发现 CELL 或 GO 之间的衔接问题；
- 当前模型、电脑、环境或依赖与原计划差异较大；
- CELL 变化已经影响后续 GO、技术路线、验收目标或 Owner 需求。

## 建议选择

Supervisor 在现有工程权限和资源范围内给出能继续施工的具体方案。电脑、工具授权、账号或受控测试环境属于 Owner 掌握的资源时，由 Owner 授权后再变化；Supervisor 负责先把解决路线设计清楚，而不是把问题原样交回 Owner。

Supervisor 可以按实际原因组合以下办法：

1. 在现有权限内补充信息、可用资源或验证方式；
2. 相关模型未由 Owner 直接指定时，可以把 Worker 能力提高一级；Owner 已指定时保留该选择，使用 `$slk-select-models` 说明变更理由和影响，再由 Owner 决定是否改变指定；
3. 调整当前或后续 CELL、施工顺序或技术路线，让已验证成果继续被继承；
4. 解决方案需要 Owner 掌握的电脑、工具、账号、测试环境或业务权限时，提交推荐方案、预期影响、可行替代和最低必要授权；
5. 同一 CELL 经过两轮 D1 返工仍未收敛时，Supervisor 可以记录本 CELL 的豁免、实际影响和未来恢复条件，再把当前 Run 的后续 CELL 交还 Checker 继续推进。

这类豁免发生在 D1 返工边界，不是 D2。豁免作为独立结果保留，不改写为 D1 PASS。最终报告分别列出 D1 通过数和 Supervisor 豁免数。

## 更新与回到施工

调整通常保持原 Run 目标和已约定验收目标；Owner主动改变目标时，再更新相应定义。Supervisor 把原因、选择、影响、CELL n/N变化和未决风险写入根记录。

调整完成后，Supervisor 把决定写入记录并交还 Checker，随后结束本次激活。待施工 CELL 可以使用 `$slk-dispatch-cell` 校准并派发；当前 CELL 的修复可以回到 `$slk-rework-cell`。D2 衔接问题通过 Checker→Worker→Checker 修复后，再激活 Supervisor 检查相关 D2。
