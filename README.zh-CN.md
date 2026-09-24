# Small Loop Skill（SLK）

当前版本：**4.2.11**

SLK 是 Loop Engineering 的线性形态，用于一个有边界的中小型工程 Run，或大型工程中相对独立的中小范围。一个 SLK 就是一个 Run，Run 直接包含一条线性 CELL 路径。

## 核心关系

```text
Supervisor ↔ Checker ↔ Worker

        可选 Overwatcher（仅观察/恢复/升级）

CELL 派发 → Worker 施工与 D0 → 候选 → Checker 隔离 D1 → 通过/返工 → Supervisor D2
```

```text
规划 Run/检查 → 核对固定角色绑定 → 划分初始 CELL
→ 原对话创建 Supervisor 并交接 → Supervisor 角色 Eval → 根记录
→ Supervisor 创建 Checker → Checker 角色 Eval → Checker 创建 Worker
→ 通讯测试 → 第一个 CELL
```

Codex 固定为 Supervisor（`gpt-5.6-sol` + `xhigh`），OCRV 固定为 Checker（Qwen3.8-Max），DSH 固定为 Worker（DeepSeek V4 Flash）；runtime、model、session 和 adapter 身份由工具验证，不从提示词推断。Supervisor 在启动、上级求助、豁免、成员恢复和 D2 等边界按需激活；日常 CELL 由 Checker 与 Worker 直接推进，Supervisor 不在线等待逐 CELL 结果。D1 PASS 才增加验收进度；D1 INCOMPLETE 保持 D1 未闭合且 TOKEN 留在 Checker；只有正式 D1 FAIL 可以进入封闭的 `Checker → Supervisor → 同一 Worker` 返工路径，由 Supervisor 生成结构化指引但不重做 D1。一个 Run 还可绑定一个专属且不可复用的 Overwatcher Agent Session；绑定后由同一 Session 保持前台 active turn，每 180–300 秒完成一次固定主动巡查。它不是 heartbeat、定时任务、daemon、后台 Agent或正常通讯中继，不修改 BI/TOKEN，也没有 D0/D1/D2 权限。

Run 规划沿用 D0、D1、D2 三层检查，不为检查本身创建独立 CELL。建议优先用现有入口直接验证产品，把检查工具或环境故障与产品缺陷分开，复用仍有效的客观证据，不逐层重复完整验收或先搭建检查体系；证据不足保留未证明，不写成 PASS。SLK 接入已经完成或部分完成的项目时，先保留并复用已完成工作，再选择为可靠达到当前目标所需的合理最小施工路线、范围和工程活动，而不是只追求最小代码差异。

SLK 的指导帮助成员判断怎样继续。返工、通讯恢复、成员恢复、计划调整和豁免作为特定情境下的可用方法存在。

RTK、Probe CLI 与 Ponytail 是可选的外部效率工具。它们可以在 Codex 全域只安装一次，但安装不等于获得项目使用授权；每个 Run 仍由 Owner 决定是否启用。SLK 只显式调用，不启用自动 hook、MCP 或额外 Agent；原生命令与原始证据始终可以回退并作为事实依据。

跨 Agent 交接使用已验收的 `slk-transport`、精确角色端点和原生 Agent 激活。DSH/OCRV 只接收一个不可变、哈希绑定的 task file，并在任何终态结果之前写出 `started.json`；数据库行、后台消息、成功退出或按对话标题匹配都不等于投递。4.2.11 在 active-writer 冲突时向精确 canonical task/active turn 新发一条可审计消息，不再承诺 turn 结束后的延时自唤醒；恢复的 DSH 身份会重新校验，OCRV 在 Worker job 外 headless 启动，DPAPI 解码严格区分编码，命令退出/JSON 解析/业务状态保持分离，提交后的 runtime revision 会返回，Checker 只接收必要回执与原始日志的路径/大小/哈希索引。工具或传输失败保留同一 D1 attempt，不冒充产品 FAIL。详见 [`docs/transport/SLK-TRANSPORT.md`](docs/transport/SLK-TRANSPORT.md)。

## 4.0 状态与 LE BI

SLK 4.0 加入一个可配置的电脑全域数据根目录、版本化 SQLite 权威状态、耐久证据、确定性 Markdown 导出，以及独立的只读桌面 **LE BI**。4.2.11 中三工程角色仍只写各自事实；可选 whole-Run Overwatcher 仍是非权威观察者，不成为调度器。Run 终结后，Supervisor 可原子退役精确的 Checker 和 Worker，不创建替代者；LE BI 只依据该中央事实显示归档，同时保留 Supervisor 与全部工程历史。显式采用链延伸到 4.2.11；`slk-bi-query` 与 LE BI 仍只读。详见 [`docs/state/SLK-STATE.md`](docs/state/SLK-STATE.md) 与 [`docs/state/SLK-BI.md`](docs/state/SLK-BI.md)。

LE BI 按显式 Run 身份显示精简横条，不论其为独立 SLK，还是属于某个 CLK/GLK 项目。显式 predecessor lineage 区分当前、历史、重复活动与孤立身份，不再按标题或时间猜测合并。展开后显示三个技术角色、CELL 事实，以及有绑定时独立的 Overwatcher 运行保障条。BI 不确认消息是否真正投递，不恢复通讯，也不修改 Run；被接受的观察可以保守显示“活动未证明”，但不能改变工程进度。

## Skill 集合

当前方法位于 [`skills/`](skills/)：

- [`skills/small-loop-skill/SKILL.md`](skills/small-loop-skill/SKILL.md) 保存轻量身份和情境入口；
- 14 个同级子 Skill 分别处理 Run 与初始 CELL 规划、资源连续性、角色模型选择、封闭角色 Eval、成员生命周期、可选 Overwatcher 观察、CELL 派发与施工、记录、返工、调整、通讯恢复和收尾。返工需要根因诊断时，可以调用当前环境中适合项目的 Debug Skill。

这 14 个子 Skill 不是独立工程方法，不可脱离 SLK Run 单独使用。当前 Run 已选择 Small Loop Skill（SLK），并由主 Skill 或同集合流程路由到对应情境后，才使用相应子 Skill。

普通施工读取主 Skill 和当前情境对应的 Skill；情况变化时再加载相关指导。维护 SLK 提示词时，对已发现的误用同时修正主体正确做法，并在独立“负面提示词”章节写对应的“不要……”；已有提醒优先修改，不反复堆叠。负面章节补充同一方法，不另立工作体系或审批、停工清单。

## Run 记录

Supervisor 初始化 Run 及第一版施工方案。Worker、Checker、Supervisor 分别把自己的工程事实追加到配置好的 SLK 数据根目录；启用的 Overwatcher 只追加自己的完整巡查周期和运行观察。系统再从这一权威状态确定性导出 `SLK-RUN-<RUN-ID>.md`，不写入产品仓库。模板仍位于 [`skills/slk-record-run/assets/SLK-RUN.template.md`](skills/slk-record-run/assets/SLK-RUN.template.md)，用于保持可读结构与兼容性。

## 安装

把 `skills/` 下 15 个目录作为同级目录放入 Codex Skill 根目录。调用 `$small-loop-skill` 后，主 Skill 会随 Run 状态建议使用相应子 Skill。

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
