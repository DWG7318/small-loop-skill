---
name: slk-record-run
description: Use when an active Small Loop Skill (SLK) Run needs its root record initialized or a member is preserving work and handoff facts.
---

# Record an SLK Run

> **使用边界：** 本 Skill 是 Small Loop Skill（SLK）的子 Skill，不可脱离 SLK Run 单独使用。
> 适用前提是当前 Run 已选择 `$small-loop-skill`，并由 SLK 主 Skill 或同集合流程路由到本情境。

## 当前目标

在中央 SLK 数据根维护一份可读、可追查的 Run 状态，让接管成员和 Owner 理解已经做了什么、检查了什么、出现过什么问题以及下一步在哪里；SQLite 是状态事实，`SLK-RUN-<RUN-ID>.md` 是自动导出，完整工程历史留在中央状态，令牌只携带当前状态集合与记录指针。

通过 Eval 后，Supervisor 使用 `slk-state init-run` 写入 Run 定义、计划、方法版本、显式 predecessor（适用时）、身份和端点，再使用 `$slk-manage-team` 建立后续成员。即使成员在其他 worktree 施工，三个工程角色与可选 Overwatcher 都指向同一中央状态；Checker 的 D1 隔离和 Supervisor 的 D2 顺序保持不变。

历史上独立初始化的重复 Run 不属于普通 predecessor：只有 Owner 明确指定 canonical/source ID 后，canonical 当前 Supervisor 才可提交精确快照执行 `slk-state reconcile-run-identities`；旧 Run 需要当前语义时再以独立 Owner 证据执行 `slk-state adopt-method-contract`。两类回执追加且不可变，只更新身份元数据或有效方法版本，origin 版本与全部工程历史、角色、证据和 TOKEN 保持不变。

## 各角色写自己的事实

- Worker 通过 `slk-state` 记录施工变化、资源占用与恢复、候选、最低 D0、判断过程、风险和交付对象；本地 D0 尝试与正式候选、D1 返工分别标明。
- Checker 记录派发、D1 方法与结果、错误、返工建议、CELL 与 Run 进度，以及从实际工作中得到的 CELL 容量事实，并通过 `slk-state` 追加。
- Supervisor 仅在被激活时记录启动交接、计划调整、豁免、成员恢复、D2、归档或最终结论，并通过 `slk-state` 追加；关键失败、重要决定和未执行事项建议在继续调整前及时追加，保留可能被后续操作覆盖的必要证据，交接前补齐，不接管日常进度记录。
- Overwatcher 只用独立凭证追加完整八项巡查 cycle，以及通讯、活动证明、记录冲突、恢复升级和自身归档等 operational observation；只更新自己的 active/cycle 状态，不要写 D0/D1/D2、计划、角色替换、Run 结论、TOKEN 或 BI。

## 建议记录方式

- 接收者在令牌激活本轮后的第一步用 `slk-bi-query` 先比较编号与身份；发送者只在原生启动成功后用 `slk-state handoff` 原子推进当前有效令牌和最后真实流转，同号或旧号不改指针，不预写尚未发生的流转。
- CELL 历史、错误、失败尝试、返工、豁免和重要决定采用追加记录；后来的通过结论保留前面的真实过程。
- 命令和结果保留简洁摘要及可复查的原始证据路径或哈希，并区分实际执行、间接验证与推断；工具或环境故障与产品缺陷分别记录，保留实际处理和未证明部分。
- 三个工程角色各写自己的事实，Overwatcher 只写自己的运行观察；Owner、其他 Agent 和 BI 只通过 `slk-bi-query` 读取。记录保持工程上足够完整，从当前节点与相关条目读取；原始日志按失败定位查阅，不复制整段令牌历史或大日志。

## 工作顺序

每次角色行动的倒数第二项建议用 `slk-state` 写入自己的事实；最后一项完成真实传输并在成功后推进 `SLK TOKEN`。完成传输后结束本轮工作，不跟踪下一对话；Markdown 自动导出失败只形成 warning，可稍后重新生成。

## 负面提示词

- 不要等到最后交接才补写关键失败或重要决定，不要手工改写自动导出/BI、越权写他人事实，或把尚未执行写成已经执行；不要抹掉错误、返工或豁免历史，也不要把简要记录扩成逐命令审计。
- 不要只保存二次总结或结论 JSON 而丢失决定验收结论的原始证据位置，也不要把代码未改、代理环境结果或逻辑推断登记成已经执行的真实环境验证。
- 不要按标题自动合并 Run、直接改 SQLite、伪造旧凭证、另建替代 Run 或用提示词声称版本已升级；管理操作使用闭合 Owner 证据、显式 ID、精确快照和不可变回执。
