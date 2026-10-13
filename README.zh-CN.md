# Small Loop Skill（SLK）

当前源码版本：**4.5.1 — 源码与预编译分发已验证**。详见[451计划](docs/superpowers/plans/2026-10-13-slk-4.5.1.md)与[验证记录](VALIDATION-REPORT.md)。是否已安装以目标电脑的安装回执为准，不由版本文字推断；历史 Run 的身份和版本不改写。

SLK 是 Loop Engineering 的线性形态，用于一个有边界的中小工程 Run，或大型工程中相对独立的范围。一个 SLK 就是一个 Run，只含一条串行 CELL 路径。

## 核心关系

```text
Supervisor → Checker → Worker → Checker
                       FAIL → Supervisor → 同一 Worker → Checker
                 最终 PASS → Supervisor D2

Overwatcher：Supervisor 必需的直属 subagent，只观察并向所属 Supervisor 报告
Temporal：必需的连续性与计时保障，不拥有工程权威
```

任何 CELL 开工前，Supervisor 打开预编译 BI 1.1.1，通过 `preflight-basic` 确认已安装 SLK、DSH/OCRV、Skill、工具、状态、共用 Temporal，以及准确的角色身份/端点。成员接受简短角色说明和角色 eval；检查必需的正常直连通讯，不模拟一整轮工程。严格通讯演练保留为开发/回归工具，不再成为普通开工依赖。缺项采用预制配置和排障建议，未知问题由 Supervisor 决定。十分钟检查、二十分钟准备只是效率建议，不是截止、失败或停止门槛。使用者调用成品，不在每次开工编译或重建依赖。

Codex 担任 Supervisor，固定 canonical `gpt-6.1-sol`，每个 Run 由 Owner 选择 `high` 或 `xhigh`；OCRV 担任 Checker（Qwen3.8-Max）；DSH 担任 Worker（DeepSeek V4 Flash）。runtime、model、reasoning、Session、adapter、endpoint 与原生活动都由工具验证，不从提示词推断。Supervisor 还要按 DSH 实际能力给冻结方案定 CELL：大工作在派工前拆成可独立 D0/D1 的中小 CELL，不降低验收。目标是绝大部分 CELL 首轮 D1 PASS；第二次连续正式 D1 FAIL 后加强调查并考虑版本化拆分未接受范围，这是施工指引而非输出否决器，D1 权威仍属于 Checker。

Overwatcher 为必选：每个 Supervisor 只有一个原生直属 subagent，在该 Supervisor 的每个 Run 中登记。推荐高效低推理模型，不硬绑定具体型号。它每 600 秒交叉核验事实，只向所属 Supervisor 报告 `ANOMALY` 或 `UNKNOWN`；不转发正常工作、不重试投递、不修改 BI/TOKEN、不判断 D0/D1/D2，也不修复成员。解除一个 Run 不停止其他 Run 的巡查。只有所属 Supervisor 可叫停，任何退出仍须其确认；由真实父子身份和当前原生执行证明激活，不能把工具接受请求当作已运行。

Temporal 是多个 Run 共用的一套 headless 本地服务。每个 Run 拥有独立 `SLK.Start` 与 `SLK.Run`，保存准确原生启动确认、原发送者恢复、成员停留 30 分钟的 Supervisor 通知、每 20 分钟 OW 审计和独立关闭。它不裁决工程状态，也不替代成员直连通讯。SLK 不安装 Docker；必需连续性不可用或失败时，由 Supervisor 修复后才可继续。

Run 的测试、复核与验收仍归入 D0、D1、D2，不另建纯检验 CELL。证据不足保持未证明，不写成 PASS。RTK、Probe CLI 与 Ponytail 仍是可选效率工具，必须保留原生命令回退和原始证据。

跨 Agent 投递使用 `slk-transport`，绑定不可变端点、envelope、候选/证据哈希、密封角色凭据与 `slk.native-start/v2`。DSH/OCRV 只发布紧凑、原子化的原生活动与终态执行回执，大日志保留本地路径和哈希；Worker 续接只能一次，孤立原生任务返回 `WORKER_INCOMPLETE`；Checker 完成只能派准确的下一 Required CELL 或最终 `D2_READY`。详见 [`docs/transport/SLK-TRANSPORT.md`](docs/transport/SLK-TRANSPORT.md)。

## 状态与 BI

SLK 使用版本化 SQLite 权威状态、耐久证据、确定性 Markdown 导出和只读 LE BI。BI/WebBI 1.1.1 显示设备/版本、四角色身份、Agent 明确标注的新消息和归档 Run。WebBI 接收各设备独立上传的 Run，并可用服务器 URL、用户名、密码、Topic 四项配置 ntfy；BI/WebBI 不推断消息类型，也不修改工程事实。详见 [`docs/state/SLK-STATE.md`](docs/state/SLK-STATE.md) 与 [`docs/state/SLK-BI.md`](docs/state/SLK-BI.md)。

## Skill 集合

把 [`skills/`](skills/) 下同级目录按交付清单完整安装，不固定 Skill 数量。[主 Skill](skills/small-loop-skill/SKILL.md) 路由到规划、角色理解/团队准备、成员更换/归档、Temporal、OW、暂停/恢复、CELL 工作、记录、通讯恢复和收尾等短指引。准备排障与施工排障是分开的可选入口，不是新增必经阶段。它们属于同一方法，不能脱离 SLK Run 单独使用。

## 验证

```text
python scripts/validate_repository.py
python -m pytest -q
```

Windows 机器准备见 [`docs/runtime/SLK-WINDOWS-RUNTIME.md`](docs/runtime/SLK-WINDOWS-RUNTIME.md)。v3.0.8 保留纯提示词版本，v2.6.0 保留上一代单体方法。

## 许可证

MIT。
