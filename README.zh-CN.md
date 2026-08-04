# Small Loop Skill（SLK）

Small Loop Skill 是用于一个有界 LCCoding Run 的严格串行工程执行方法。

当前版本：**2.5.0**

```text
Owner
  ↓
一个可见 Control Conversation
  ├─ Supervisor responsibility
  ├─ Checker responsibility（D1）
  └─ Verifier responsibility（D2/D3）
         ↕
一个长期唯一 Worker Conversation（D0）

一个 Run Patrol 保障对话（无技术权威）
```

Control 在一次正式决策中只能启用一种责任模式；同一时刻只能有一个 Active
CELL。Verifier 使用干净验证环境和不可变候选证据，但 SLK 不声称同一 Control
Conversation 内存在盲上下文隔离，也不创建第三个正式工程 Conversation。

## 执行边界

SLK 消费 LCCoding 冻结的 `RUN_CONTRACT`，执行唯一严格串行 GO 序列：

```text
RUN_CONTRACT
→ GO-001 → GO-002 → … → GO-N
→ D3
→ 当前 Run 的 Owner Acceptance
→ LOOP_OWNER_ACCEPTED
```

Calabash、集中项目级安全审计、交付和项目完成属于 LCCoding。SLK 仍执行 Run
Contract 要求的本地安全检查，并对已知严重风险实施硬刹车。

出现固定并行 Chain/Stage 时使用 CLK；出现分支、合并、回退、循环或自由 GO 图时
使用 GLK。

## 因果缺陷返工

D1 拒绝候选后，Checker 把一个 `DEFECT_LINEAGE` 绑定到不可变失败 Candidate、
失败指纹、复现证据与修复轮次。Worker 必须先稳定复现，或证据化说明不可复现；
随后一次只验证一个根因假设、执行一个最小实验，再提交最小根因修复。

对可稳定复现且可合理自动化的缺陷，D0 必须绑定 fail-before、pass-after 和风险
相称的回归证据；不适用时必须由 Checker 审核 exemption 与替代证据。同一 lineage
连续三个修复 Candidate 被 Checker 拒绝后，禁止第 4 次普通返工，转入架构复审、
方法边界退出或版本化 Contract 修订。

该纪律只嵌入 D0/D1 缺陷返工，不新增 D4、角色、可见 Conversation，也不引入
Chain/Stage/Barrier 或图激活。

## 运行保障

SLK 2.5.0 增加 Worker 专属四级 Checker 叫醒阶梯，禁止 Supervisor 长等待循环，
并从有效 D1/D2 receipt 推导分层进度。每个 Run 恰好一个无技术权威的巡检对话。
Supervisor 以可验证设备事实和累计工程负载冻结 CELL 容量；只有派工前
`CELL_CAPACITY_GATE=PASS` 才能交给 Worker。巡检工作量固定映射为
`LOW→10`、`MEDIUM→15`、`HIGH→30` 分钟，每周期必须完成全部最低错误清单。
Control 三种责任和 Worker 默认禁止置顶；非技术 Patrol 单独禁止 Pin/Unpin。
每个实质 verdict 恰有一条绑定的 Supervisor 进度；轻量 `RUN_RUNTIME_INDEX`
证明每次派工都具备容量、叫醒、进度和巡检证据，但不成为 Runtime。

详见 [运行控制与进度](references/runtime-control-and-progress.md)。
