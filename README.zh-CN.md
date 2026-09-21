# Small Loop Skill（SLK）

当前版本：**4.1.0**

SLK 是 Loop Engineering 的线性形态，用于一个有边界的中小型工程 Run，或大型工程中相对独立的中小范围。一个 SLK 就是一个 Run，Run 直接包含一条线性 CELL 路径。

## 核心关系

```text
Supervisor ↔ Checker ↔ Worker

CELL 派发 → Worker 施工与 D0 → 候选 → Checker 隔离 D1 → 通过/返工 → Supervisor D2
```

```text
规划 Run/检查 → 选择角色模型 → 划分初始 CELL
→ 原对话创建 Supervisor 并交接 → Supervisor Grill → 根记录
→ Supervisor 创建 Checker → Checker 职责确认 → Checker 创建 Worker
→ 通讯测试 → 第一个 CELL
```

Supervisor 在启动、上级求助、豁免、成员恢复和 D2 等边界按需激活；日常 CELL 由 Checker 与 Worker 直接推进，Supervisor 不在线等待逐 CELL 结果。一个当前有效的 `SLK TOKEN` 在 4.0 状态核心中记录最后已确认的责任边界：发送者仅在原生投递成立后推进令牌，接收者开始真实工作时记录 `WORK_STARTED`；任何一项都不能单独用来假装成员仍在工作。Checker 派发 CELL，并在隔离状态下执行 D1。Worker 完成当前 CELL，并在交付前执行最低程度 D0。

Run 规划沿用 D0、D1、D2 三层检查，不为检查本身创建独立 CELL。建议优先用现有入口直接验证产品，把检查工具或环境故障与产品缺陷分开，复用仍有效的客观证据，不逐层重复完整验收或先搭建检查体系；证据不足保留未证明，不写成 PASS。SLK 接入已经完成或部分完成的项目时，先保留并复用已完成工作，再选择为可靠达到当前目标所需的合理最小施工路线、范围和工程活动，而不是只追求最小代码差异。

SLK 的指导帮助成员判断怎样继续。返工、通讯恢复、成员恢复、计划调整和豁免作为特定情境下的可用方法存在。

RTK、Probe CLI 与 Ponytail 是可选的外部效率工具。它们可以在 Codex 全域只安装一次，但安装不等于获得项目使用授权；每个 Run 仍由 Owner 决定是否启用。SLK 只显式调用，不启用自动 hook、MCP 或额外 Agent；原生命令与原始证据始终可以回退并作为事实依据。

跨 Agent 交接使用已验收的 `slk-transport`、精确角色端点和原生 Agent 激活。数据库行、后台消息或按对话标题匹配都不等于投递；只有精确原生启动证据成立后，当前发送者才完成交接，否则继续持有责任。操作说明见 [`docs/transport/SLK-TRANSPORT.md`](docs/transport/SLK-TRANSPORT.md)。

## 4.0 状态与 LE BI

SLK 4.0 加入一个可配置的电脑全域数据根目录、版本化 SQLite 权威状态、耐久证据、确定性 Markdown 导出，以及独立的只读桌面 **LE BI**。Supervisor、Checker、Worker 只通过经过身份验证的 `slk-state` CLI 写入各自原有事实；数据库不调度施工，也不增加第四个角色。`slk-bi-query` 为其他 Agent 提供稳定只读 JSON，LE BI 则显示同一组投影，不暴露凭据或写入入口。公开方法结构为 `Run → CELL`；4.0 数据库只为历史数据兼容保留原分组字段，LE BI 不展示该层。详见 [`docs/state/SLK-STATE.md`](docs/state/SLK-STATE.md)、[`docs/state/SLK-BI.md`](docs/state/SLK-BI.md)、独立的 [`状态核心验收记录`](docs/state/SLK-STATE-ACCEPTANCE.md) 与 [`BI 验收记录`](docs/state/SLK-BI-ACCEPTANCE.md)。

LE BI 把所有活动 SLK 作为精简横条显示，不论其为独立 SLK，还是属于某个 CLK/GLK 项目。展开后只显示该 SLK 的三角色、模型与 CELL 记录；完成、废弃或被替代的 SLK 立即进入归档箱。BI 不确认消息是否真正投递，不凭旧事件推断当前进程存活，不恢复通讯，也不修改 Run。未来 LCaS rc.08/rc.09 可以嵌入这些读取组件；SLK 4.0 的当前运行不依赖该集成。

## Skill 集合

当前方法位于 [`skills/`](skills/)：

- [`skills/small-loop-skill/SKILL.md`](skills/small-loop-skill/SKILL.md) 保存轻量身份和路由；
- 13 个同级子 Skill 分别处理 Run 与初始 CELL 规划、资源连续性、角色模型选择、Supervisor Grill、成员生命周期、CELL 派发与施工、记录、返工、调整、通讯恢复和收尾。返工需要根因诊断时，可以调用当前环境中适合项目的 Debug Skill。

这 13 个子 Skill 不是独立工程方法，不可脱离 SLK Run 单独使用。当前 Run 已选择 Small Loop Skill（SLK），并由主 Skill 或同集合流程路由到对应情境后，才使用相应子 Skill。

普通施工读取主 Skill 和当前情境对应的 Skill；情况变化时再加载相关指导。维护 SLK 提示词时，对已发现的误用同时修正主体正确做法，并在独立“负面提示词”章节写对应的“不要……”；已有提醒优先修改，不反复堆叠。负面章节补充同一方法，不另立工作体系或审批、停工清单。

## Run 记录

Supervisor 初始化 Run 及第一版施工方案。Worker、Checker、Supervisor 分别把自己的工程事实追加到配置好的 SLK 数据根目录；系统再从这一权威状态确定性导出 `SLK-RUN-<RUN-ID>.md`，不写入产品仓库。模板仍位于 [`skills/slk-record-run/assets/SLK-RUN.template.md`](skills/slk-record-run/assets/SLK-RUN.template.md)，用于保持可读结构与兼容性。

## 安装

把 `skills/` 下 14 个目录作为同级目录放入 Codex Skill 根目录。调用 `$small-loop-skill` 后，主 Skill 会随 Run 状态建议使用相应子 Skill。

新电脑还需一次性配置 DSH、OCRV、跨 Agent 传输与状态工具；完整步骤见 [`SLK 4.0 Windows 运行环境配置指引`](docs/runtime/SLK-WINDOWS-RUNTIME.md)。这些机器级组件由多个项目复用，不随每个项目重复安装。

## 验证

```text
python scripts/validate_repository.py
python -m pytest -q
```

## 历史版本

SLK **v3.0.8** 保留为最后一个纯提示词轻量版本，**v2.6.0** 保留为上一代单体恢复版本。SLK 4.0 保持 3.x 方法语义，只增加跨 Agent 的耐久状态和只读展示，不替换三角色 Loop。

## 许可证

MIT。
