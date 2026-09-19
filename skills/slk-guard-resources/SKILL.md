---
name: slk-guard-resources
description: Use when an active Small Loop Skill (SLK) Run may encounter Cargo locks or another obvious exclusive resource.
---

# Guard SLK Resources

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

在初始 CELL 划分前识别最可能打断 Loop 的独占资源，并把轻量隔离、恢复和清理决定写进 Run 方案。

## 静态检查

1. 本 Run 是否执行 Cargo/Rust 构建或测试？如是，建议 Worker 与 Checker 通过 `slk-cargo` 复用本 Run 的独立 target；参数和恢复细节查看 `slk-cargo --help`。
2. 本 Run 是否还有一个明显的独占资源，例如固定数据库实例、端口、临时目录或 GPU？如有，记录它的临时隔离办法、无法隔离时的有界恢复办法和收尾责任。
3. 没有明显独占资源时，记录“无特别资源安排”即可，不扩展检查。

## 施工中

资源占用发生时，当前角色读取 [`resource-contention.md`](../slk-execute-cell/references/resource-contention.md)，保留当前 SLK TOKEN 并从同一节点恢复。安全恢复办法不成立时，向 Supervisor 说明事实、已尝试动作和推荐调整。

## 计划输出

Run 方案增加一项“资源安排”：列出 Cargo 是否使用 `slk-cargo`、其他明显独占资源、恢复边界与最终清理者。

## 负面提示词

- 不要把静态资源检查扩成持续观察、后台任务或动态资源清单。
- 不要为资源安排另建角色、检查层或施工 CELL，也不要把安静等待本身猜成资源锁。
