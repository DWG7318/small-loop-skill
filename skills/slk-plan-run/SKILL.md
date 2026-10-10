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
- Run 的线性 CELL 顺序与全部初始 CELL 划分；
- 项目现有测试、构建、运行入口和相关检验 Skill；
- 固定角色运行时、电脑配置、环境和时间条件。

## 可选全域效率工具

RTK 用于压缩高噪声终端输出，Probe CLI 用于在精准读取前定位代码结构，Ponytail 用于减少已理解问题后的过度施工；三者服务 Worker，也可服务 Checker。开始规划时检查 Codex 全域是否可用，缺少时从官方来源只安装一次并验证，不复制到单个项目；安装不等于启用，随后由 Owner 决定本次 Run 启用哪些并写入 Run 方案。RTK 与 Ponytail 不启用自动 hook，Probe CLI 不接 MCP 或额外 Agent，只由成员在适用位置显式调用。

这些增强不增加角色，也不增加流程层，不改变 CELL 目标和 D0、D1、D2。压缩不代替核心 diff、关键错误原文和最终验收证据；工具缺失或失败不阻止 SLK，成员回退原生命令和精准读取继续工作。

## 建议做法

1. 查看当前适用的 SLK 版本和更新内容，让本次 Run 引用同一方法基线。
2. 确认工作可以沿 `Run → CELL` 的单一路径推进；范围明显变化时，与 Owner 重新澄清 Run 边界。
3. 依次写出需要完成的工程范围和 CELL 结果，保持单一线性顺序。接手已完成或部分完成项目时，先识别并保留、复用已完成工作，再按“合理最小施工”规划稳定达到当前目标所需的施工范围；这不等于最小代码改动，并应避免重复施工、提前开展无关工作和不必要的全局重构。
4. 使用 `$slk-guard-resources` 静态确认 Cargo 和其他明显独占资源的隔离、恢复与清理安排；没有相应资源时简要记为无特别安排。
5. Agent 根据项目目标、现有测试、可观察结果和相关检验 Skill 自行设计分层检查；对依赖 UI、运行时或真实环境的 CELL，注明现有直接证据入口、能取得证据的角色与保存位置。D0提供最低施工信心，D1检查当前 CELL，D2检查成果组合；建议减少重复和过度检验，优先使用现有入口或直接操作取得产品证据，不把搭建检查体系当作开工前提。测试、复核、验收或独立检查本身不另列为独立 CELL，只有检查发现且确需实施的工程工作才进入 CELL。
6. 在创建 Supervisor 前使用 `$slk-select-models`，再用 `$slk-manage-team` 建立四角色 `RUN_TEAM_REGISTRY`，打开可见 BI 1.1.1，核对真实 runtime、model、adapter、endpoint、设备、上下文/任务容量、可写工作区及必需 Skill/Tool；以合法隔离小样本由原责任成员完成七腿演练并 `seal-normal-chain-source`，产品 Run 只执行 `preflight-new-run` 当前准入。Owner 对 Ponytail、RTK、Probe CLI 明确 ON/OFF；Supervisor 可补充项目所需 Skill/Tool并纳入真实预检，不凭自由配置启用未登记功能。Overwatcher 与 Temporal 是 4.4.4 readiness 必需项。
7. 使用 `$slk-manage-temporal` 验证共享本地服务，并以稳定 Run ID 启动本 Run 独立的 `SLK.Start` 与 `SLK.Run` 工作流；服务、worker、adapter 或 readiness 收据未证明时保持阻断，不以直连正常代替运行保障。
8. 工程方案和验收结果已经确定后，Supervisor 仍须按 DSH Worker 的实际能力、电脑和累积工程量划分为初始 CELL：大 CELL 在派工前拆成依赖明确、可独立 D0、独立 D1 的多个中小 CELL，并为测试、意外依赖和返工保留余量；越靠后的 CELL，尤其衔接或融合工作的 CELL，在可行时拆得更小。这只调整施工颗粒，不改变原 Run 结果和验收强度，也不把逐条命令包装成 CELL。
9. 说明后续由 Checker 根据前序 CELL 的实际施工事实、D1和返工表现动态校准待派发 CELL，不把初始估计冻结成固定容量。
10. 汇总 Run 目标、CELL 顺序与总数或近期窗口、分层检查方案、每个 CELL 的容量依据、资源安排、四角色绑定、中央 SLK 数据根、BI、Temporal、可选效率工具、已知风险和 Owner 决定。

## 完成后

原对话可以据此创建 Supervisor，完成原对话 ↔ Supervisor 的双向通讯测试并交接。Supervisor 接着使用 `$slk-grill-supervisor` 确认自己已经理解方法和当前 Run。

## 负面提示词

- 不要把测试、复核、验收或独立检查本身列成施工 CELL；它们属于 D0/D1/D2，另列会重复检验；不要先搭大型检测体系才开工，也不要借接手已完成或部分完成项目默认展开无关全局重构、把“合理最小施工”缩成最小代码 diff 或冻结初始 CELL 容量估计。
- 不要在已知验收依赖特定运行时、UI 或真实环境时只留下抽象结论而不注明现有证据入口，也不要把代理环境、逻辑视口或代码推断写成未实际执行的目标环境验证。
- 不要因选择 Temporal 新增角色或改变直连；不要让它决定 D0/D1/D2、移动 `SLK TOKEN`、自动切换模型，或用 delivery success 代替 `native-start ACK`。
- 不要用“工具应该存在”、提示词自报或缺省开启代替 readiness；`REPAIR_NEEDED` 只修最小本地缺口，`INCOMPATIBLE` 不派工试运气。
