# Run09 实战升级报告接收与分流

接收日期：2026-10-15，北京时间。目标：完整核验并去重登记实战报告，纳入已获 Owner 确认的下一版范围；本阶段不修代码、不部署、不处理 LCaS Run 收尾。

## 接收步骤与证据

- [x] 核对报告字节数/SHA-256并完整读取。
- [x] 核对索引附件与当前版本计划，区分重复、新确证、待查及非 SLK 责任。
- [x] 原样归档报告，按版本线登记最小改进和回归范围。
- [x] 校验归档字节及仓库 Manifest；这只证明登记完整，不是任何缺陷已经修复。

原件：`D:/LCaS/.codex/.tmp/SLK-RUN-LCAS-RC08-IDENTITY-AWARE-MESSAGE-DELIVERY/prepared/slk-next-version-upgrade-report-20261015.md`。

归档：[完整原报告](reports/2026-10-15-lcas-run09-slk-upgrade-report.md)。原件与归档均为 **18377 字节**，SHA-256 **3762a58678afa975dc1789ce8662a8f1e86d910bdcb7f74296c867419b38bae5**。

接收方独立核对：报告表格中的 10 份 prepared 附件均与所列字节数/SHA 匹配；中央导出为 860251 字节、SHA `4048a341302dfde25f245dc2ac220d9c181fcbda7090ff96ce5b1ea6561895a1`，也匹配。安装 `slk-transport.pyz` 的 SHA 仍为 `cd861bcd0b90e929ebc93a98e8875d53928b8e64c861f8dc3c87e58749802ea3`。

已完整读取主报告及 `cell03-method-incidents.md`、`overwatcher-cycle40-field-confusion.md`、`close-run-after-d2-temporal-20261015-result.json`。其余大附件本次只核对完整性，不把哈希一致冒充逐条根因复核。任务内 `role_host.py` 只有 SHA、没有唯一绝对路径，本次未核对该副本；实施关联修复前须定位原件。报告中的 Rust 38 项、Temporal 4 项和历史回放结果属于现场已有验证，本接收阶段没有复跑。

## 准确版本与范围

范围更新（2026-10-15）：Owner 已要求 **3.1.0 暂缓**，原因是该线工作尚未结束。下列 3.1.0 列仅保留为将来分流记录；当前策划只覆盖 BI/WebBI 1.1.3 和 4.x 维修，见 [两项方案草案](2026-10-15-bi-113-and-4x-repair-proposal.md)。没有启动修复、发布或部署。

- 来源是 **SLK 4.5.2 build2 / Run09 / plan4**，不是下一版编号。
- Owner 已确认的下一条方法升级线是 **SLK 3.1.0**，沿轻量 3.x 线吸收适用原则，并接入届时最新版预编译 BI。当前 3.0.9 不动；不搬入 4.x 的 OW、Temporal、中央生命周期或关闭 census。
- **BI / WebBI 1.1.3** 继续按既定显示、透明度、计数及兼容计划推进。该报告没有确证独立 BI 新缺陷；只延续“记录真实状态、不将 UNKNOWN/后台结束伪装为完成”的展示边界。
- **4.x 专有实现维修** 单独登记在本文，目标补丁编号尚未获 Owner 确认，不擅定 4.5.3 或其他编号，不冒称已并入 3.1.0。

## 去重登记：3 类重复 + 4 类本轮新确证

以下“确证”沿用现场报告分类；接收登记不等于本机独立复现或正式修复。

| ID | 问题与去重边界 | 3.1.0 适用内容 | 4.x 原入口最小修正与回归 |
| --- | --- | --- | --- |
| R1 | OCRV 8000 字符门槛重现；10413 字符、模型创建前拒绝与缺报告是同一阻塞链，不另计 D1 FAIL | 保留完整目标/验收与原件引用，减少重复背景，不加任意长度拒绝或静默截断；先核实实际 OCRV 工具限制 | 查清 SLK 附加门槛与原生入口各自实际作用，移除已证实的任意门槛；超过 8000 的真实资料可完整读取并交付，不能换一个固定阈值 |
| R2 | 合法恢复/历史计划与当前 canonical 来源错配；历史 Host 关闭拒绝是同类新表现，不另立缺陷 | 恢复保留原成员、Session、任务与候选；历史证据按原身份/计划核对，当前责任用当前版本；不重写旧证据 | 修原调用→合法 recovery activation 关联与历史 Host 选择；同 Session/不同合法计划正例通过，错身份/错 hash 反例仍拒绝 |
| R3 | OW/Temporal 同类审计反复失败；audit74–83 不拆成多个缺陷 | 区分工程通过、实际后台结束、归档完成；Supervisor 在既有授权内现场处理，不因行政 pending 留无意义后台 | 先查原 Temporal 事件分辨解绑后旧告警的产生/积压/投递；复用原 close-run 结束准确 pair，不停共享服务，不重开 OW/工程 |
| N1 | REQUESTED 未生效暂停无法撤销 | 澄清“申请暂停”不等于“已经暂停”，撤回未生效决定不伪造暂停和计时；不新增状态机 | 复用现场最小转移，保持 pause_id/revision/权限/TOKEN；回归普通 PAUSED、撤销、幂等、计时与原历史回放 |
| N2 | OW 顶层字段和消费者不一致；自身活性与对象状态混淆 | 不适用：3.x 不因此新增 OW | 在原 OW 子 Skill 加一个消费者实际可接受的紧凑示例；自身 IN_PROGRESS 与对象 UNKNOWN/ACTIVITY_UNPROVEN 可同时为真，不增加宽松 schema |
| N3 | 多通知指向同一主管原生 turn，被重复计未停调用并重复读历史 | Supervisor 保持在线协调；通知不是独立成员/任务，不要求主管先退出才能收尾 | 按精确 thread/turn 等原生身份归并；只识别当前精确协调实体，不豁免全部 Supervisor 或真实旧 writer；单次复用原观测、不刷新 observed_at |
| N4 | OCRV inspector 输出不能被自身 TASK_ACTIVITY 消费者接受 | 不因此强制引入探针；使用任何既有状态工具时，不将适配失败当仍运行或已停止 | 修现有投影接缝，保留 Run/message/task/时间；覆盖 launcher 已结束但 executor 活跃的反例，不用报告文件或 transport FAILED 伪造 STOPPED |

现有主库仍可定位 R1 的 `src/slk_transport/adapters/ocrv.py::DEFAULT_REVIEW_CAPACITY.max_background_characters=8000`，以及 N4 的 `_file_native_probe → inspect_ocrv_session → validate_native_task_activity` 接缝。静态存在只用于定位后续回归，不证明其他容量默认值都实际挡工。历史 4.4.3 文档曾描述原生 8000 限制；后续修订必须分清工具版本和生效入口，不以新报告覆盖旧现场事实。

## 已有临时恢复，不能重新包装为正式修复

- R1 完整原件索引化已使原 Checker 恢复，但安装门槛未因此消失。
- R2 历史 Host 修正只消除初始拒绝，完整关闭未通过。
- N1 现场最小修正已有报告列出的 Rust/Temporal/回放证据；应复用而非重造暂停系统，仍须与正式源码差异和适用版本核对。
- N2 已有原 cycle40 标准消费者成功回执，优先修子 Skill 语义与示例，不再加组件；不顺带宣称恢复关联也已修好。
- N3 单次缓存只减少重复读取，不修复 MCP 失败或 stale 证据。
- 原安装 CLI 已返回 `PAIR_CLOSED`；报告包含独立 SDK 核对两工作流于北京时间 2026-10-15 16:09:58 均 COMPLETED。关闭这一准确 pair 不需要另升代码。

## 待查、责任与验收边界

- 第二次 census 的 188 行是证据行，不是成员数：STOPPED 86、STAGED_NOT_STARTED 25、COORDINATING 1、UNKNOWN 76。
- UNKNOWN 分组保持原数：MCP 请求失败 40、投影不匹配 5、endpoint 不可读 2、历史启动/停止缺证 19、原调用 active/unknown 6、旧观测 stale 4。40 条 MCP 失败不能全部归咎旧 host 别名；2 个 endpoint 尚未定因；19 条缺证不能批量改 STOPPED；audit83 的原事件时间链尚需核验。
- 产品 D1 失败、Worker 原件遗漏/草稿失实、无独立证据的模型容量猜测、Windows 外部中断/权限问题，以及 Supervisor 自己的 Session/hash/参数/命令错误，不并入 SLK 已确认缺陷总数。
- Supervisor 是现场补漏与记录的主要责任人；在原授权内补交原件、准确恢复原节点并标明实际操作者，不把所有现场问题推给 SLK 源码升级。工程判断仍归原 Worker/Checker/Supervisor 的既有职责，不能伪造正常交接或 PASS。
- 正式实施时逐项用本轮失败做小回归，再验证必要的真实消费者；保留身份、授权、证据和工程验收，不新增长度/时长/材料额度硬门槛，不增加审批器、中继、轮询后台、自唤醒或管理底座。
- LCaS 工程 D1/D2 通过、OW 真实退出、Temporal pair 完成是报告事实；中央 RUN_CLOSED、成员退役、缓存清理与 Main 交付仍 pending。本接收工作不修改这些状态，不重开 CELL/D2/OW，不联系成员或替代项目收尾。

相关计划：[SLK 3.1.0](2026-10-14-slk-3.1.0-plan.md)、[BI / WebBI 1.1.3](2026-10-14-bi-1.1.3-plan.md)。

