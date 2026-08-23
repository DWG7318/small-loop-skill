# Small Loop Skill（SLK）

当前版本：**3.0.0**

SLK 用于一个有边界的中小型工程 Run，或大型工程中相对独立的中小范围。GO 与 CELL 沿一条线性路径推进。

## 核心关系

```text
Supervisor ↔ Checker ↔ Worker

Worker D0 → Checker D1 → Supervisor D2
```

```text
规划 Run/GO/检查 → 选择角色模型 → 划分初始 CELL
→ 原对话创建 Supervisor 并交接 → Supervisor Grill → 根记录
→ Supervisor 创建 Checker → Checker 职责确认 → Checker 创建 Worker
→ 通讯测试 → 第一个 CELL
```

Supervisor 在启动、上级求助、豁免、成员恢复和 D2 等边界按需激活；日常 CELL 由 Checker 与 Worker 直接推进，Supervisor 不在线等待逐 CELL 结果。Checker 派发 CELL，并在隔离状态下执行 D1。Worker 完成当前 CELL，并在交付前执行最低程度 D0。

SLK 的指导帮助成员判断怎样继续。返工、通讯恢复、成员恢复、计划调整和豁免作为特定情境下的可用方法存在。

## Skill 集合

当前方法位于 [`skills/`](skills/)：

- [`skills/small-loop-skill/SKILL.md`](skills/small-loop-skill/SKILL.md) 保存轻量身份和路由；
- 12 个同级子 Skill 分别处理 Run 与初始 CELL 规划、角色模型选择、Supervisor Grill、成员生命周期、CELL 派发与施工、记录、返工、调整、通讯恢复和收尾。返工需要根因诊断时，可以调用当前环境中适合项目的 Debug Skill。

这 12 个子 Skill 不是独立工程方法，不可脱离 SLK Run 单独使用。当前 Run 已选择 Small Loop Skill（SLK），并由主 Skill 或同集合流程路由到对应情境后，才使用相应子 Skill。

普通施工读取主 Skill 和当前情境对应的 Skill；情况变化时再加载相关指导。

## Run 记录

Supervisor 在项目根目录创建 `SLK-RUN-<RUN-ID>.md`。Worker、Checker、Supervisor 分别写入自己的工程事实。模板位于 [`skills/slk-record-run/assets/SLK-RUN.template.md`](skills/slk-record-run/assets/SLK-RUN.template.md)。

## 安装

把 `skills/` 下 13 个目录作为同级目录放入 Codex Skill 根目录。调用 `$small-loop-skill` 后，主 Skill 会随 Run 状态建议使用相应子 Skill。

## 验证

```text
python scripts/validate_repository.py
python -m pytest -q
```

## 历史版本

SLK **v2.6.0** 继续通过 Git tag 和 Release 提供，方便既有 Run 或恢复使用。3.0.0 是新的方法边界，不覆盖历史发布。

## 许可证

MIT。
