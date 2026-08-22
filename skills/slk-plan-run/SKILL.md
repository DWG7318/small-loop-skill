---
name: slk-plan-run
description: Use when the Owner has chosen SLK and the serial Run needs an executable plan before Supervisor takeover.
---

# Plan an SLK Run

## 当前目标

与 Owner 把一个适合 SLK 的工作范围整理成可施工的 Run 方案，并为 Supervisor 接管准备清楚交接。

## 建议先了解

- Run 目标、边界和完成后的可观察结果；
- GO 的线性顺序与全部初始 CELL 划分；
- 项目现有测试、构建、运行入口和相关检验 Skill；
- 可用于每个 CELL 的模型、电脑配置、环境和时间条件。

## 建议做法

1. 查看当前适用的 SLK 版本和更新内容，让本次 Run 引用同一方法基线。
2. 确认工作可以沿一条 GO/CELL 路径推进；范围明显变化时，与 Owner 重新澄清 Run 边界。
3. 依次写出 GO 结果，并在创建 Supervisor 前把工作划成可理解、可交付、可检查的初始 CELL。
4. Agent 根据项目目标、现有测试、可观察结果和相关检验 Skill 自行设计分层检查。D0提供最低施工信心，D1检查当前 CELL，D2检查成果组合；建议减少重复和过度检验。
5. 在规划每个 CELL 时，根据该 CELL 的难度、Worker模型能力、电脑和累积工程量调整大小，并为测试、意外依赖和返工保留余量。
6. 汇总 Run 目标、GO 顺序、初始 CELL 总数或近期窗口、分层检查方案、每个 CELL 的容量依据、已知风险和 Owner 决定。

## 完成后

原对话可以据此创建 Supervisor、完成双向通讯测试并交接。Supervisor 接着使用 `$slk-grill-supervisor` 确认自己已经理解方法和当前 Run。
