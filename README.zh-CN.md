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
```

Control 在一次正式决策中只能启用一种责任模式；同一时刻只能有一个 Active
CELL。Verifier 使用干净验证环境和不可变候选证据，但 SLK 不声称同一 Control
Conversation 内存在盲上下文隔离，也不创建第三个可见 Conversation。

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

## Worker 信号连续性

每次正式 CELL 派工使用一个耐久 dispatch identity 和一条绑定信号流：

```text
ACK → PROGRESS* → BLOCKED | FINAL
```

终态信号自动唤醒 Control。未摄取终态明确表示为 `BLOCKED_UNREAD` 或
`COMPLETED_UNREAD`，不能再被误判为一般沉默，也不能据此创建第二 Worker。
Control 只摄取一次，并原子同步路由、Run 状态、可见进度和 Owner 可见状态。
只有证据证明 `TASK_NOT_DELIVERED_PROVEN` 才能向同一持久 Worker 重新派工。
