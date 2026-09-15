---
name: slk-plan-run
description: Use when an active Small Loop Skill (SLK) Run needs executable serial planning before Supervisor takeover.
---

# Plan an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

与 Owner 把一个适合 SLK 的工作范围整理成可施工的 Run 方案，并为 Supervisor 接管准备清楚交接。

## 建议先了解

- Run 目标、边界和完成后的可观察结果；
- GO 的线性顺序与全部初始 CELL 划分；
- 项目现有测试、构建、运行入口和相关检验 Skill；
- 可用于每个 CELL 的模型、电脑配置、环境和时间条件。

## 可选全域效率工具

RTK 用于压缩高噪声终端输出，Probe CLI 用于在精准读取前定位代码结构，Ponytail 用于减少已理解问题后的过度施工；三者服务 Worker，也可服务 Checker。开始规划时检查 Codex 全域是否可用，缺少时从官方来源只安装一次并验证，不复制到单个项目；安装不等于启用，随后由 Owner 决定本次 Run 启用哪些并写入 Run 方案。RTK 与 Ponytail 不启用自动 hook，Probe CLI 不接 MCP 或额外 Agent，只由成员在适用位置显式调用。

这些增强不增加角色，也不增加流程层，不改变 CELL 目标和 D0、D1、D2。压缩不代替核心 diff、关键错误原文和最终验收证据；工具缺失或失败不阻止 SLK，成员回退原生命令和精准读取继续工作。

## 建议做法

1. 查看当前适用的 SLK 版本和更新内容，让本次 Run 引用同一方法基线。
2. 确认工作可以沿一条 GO/CELL 路径推进；范围明显变化时，与 Owner 重新澄清 Run 边界。
3. 依次写出 GO 结果和需要完成的工程范围，保持单一线性顺序。接手已完成或部分完成项目时，先识别并保留、复用已完成工作，再按“合理最小施工”规划为稳定达到当前目标所需的施工路线、范围和工程活动；这不等于最小代码改动，并应避免重复施工、提前开展无关工作和不必要的全局重构。
4. Agent 根据项目目标、现有测试、可观察结果和相关检验 Skill 自行设计分层检查。D0提供最低施工信心，D1检查当前 CELL，D2检查成果组合；建议减少重复和过度检验，优先使用现有入口或直接操作取得产品证据，不把搭建检查体系当作开工前提。检查本身不另列为独立 CELL，只有检查发现后确需实施的工程工作才进入 CELL。
5. 在创建 Supervisor 前使用 `$slk-select-models`，分别选择 Supervisor、Checker、Worker 的模型能力，并记录选择理由和可替换范围；Owner 已经指定模型时，保留该指定并据此匹配 CELL。
6. 根据每项工作的难度、Worker模型能力、电脑和累积工程量，把工程工作划分为初始 CELL，并为测试、意外依赖和返工保留余量；这里形成的是开工所需的初始估计。规划 CELL 时应控制单个 CELL 的工程量，并考虑线性推进中依赖与上下文会逐步累积，使越靠后的 CELL——尤其包含衔接或融合工作的 CELL——通常保留更多余量，并在可行时拆得更小。
7. 说明后续由 Checker 根据前序 CELL 的实际施工事实、D1和返工表现动态校准待派发 CELL，不把初始估计冻结成固定容量。
8. 汇总 Run 目标、GO 顺序、初始 CELL 总数或近期窗口、分层检查方案、每个 CELL 的容量依据、角色模型选择、可选效率工具、已知风险和 Owner 决定。

## 完成后

原对话可以据此创建 Supervisor，完成原对话 ↔ Supervisor 的双向通讯测试并交接。Supervisor 接着使用 `$slk-grill-supervisor` 确认自己已经理解方法和当前 Run。

## 负面提示词

- 不要把检查本身列成施工 CELL，或先搭大型检测体系才开工；不要借接手已完成或部分完成项目默认展开无关全局重构，也不要把“合理最小施工”缩成最小代码 diff；不要把初始 CELL 容量估计冻结成后续不能校准的定额。
