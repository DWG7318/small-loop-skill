# Small Loop Skill（SLK）

Small Loop Skill 是用于一个有界 LCCoding Run 的严格串行工程执行方法。

当前版本：**2.3.1**

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
