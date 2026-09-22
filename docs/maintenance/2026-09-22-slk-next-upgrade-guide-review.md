# SLK 下一版本升级输入登记与边界复核

- 日期：2026-09-22
- 状态：`REGISTERED_AFTER_CONFLICT_FILTERING`
- canonical Run：`SLK-RUN-LCAS-RC08-GUI-WINDOWS-STABILITY-R3B`
- 当前正式版本：SLK 4.2.2
- 来源指南：`D:\LCaS\.codex\.tmp\SLK-RUN-LCAS-RC08-GUI-WINDOWS-STABILITY-R3B\SLK-NEXT-UPGRADE-GUIDE.md`
- 来源 SHA-256：`71ddac035497157e1e9c1abc7014d2c0c66ccdf7f8c231815fb5f856041343c4`
- 来源大小：21,360 字节；430 行
- 关联实战复核：[2026-09-22-slk-4.2.2-cell02-field-trial-review.md](./2026-09-22-slk-4.2.2-cell02-field-trial-review.md)
- inactive Supervisor唤醒实测：`D:\LCaS\.codex\.tmp\slk-diagnostics\inactive-supervisor-wake\INACTIVE-SUPERVISOR-WAKE-RESULT.md`
- 唤醒实测 SHA-256：`a72d4bf4f8563c709f29c9ef706c0f4bdbfff99a06b2773107172b33e4bf864d`

本记录把来源指南登记为下一版本候选升级输入，但只在本记录完成冲突过滤后的边界内具有维护权威。来源指南不是可执行授权；本记录不表示升级已经开始或完成，不授权修改 VERSION、源码、测试逻辑、全局安装或 LCaS Run，也不授权进入 CELL03、CELL04 或 D2。

## 1. 证据状态与优先级

### 1.1 `ACCEPTED_FACTS`

1. SLK 4.2.2 的 Run → CELL 公开结构、Worker/Checker/Supervisor责任边界、D1三态、同一 Worker最小返工和单一只读 Overwatcher方向不应推倒重来。
2. 首次实战暴露了启动证明过晚、active-writer交付冲突、跨 revision投影、linked worktree Git不可写、任务载体过长、instance ID不统一、Overwatcher观察误判、部署面版本漂移和成本不可分解等真实问题。
3. Run仍 active/open 时，唯一 Overwatcher foreground turn在最后权威状态落盘前结束；中央生命周期仍显示 active/observing。这是4.2.2执行合规失败，不是“4.2.2没有规定持续观察”。
4. 最后可见状态已经前进到 T013/CELL02 D1 PASS，但权威 Overwatcher cycle没有记录该最终状态；聊天说明不能替代审计记录。
5. 本次实战没有证明 DeepSeek V4 Flash能力不足，也没有形成自动升级模型的依据。
6. SLK 4.2.2正式 `D1_FAILURE_ESCALATION` 已实测成功唤醒 inactive/notLoaded Supervisor：同一消息产生匹配的 accepted、started、固定Supervisor回执和completed证据，唯一原生turn在19,083毫秒内完成，最终inspect为 `ALREADY_STARTED`且 `should_retry:false`。目标测试前不是active writer，测试后已恢复归档。
7. inactive/idle/notLoaded 与 active writer必须分流：前者直接按现有transport唤醒，后者才需要新的、可审计的native recovery message。该实测未写R3B TOKEN/BI，也未验证started之后Checker→Supervisor的中央原子handoff。

### 1.2 `ACCEPTED_CANDIDATE_REQUIREMENTS`

除下文明确冲突项外，NUG-01至NUG-16可作为下一版本设计输入。任何后续实现仍需独立设计、版本选择、TDD、完整验证和 Owner发布授权。

### 1.3 `CURRENTLY_DISABLED`

1. **BoM**：Owner已明确决定暂时不要。BoM不进入下一版本候选，不得自动触发、路由或实现。有效 D1 FAIL继续使用 `Checker → Supervisor结构化返工指引 → 同一Worker最小返工 → Checker重新D1`。只有Owner以后另行明确恢复，才允许重新登记为候选。

### 1.4 `OWNER_DECISION_REQUIRED`

1. **非终态更换 Overwatcher绑定**：正常合同不允许 per-CELL停止、释放或重建 Overwatcher。若宿主故障迫使更换 Session/turn，必须视为显式恢复/重绑定，并取得 Owner或 Supervisor按既有权威作出的明确授权；它不是普通 `RESUME`。

### 1.5 `REJECTED_BY_CURRENT_CONTRACT`

1. Run仍 active/open 时，把 Overwatcher正常置为 `SUSPENDED/RELEASED`，让同一或另一 Session以后再恢复。
2. 每个 CELL重新确认、重新启动或重新绑定 Overwatcher。
3. 以观察范围、暂时空闲或一个 CELL结束为由结束唯一 foreground active turn。
4. 把 BoM写回当前返工主链，或让 BoM成为角色、裁决者、TOKEN持有者或 Checker信息源。

## 2. 必须保留的正式基线

1. 公开结构只表达 Run → CELL；历史 `go_id`等只可作为兼容字段。
2. Worker负责施工与 D0；Checker/OCRV独立拥有 D1 PASS/FAIL/INCOMPLETE；Supervisor负责规划、派工、资源、交接与结构化返工指引，不得伪造 D1。
3. 只有证据足以确认候选存在实质阻塞缺陷时才可 D1 FAIL；覆盖、工具、候选身份或证据不足必须保持 INCOMPLETE。
4. 有效 D1 FAIL按 `Checker → Supervisor结构化返工指引 → 同一 Worker最小返工与D0 → Checker重新D1`闭环。
5. Worker保持 DeepSeek V4 Flash；适配器、工作区或上下文浪费不得伪装成模型能力失败。
6. 每个 Run最多一个 Overwatcher binding、一个专用 Agent Session和一个持续 foreground active turn；它跨越全部 CELL主动观察，直到 Run正式终结、取消或发生经授权的绑定替换。
7. Overwatcher只读观察、记录和告警：不拿 TOKEN、不改 BI、不施工、不返工、不决定 D1、不成为日常通讯 relay，也不创建 heartbeat、cron、daemon或后台 Agent。

## 3. P0 候选要求

| ID | 登记状态 | 候选要求 | 约束后的验收含义 |
|---|---|---|---|
| NUG-01 | 接受 | 启动证明与终态分离 | 原生任务被接受并取得身份后立即原子写 started receipt；terminal独立稍后产生。无真实 started evidence不得交接 TOKEN或声明已开始。 |
| NUG-02 | 部分已实测；剩余接受 | Supervisor状态分流与active-writer原生恢复 | inactive/idle/notLoaded已证明可由现有transport直接唤醒，不得绕道recovery。只有目标正在生成时，才使用新的 logical message ID和可审计 recovery receipt；旧 envelope保持 immutable/failed，不重发、不重复消费 TOKEN、不创建替代角色。另在独立临时数据库验证started后Checker→Supervisor中央原子handoff。 |
| NUG-03 | 接受 | revisioned atomic snapshot | TOKEN、latest event、message receipt和 BI projection必须来自同一 committed `snapshot_revision`；读者不得拼接不同 revision。 |
| NUG-04 | 接受 | Git可写性预检 | 隔离 Worker默认使用 `.git`位于可写根内的 standalone clone；linked worktree只有在 common git dir可写时才可派工。 |
| NUG-05 | 接受事实、改写方案 | Overwatcher turn提前结束与BI假 active | Run非终态时，turn结束必须显示为 continuity violation/inactive并阻止新派工；不得把它包装成正常 suspended/released。只有 Run终结、取消或授权重绑定才有合法 lifecycle transition。 |
| NUG-06 | 接受、收窄动作 | 最终观察先落盘 | 合法终结/取消/授权重绑定的顺序固定为：同 revision最终快照 → final cycle → lifecycle transition → 结束 turn。任一步失败即 fail closed，不得先结束再补记录。 |

P0施工应保持协议层优先和最小闭环：先统一 revision，再分离 started/terminal，再固化任务入口与Git预检，随后补 active-writer恢复，最后硬化 Overwatcher连续性与合法收尾。

## 4. P1 候选要求

| ID | 登记状态 | 候选要求 | 最小边界 |
|---|---|---|---|
| NUG-07 | 接受 | 不可变 task file + 短参数 | task file绑定 run、cell、attempt、role、message、candidate、result、evidence和hash；执行者先验证，不搜索旧 Run猜任务。 |
| NUG-08 | 接受 | 统一 instance ID生成和校验 | 生成时同时满足唯一、可归属和不超过64字符；transport和DSH共享同一判定。 |
| NUG-09 | 接受 | liveness与cadence拆分 | fresh exact native status决定liveness；延迟只影响cadence health。native `inProgress`时不得写 inactive。 |
| NUG-10 | 接受 | canonical instruction scope | 只接受 canonical task、binding revision之后且 sender/sequence可验证的控制消息；历史 source Run只作证据。 |
| NUG-11 | 接受 | incident生命周期 | 使用稳定 incident ID和 `OPEN → ACKNOWLEDGED → RESOLVED`；当前异常与历史事故分离。 |
| NUG-12 | 接受 | evidence ref存在性与hash | cycle登记前校验路径、可读性和hash；失败时只能写证据不完整，不得声明完整。 |
| NUG-13 | 接受、严格限域 | 轻量 wait-for-change | 只能在同一个 foreground active turn内有界阻塞，revision变化提前返回、最晚按基准间隔返回；不得演化为heartbeat、cron、daemon、新任务或后台 watcher。 |
| NUG-14 | 接受 | 原子版本一致性 | skills、binary、state docs、transport docs和schema由同一manifest约束；任一漂移则部署整体失败并保留旧版本。 |

## 5. P2 候选要求

| ID | 登记状态 | 候选要求 | 不得推导 |
|---|---|---|---|
| NUG-15 | 接受 | 分角色记录 uncached input、cache read、output、elapsed、tool-step、文件数和diff规模，区分定位/适配器/Git绕路与真实施工 | 不得因微型返工token高自动把 Flash升级为Pro或GPT。 |
| NUG-16 | 接受 | 记录cadence lateness、native/central一致率、revision差、未解决incident、evidence失败和单Session/turn连续时长 | 指标不成为新的调度层，也不阻塞正常主链。 |

## 6. Overwatcher新增结论

### 6.1 正常生命周期

1. Supervisor在 Run开始时确认一个 Overwatcher binding；一个 Run最多一个，不跨 Run复用。
2. 已绑定的 Agent Session启动一个 foreground active turn，并在所有 CELL之间持续主动观察；基准间隔可保持240秒，权威 revision变化可提前唤醒。
3. CELL交付、D1 PASS/FAIL/INCOMPLETE、返工、CELL切换或短暂无工程动作都不构成结束 foreground turn的理由。
4. Run正式终结或取消时，先记录最终同 revision cycle，再记录 terminal lifecycle，随后结束 turn并归档 Session。

### 6.2 非法中断与恢复

1. Run active/open但 exact turn不再 active，是 `OVERWATCHER_CONTINUITY_VIOLATION`，不是正常 suspended。
2. 中断发生后，BI必须区分“Run仍开放”和“观察已失活”，并阻止后续正式派工，直到恢复被审计确认。
3. 优先恢复同一 Session/turn；宿主不支持时，任何新 Session/turn都属于授权重绑定，必须有 replacement receipt、旧绑定终态和无重叠证明。
4. 恢复不得创建第二 watcher、heartbeat、cron、daemon或后台 Agent，也不得让 Overwatcher取得 TOKEN或修改 BI。

### 6.3 来源指南生命周期词的处置

- `ACTIVE`可保留为正常状态。
- `SUSPENDING/SUSPENDED/RELEASED/RESUMING`不得作为 Run非终态的日常流程；只可在未来设计中用于取消、终态收尾或授权重绑定，并须避免掩盖连续性违规。
- `EXITED`仅适用于 Run终态、取消或被合法替换后的旧绑定。

## 7. 下一版本的21个自动验收反例

以下完整登记来源指南的21项，并按现行 Owner决定规范化预期：

1. **Supervisor状态分流**：inactive/idle/notLoaded目标必须由现有transport直接唤醒并产生唯一accepted/started/completed链；started后在独立临时数据库原子完成Checker→Supervisor TOKEN handoff。只有目标正在生成时才走一个新recovery message；旧 envelope不重发、不重复执行。
2. **DSH started先于terminal**：启动后30秒内出现 started receipt和TOKEN handoff，terminal可在数分钟后出现；不得由terminal倒填started。
3. **OCRV started先于verdict**：启动后30秒内完成started/TOKEN；review完成前不得伪造PASS/FAIL。
4. **不完整检查保持INCOMPLETE**：工具中断、仅检查部分文件或候选SHA不明时，不得写FAIL或PASS。
5. **FAIL证据门槛**：只有完整证据确认阻塞产品缺陷时才FAIL；非阻塞建议不得升级为FAIL。
6. **单次返工链**：一个有效FAIL只触发一次返工链；同一失败包不得重复派发。
7. **BoM禁用**：当前合同下，任何自动BoM触发、路由或实现都必须拒绝；有效FAIL只能进入Supervisor结构化返工指引闭环。Owner未来若明确恢复BoM，必须作为新的版本输入重新设计和验收，不能复用本项作为正例。
8. **Git可写预检**：standalone clone可直接commit；common git dir不可写时在模型启动前拒绝。
9. **instance ID边界**：64字符边界在transport/DSH一致；超长值在启动前由共享validator拒绝。
10. **task file隔离**：Worker只读指定且hash匹配的task file；目录中的旧Run文件不能影响当前任务。
11. **快照原子性**：并发handoff/event写入时，reader只能看到完整旧revision或完整新revision，不得看到混合状态。
12. **非终态turn结束**：Run active/open但exact Overwatcher turn结束时，BI必须显示continuity violation/inactive并阻止新派工；不得显示observing，也不得视作正常suspended。
13. **安装一致性**：skills/bin/docs/schema任一版本不一致时整体安装失败并保留旧版。
14. **cadence不冒充liveness**：exact turn持续`inProgress`但cycle晚到700秒时，只能写`CADENCE_LATE`，不得写inactive。
15. **历史指令隔离**：source Run出现时间更新但过期的Owner文本时，只服从canonical task在binding revision之后的已验证指令。
16. **incident收敛**：异常恢复后从`current_anomalies`移除，进入带resolution revision的历史记录。
17. **证据引用校验**：路径拼错、文件不存在或hash不符时，cycle只能标记证据不完整。
18. **同turn轻量等待**：权威revision变化时wait-for-change提前返回；无变化时约240秒返回；全过程不创建heartbeat/cron/daemon或后台任务。
19. **合法终结顺序**：仅在Run终态、取消或授权重绑定时，先记录含最终TOKEN/event/D1的final cycle，再写lifecycle transition，最后结束turn。
20. **final-cycle失败关闭**：最终cycle写入失败时，不得结束turn或把中央状态标成正常释放。
21. **全Run唯一连续观察**：整个Run只有一个binding、一个Session、一个活跃foreground turn；CELL边界不得重新确认或重建。新绑定只允许经授权恢复，并必须有显式receipt和无重叠证明。

## 8. 发布门禁

下一版本候选只有同时满足以下条件，才可请求发布授权：

1. 经本记录规范化的 P0六项及21个自动反例全部通过；BoM保持禁用并由负例机械拒绝，除非Owner以后产生新的明确版本决定。
2. 不改变 Run → CELL公开结构，不新增第二 Checker、第二 D1或额外审批层。
3. 不降低 D1质量，不把INCOMPLETE伪装成PASS/FAIL；Supervisor不接管D1。
4. Flash仍为Worker，不因成本、返工或适配器问题自动升级模型。
5. Overwatcher仍只读、全Run唯一且持续active，无TOKEN、无BI写权限、无heartbeat/daemon。
6. 旧Run、4.2.2证据和失败消息保持immutable。
7. skills、binary、docs、schema及manifest版本/hash完全一致。
8. repository validator、Skill测试、transport测试、Overwatcher反例和版本一致性门禁全部通过。
9. 在独立沙箱完成最小实战，不把当前 LCaS R3B用作升级试验场。
10. 实现、安装、push、tag、Release和全域替换均另需其适用授权；维护输入登记本身不授予这些权限。

## 9. 明确非目标

下一次升级不得：

- 修改 LCaS产品候选、推进CELL03/CELL04/D2或重写任何历史Run证据。
- 推翻Worker/Checker/Supervisor通讯拓扑，或让Supervisor深度参与日常施工和D1。
- 引入第二Checker、第二D1、新审批层、常驻服务、后台Agent、高频heartbeat或重型workflow engine。
- 让Overwatcher成为必经relay、TOKEN持有者、BI写入者、工程角色或产品验收者。
- 触发、路由、实现或恢复BoM；Owner未来若明确恢复，必须另行形成新版本输入，且不得直接把BoM变成SLK角色或裁决者。
- 把所有finding变成FAIL，或把工具/证据不足写成产品FAIL。
- 自动把Flash升级到Pro或GPT。
- 建造与上述缺口和反例无关的大型验证平台。
- 把文档登记写成SLK已经升级、安装或发布完成。

## 10. 候选交付物索引

未来获批施工时，最小候选交付物应覆盖：

1. 一页协议变更及向后兼容说明。
2. snapshot revision与Overwatcher continuity/lifecycle schema。
3. adapter started/terminal分离。
4. immutable task file、短参数和instance ID共享validator。
5. standalone clone默认策略与Git writable preflight。
6. active-writer native recovery与receipt。
7. Overwatcher cycle、incident、evidence ref、wait-for-change和终态收尾。
8. 本记录规范化后的21个自动反例。
9. 发布manifest及安装面版本/hash一致性检查。
10. 独立沙箱实战报告，覆盖成本、准确性、状态一致性、全Run连续性和终态收尾。

## 11. 当前维护结论

- 来源指南已完成身份核验并登记，但必须经过本记录的冲突过滤使用。
- 当前可直接进入未来设计评审的是：NUG-01至04、NUG-05/06的连续性改写、NUG-07至16及相应规范化反例。
- BoM当前明确禁用、不进入下一版本候选；Run非终态的Overwatcher正常暂停/释放也不属于已批准设计。
- 本次只形成文档级维护输入；SLK仍为4.2.2，未实施、未安装、未发布，也未改变 LCaS R3B任何状态。
