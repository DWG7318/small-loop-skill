---
name: slk-plan-run
description: Use when an active Small Loop Skill (SLK) Run needs executable serial planning before Supervisor takeover.
---

# Plan an SLK Run

仅用于已启用 SLK 的 Run。原对话与 Owner 先确定工程方案，创建已确认 Supervisor 后由其补齐实际团队准备与 CELL 颗粒度；不要求尚未创建的角色预先完成登记。

## 形成可施工方案

1. 确认目标、边界、完成后的可观察结果及当前方法基线。保留、复用已有完成/部分完成工作，规划稳定达到目标所需的合理最小施工；不等于只追求最小 diff，也不默认全局重构。
2. 列出单一线性 CELL 路径、依赖与每项工程结果。先沿 `$slk-guard-resources` 确认 Cargo/明显独占资源的隔离、恢复和收尾责任；没有则简记。
3. 利用已有测试/构建/运行入口设计 D0、D1、D2：最低施工信心、当前 CELL、组合成果。按本 CELL 改动核真实 producer/consumer、直接下游，以及相关取消、并发、落盘或可移植性风险；不是每项都重查。测试先证明行为实际发生再断言结果，不让未启动的 Hook 或手写 reader fixture 冒充真实 producer。UI/真实运行时验收注明直接证据入口、能取证的角色与保存位置；间接验证不冒充目标环境实测。不先搭检查项目，**检验本身不列施工 CELL**。
4. 按 DSH 当前模型能力、电脑、累积工程量、依赖和返工余量拆初始 CELL。大 CELL 细分为可独立 D0/D1 的中小工程结果，后期衔接/融合项在可行时更小；不逐条命令派工、不改变验收强度、不冻结统一容量定额。
5. 先用 `$slk-select-models` 明确 Owner 选择。汇总目标、顺序/近期窗口、分层检查、容量依据、资源安排、风险和 Owner 决定，与 Owner 确认方案及 Supervisor 人选。
6. 将方案交给已确认 Supervisor；后者沿 `$slk-manage-team` 一次初始化、角色理解/Eval、登记、打开 BI、补齐必要工具和共享 Temporal/本 Run 工作流。已有项不重复。Supervisor 可补项目真正需要的能力，再根据实际情况局部细分；准备不是历史全链演练或现场编译。
7. 日常由 Checker 根据前序施工、D1、返工事实校准待派项；影响目标/验收时交 Supervisor 调整。原对话退出工程工作，保留 Owner 联系与 Supervisor 故障恢复入口。

## 可选效率增强

RTK 压低噪声输出，Probe CLI 先定位再精准读代码，Ponytail 减少过度施工。三者可服务 Worker/Checker，不增加角色/流程层。未选择、缺失、兼容更新或查新失败仅提示，不挡开工、不自动安装；Owner 选用才从官方来源全域安装一次并验证，在方案记真实选择。安装不等于启用，不用自动 hook/MCP/额外 Agent。

压缩不替代核心 diff、错误原文和验收证据；疑义回原文或原生命令。Temporal/OW 与必要身份/权限仍须真实就绪，不拿直连正常代替保障。

## 负面提示词

不要把测试、复核、验收或独立检查本身列为 CELL；检查发现且确需实施的工程才列。不要因容量估计冻结后续路线、提前无关施工，或让工具为 D0/D1/D2 裁决、移动 TOKEN、换模型。真实必要能力不兼容就修复，不派工试运气；时间建议和可选增强不作准入门槛。
