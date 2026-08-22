---
name: slk-plan-run
description: Use when the Owner has chosen SLK and the serial Run needs an executable plan before Supervisor takeover.
---

# Plan an SLK Run

## 当前目标

与 Owner 把一个适合 SLK 的工作范围整理成可施工的 Run 方案，并为 Supervisor 接管准备清楚交接。

## 建议先了解

- Run 目标、边界和完成后的可观察结果；
- GO 的线性顺序与初步 CELL 划分；
- 可用模型、电脑配置、环境和时间条件；
- Owner 希望采用的 D0、D1、D2 验收目标。

## 建议做法

1. 查看当前适用的 SLK 版本和更新内容，让本次 Run 引用同一方法基线。
2. 确认工作可以沿一条 GO/CELL 路径推进；范围明显变化时，与 Owner 重新澄清 Run 边界。
3. 依次写出 GO 结果，再把近期工作划成可理解、可交付、可检查的 CELL。
4. 与 Owner 敲定 D0、D1、D2 分别证明什么。检查方式可以随风险调整，验收目标保持清楚。
5. 根据 Supervisor、Checker、Worker 的工作难度建议初始模型能力，并记录实际电脑和环境。规划时为测试、意外依赖和返工保留余量。
6. 对新颖、高风险或环境不确定的 Run，可以先做一次轻量推演，重点寻找第一批 CELL、通讯和验证安排中的明显缺口。
7. 汇总 Run 目标、GO 顺序、CELL 总数或近期窗口、验收目标、模型与电脑假设、已知风险和 Owner 决定。

## 完成后

原对话可以据此创建 Supervisor、完成双向通讯测试并交接。Supervisor 接着使用 `$slk-grill-supervisor` 确认自己已经理解方法和当前 Run。
