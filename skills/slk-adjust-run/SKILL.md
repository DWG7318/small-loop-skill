---
name: slk-adjust-run
description: Use when repeated D1 failure, D2 findings, or changed resources call for an SLK Supervisor planning decision.
---

# Adjust an SLK Run

## 当前目标

由 Supervisor 选择一条能让 Run 继续的调整路线，同时保持计划、进度和未解决问题透明。

## 常见触发

- 连续 D1 返工仍未收敛；
- D2 发现 CELL 或 GO 之间的衔接问题；
- 当前模型、电脑、环境或依赖与原计划差异较大；
- CELL 变化已经影响后续 GO、技术路线、验收目标或 Owner 需求。

## 建议选择

Supervisor 可以按实际原因组合以下办法：

1. 补充信息、资源或可验证的环境；
2. 把相关 Worker 模型能力提高一级；
3. 更换电脑、工具、账号或测试环境；
4. 调整后续 CELL 或技术路线，让已验证成果继续被继承；
5. 对改变 Run 目标、验收目标或 Owner 权限的事项，向 Owner 提出一个清楚的问题；
6. 对两轮修复后仍暂时无法解决、且其余 Run 仍有价值的事项，记录 Supervisor 豁免及未来恢复条件。

豁免作为独立结果保留，不改写为 D1 PASS。最终报告分别列出 D1 通过数和 Supervisor 豁免数。

## 更新与回到施工

调整通常保持原 Run 目标和已约定验收目标；Owner主动改变目标时，再更新相应定义。Supervisor 把原因、选择、影响、CELL n/N变化和未决风险写入根记录。

调整完成后，Supervisor 把决定写入记录并交还 Checker，随后结束本次激活。待施工 CELL 可以使用 `$slk-dispatch-cell` 校准并派发；当前 CELL 的修复可以回到 `$slk-rework-cell`。D2 衔接问题通过 Checker→Worker→Checker 修复后，再激活 Supervisor 检查相关 D2。
