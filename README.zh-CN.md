# Small Loop Skill（SLK）

当前源码版本：**4.4.5 — 开放维修，未发布、未部署**。见[维修状态](VALIDATION-REPORT.md)；正在使用的 4.4.4 安装和原有证据不变。

SLK 是 Loop Engineering 的线性形态，用于一个有边界的中小工程 Run，或大型工程中相对独立的范围。一个 SLK 就是一个 Run，只含一条串行 CELL 路径。

## 核心关系

```text
Supervisor → Checker → Worker → Checker
                       FAIL → Supervisor → 同一 Worker → Checker
                 最终 PASS → Supervisor D2

Overwatcher：必需、非权威，只核实真假并向 Supervisor 报告
Temporal：必需的连续性与计时保障，不拥有工程权威
```

任何 CELL 开工前，Supervisor 必须打开 BI 1.1.1，建立四角色 `RUN_TEAM_REGISTRY`，证明工具/能力和设备 readiness，并绑定由七条准确通讯演练产生的真实隔离来源。第一份来源只能由一次性单 CELL Run 通过 `preflight-conformance-sample` 产生：运行证据位于 `slk-conformance/<SLK-CONFORMANCE-…>`，Worker 工作区是与其分离、clean、固定 HEAD 且无 remote 的样本 Git，其他角色保留真实原生 cwd，绝不能派产品工作。Temporal 使用内置两阶段标准适配器：中央 bootstrap 只创建一次真实工作流对，得到真实 identity/Host/OW 证据后再按显式样本或产品模式准入；产品 Run 永远以 `preflight-new-run` 绑定另一 Run 的密封来源，不重放假 FAIL/返工/D2。证据缺失、过期、猜测、循环依赖或不可查询时禁止派工。

Codex 担任 Supervisor，固定 canonical `gpt-6.1-sol`，每个 Run 由 Owner 选择 `high` 或 `xhigh`；OCRV 担任 Checker（Qwen3.8-Max）；DSH 担任 Worker（DeepSeek V4 Flash）。runtime、model、reasoning、Session、adapter、endpoint 与原生活动都由工具验证，不从提示词推断。Supervisor 还要按 DSH 实际能力给冻结方案定 CELL：大工作在派工前拆成可独立 D0/D1 的中小 CELL，不降低验收。目标是绝大部分 CELL 首轮 D1 PASS；同一 CELL 第二次连续正式 D1 FAIL 后停止普通返工，版本化拆分未接受范围，D1 权威仍属于 Checker。

Overwatcher 为必选，每 600 秒以交叉证据核验真实情况。它不转发正常工作、不重试投递、不修改 BI/TOKEN、不判断 D0/D1/D2，也不修复成员；只把 `ANOMALY` 或 `UNKNOWN` 报给准确登记的 Supervisor，并继续观察。一个 Run 只有一个独立 OW 角色绑定；只有 agent/model/endpoint/cadence 等事实完全一致时，同一个 active Session 才能同时服务多个 Run，而且每个 Run 必须独立定界。只有 Supervisor 可叫停 OW；任何退出都必须触发 Supervisor 二次确认的 runtime guard，未解除前不得派发下一 CELL。

Temporal 是多个 Run 共用的一套 headless 本地服务。每个 Run 拥有独立 `SLK.Start` 与 `SLK.Run`，保存准确原生启动确认、原发送者恢复、成员停留 30 分钟的 Supervisor 通知、每 20 分钟 OW 审计和独立关闭。它不裁决工程状态，也不替代成员直连通讯。SLK 不安装 Docker；必需连续性不可用或失败时，由 Supervisor 修复后才可继续。

Run 的测试、复核与验收仍归入 D0、D1、D2，不另建纯检验 CELL。证据不足保持未证明，不写成 PASS。RTK、Probe CLI 与 Ponytail 仍是可选效率工具，必须保留原生命令回退和原始证据。

跨 Agent 投递使用 `slk-transport`，绑定不可变端点、envelope、候选/证据哈希、密封角色凭据与 `slk.native-start/v2`。DSH/OCRV 只发布紧凑、原子化的原生活动与终态执行回执，大日志保留本地路径和哈希；Worker 续接只能一次，孤立原生任务返回 `WORKER_INCOMPLETE`；Checker 完成只能派准确的下一 Required CELL 或最终 `D2_READY`。详见 [`docs/transport/SLK-TRANSPORT.md`](docs/transport/SLK-TRANSPORT.md)。

## 状态与 BI

SLK 使用版本化 SQLite 权威状态、耐久证据、确定性 Markdown 导出和只读 LE BI。BI/WebBI 1.1.1 显示设备/版本、四角色身份、Agent 明确标注的新消息和归档 Run。WebBI 接收各设备独立上传的 Run，并可用服务器 URL、用户名、密码、Topic 四项配置 ntfy；BI/WebBI 不推断消息类型，也不修改工程事实。详见 [`docs/state/SLK-STATE.md`](docs/state/SLK-STATE.md) 与 [`docs/state/SLK-BI.md`](docs/state/SLK-BI.md)。

## Skill 集合

把 [`skills/`](skills/) 下 17 个同级目录作为完整包安装：[主 Skill](skills/small-loop-skill/SKILL.md) 加 16 个情境子 Skill，覆盖计划、容量、模型、角色 Eval/团队准备、Temporal、OW 观察、CELL 施工/检查/返工、记录、调整、恢复和收尾。它们属于同一方法，不是独立方法，不能脱离 SLK Run 单独使用。

## 验证

```text
python scripts/validate_repository.py
python -m pytest -q
```

Windows 机器准备见 [`docs/runtime/SLK-WINDOWS-RUNTIME.md`](docs/runtime/SLK-WINDOWS-RUNTIME.md)。v3.0.8 保留纯提示词版本，v2.6.0 保留上一代单体方法。

## 许可证

MIT。
