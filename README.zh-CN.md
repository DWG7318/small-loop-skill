# Small Loop Skill（SLK）

当前版本：**3.1.1**（独立 `maintenance/3.1.1` 维护分支，基于 `v3.1.0` / `e200966`；3.x 历史基线包括 `v3.0.9` 与 `v3.0.8`）

本版仅补短收尾入口、原工作簿结项总结和角色通用表述，配套独立预编译 BI/WebBI 1.1.6 或兼容新版；[BI 用法](skills/slk-record-run/references/bi.md)。不引入 4.x 的 OW、Temporal、状态数据库或 RoleHost。使用侧不需要 Rust/Node 编译环境，也不因 BI 升级切换工程方法。

SLK 是 Loop Engineering 的线性形态，用于一个有边界的中小型工程 Run，或大型工程中相对独立的中小范围。GO 与 CELL 沿一条线性路径推进。

## 核心关系

```text
Supervisor ↔ Checker ↔ Worker

CELL 派发 → Worker 施工与 D0 → 候选 → Checker 隔离 D1 → 通过/返工 → Supervisor D2 → 收尾
```

```text
规划 Run/GO/检查 → 选择角色模型 → 划分初始 CELL
→ 原对话创建 Supervisor 并交接 → Supervisor Grill → 根记录
→ Supervisor 创建 Checker → Checker 职责确认 → Checker 创建 Worker
→ 通讯测试 → 第一个 CELL
```

Supervisor 在施工期间持续在线，通过原生等待和精简证据低 Token 观察 Worker/Checker，在既有授权内现场排障并记录处置结果；日常 CELL 仍由 Checker 与 Worker 直接推进，不接管派发或独立 D1。一个当前有效的 `SLK TOKEN` 由既有可见交接消息携带：它标明最后已确认的责任边界，但不证明成员正在实时施工，也不新增角色、服务、状态文件或回执轮次。Checker 派发 CELL，并在隔离状态下执行 D1。Worker 完成当前 CELL，并在交付前执行最低程度 D0；两者以交接为最后动作，Supervisor 则继续观察直到 Run 收尾或 Owner 明确停止。

Run 规划沿用 D0、D1、D2 三层检查，不为检查本身创建独立 CELL。建议优先用现有入口直接验证产品，把检查工具或环境故障与产品缺陷分开，复用仍有效的客观证据，不逐层重复完整验收或先搭建检查体系；证据不足保留未证明，不写成 PASS。SLK 接入已经完成或部分完成的项目时，先保留并复用已完成工作，再选择为可靠达到当前目标所需的合理最小施工路线、范围和工程活动，而不是只追求最小代码差异。

SLK 的指导帮助成员判断怎样继续。返工、通讯恢复、成员恢复、计划调整和豁免作为特定情境下的可用方法存在。

Supervisor、Checker、Worker 是职责，不等同特定产品。由 Owner 确认实际 Supervisor、Agent 平台与模型；型号是能力推荐而非白名单。Supervisor 推荐能力参考 `gpt-6.1-sol/high`，不为低 Token 观察擅自降为低性能模型，Owner 指定保持优先。当前 CELL 的 D1 能力调整与 D2 按实际原因决策保持不变。

RTK、Probe CLI 与 Ponytail 是可选的外部效率工具。它们可以在 Codex 全域只安装一次，但安装不等于获得项目使用授权；每个 Run 仍由 Owner 决定是否启用。SLK 只显式调用，不启用自动 hook、MCP 或额外 Agent；原生命令与原始证据始终可以回退并作为事实依据。

## Skill 集合

当前方法位于 [`skills/`](skills/)：

- [`skills/small-loop-skill/SKILL.md`](skills/small-loop-skill/SKILL.md) 保存轻量身份和路由；
- 13 个同级子 Skill 分别处理 Run 与初始 CELL 规划、角色模型选择、Supervisor Grill、成员生命周期、CELL 派发与施工、记录、返工、调整、通讯恢复、D2 和验收后收尾。返工需要根因诊断时，可以调用当前环境中适合项目的 Debug Skill。

这 13 个子 Skill 不是独立工程方法，不可脱离 SLK Run 单独使用。当前 Run 已选择 Small Loop Skill（SLK），并由主 Skill 或同集合流程路由到对应情境后，才使用相应子 Skill。当前共 14 个是实际清单，不是永久数量上限。

普通施工读取主 Skill 和当前情境对应的 Skill；情况变化时再加载相关指导。维护 SLK 提示词时，对已发现的误用同时修正主体正确做法，并在独立“负面提示词”章节写对应的“不要……”；已有提醒优先修改，不反复堆叠。负面章节补充同一方法，不另立工作体系或审批、停工清单。

## Run 记录

Supervisor 在项目根目录创建 `SLK-RUN-<RUN-ID>.md`。Worker、Checker、Supervisor 分别写入自己的工程事实，包括当前令牌指针和最后真实流转；完整历史仍保留在这一个记录中。模板位于 [`skills/slk-record-run/assets/SLK-RUN.template.md`](skills/slk-record-run/assets/SLK-RUN.template.md)。

原工作簿新增正式「结项总结」，记录实际作者与带时区时间、成果、关键问题与现场处理、剩余事项及必要证据。设备署名由 Agent 提供电脑名、IP地址、操作系统版本；公网出口 IP 只是建议，未知写「未获取」，BI 不探测。以后更正追加作者、时间与来源，不改写历史 D2。

[`slk-finalize-run`](skills/slk-finalize-run/SKILL.md) 只接已有真实 D2 PASS 或授权终止结论后的未完成收尾：先确认准确 Worker/Checker 工程活动已结束，再保存总结、同步唯一当前状态与 CLOSED 令牌并仅归档它们，最后由原创建 Supervisor 使用 BI 读取并归档。活动未确认结束时保留未完成，不写终态或归档。已完成项跳过，方法收尾、BI 本地归档与云端保存分别报告；断网留待上传，不重做准备或 D0/D1/D2、不重开工程，保留 Supervisor 及原记录。

## 安装

把 `skills/` 下 14 个目录作为同级目录放入 Owner 选定的项目 Skill 根目录（例如 `.agents/skills`）。核验固定提交、版本和 17 个 Skill 文件哈希后，仅清理该授权项目内已被替代的 3.x 可调用入口；保留无关 Skill 和旧 Run/证据记录，不覆盖全域 4.x 或其他在跑 Run 绑定的方法。调用 `$small-loop-skill` 后，主 Skill 会随 Run 状态建议使用相应子 Skill。

## 验证

```text
python scripts/validate_repository.py
python scripts/quick_validate.py skills
python -m pytest -q
```

## 历史版本

SLK **v2.6.0** 继续通过 Git tag 和 Release 提供，方便既有 Run 或恢复使用。3.0.0 是新的方法边界，不覆盖历史发布。

## 许可证

MIT。
