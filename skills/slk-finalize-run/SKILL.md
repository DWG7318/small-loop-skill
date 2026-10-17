---
name: slk-finalize-run
description: Use when an active Small Loop Skill (SLK) Run already has a real D2 PASS or an authorized termination result and still has closeout work remaining.
---

# Finalize an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

沿已有结论完成剩余收尾；不重做准备、D0、D1 或 D2，不把归档变成新的工程节点。

## 收尾

1. 读取准确 Run 的原工作簿、真实 D2 PASS 或已获授权的终止结果，以及已有收尾证据；已完成项跳过。缺少真实最终结果时回到原节点，不由本 Skill 补造通过。
2. Supervisor 按 `$slk-record-run` 在原工作簿保存精简结项总结，再同步唯一当前摘要；完成状态为 `CLOSED`，终止保留真实终止状态，最终令牌 `SLK TOKEN` 标为 `CLOSED`、不再流转。保留失败、豁免、未解决项和证据，不抹去原结论。
3. 按准确任务 ID 确认本 Run 的 Worker、Checker 工程活动已结束，包括已知外部任务；只归档这两个成员，先归档 Worker、再归档 Checker，以实际返回和归档状态确认。残留活动由 Supervisor 定向处理，未确认就记未完成，不做全机检查，也不另造 Worker/Checker 的收尾消息或回执。
4. 原创建 Supervisor 依 `slk-record-run/references/bi.md` 在自身可信宿主执行既有 `slk-bi.ps1 --bi-read "<RUN-ID>"`，确认总结与最终状态已读入，再执行 `--bi-archive "<RUN-ID>"` 并读取结果；准确 Run ID 与创建者身份不由同名或文字声明代替。已确认归档不重复操作。
5. 分别核实方法收尾、BI 本地归档和云端保存；断网只留待上传，不重开工程，也不把本地成功称为云端已保存。归档失败或身份未确认时保留相应未完成事项。
6. 向 Owner 简报真实结果、豁免/风险、未完成事项和原记录路径；方法收尾完成或 Owner 明确停止后结束持续观察，保留 Supervisor 对话及原记录。

## 负面提示词

- 不要因收尾重跑准备或验收、重开已闭合工程，或把活动回合结束当成外部任务结束；不要归档其他 Run 成员、Supervisor 对话，或把计划、消息受理和待上传写成完成。
