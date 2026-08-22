---
name: slk-plan-cell
description: Use when the next serial SLK CELL needs a workable boundary before Checker dispatch.
---

# Plan the Current CELL

## 当前目标

把下一段工作整理成一个适合当前 Worker、电脑和工程状态的 CELL，同时让 Checker 能独立判断结果。

## 建议了解

- 当前 GO、前一 CELL 结果和下一项真实依赖；
- Worker 当前模型能力与可用的提高一级方案；
- 电脑、工具、测试时间和环境限制；
- 随代码增长形成的累积工程量；
- 本 CELL 的验收目标及其与 Run 目标的关系。

## 建议做法

1. 选择一个有明确结果、边界和检查方法的当前 CELL，并标记 `CELL n/N`。
2. 用实际工程量判断难度，而不是只看文字描述。后期的小改动可能需要较大的回归范围。
3. 让模型和电脑在施工、测试、意外依赖与返工之后仍有余量。
4. 预计工作接近可用能力时，可以在派发前拆分为两个串行 CELL。两个 CELL 共同保留原验收目标。
5. 写清输入、期望变化、相关文件或系统范围、建议 D0、D1 验收目标和已知风险。
6. 计划变化时更新 n/N 和根 Run 记录，让后续成员看到当前分母。

## 完成后

把 CELL 方案交给 Checker，并建议使用 `$slk-dispatch-cell` 形成面向 Worker 的简洁交付。
