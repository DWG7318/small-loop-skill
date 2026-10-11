---
name: slk-troubleshoot-preflight
description: Use when basic SLK preparation finds a missing component, unusable endpoint, role misunderstanding, or readiness failure before construction.
---

# Troubleshoot preparation

仅用于已启用 SLK 的 Run。这是可选排障入口和快捷预案，不是新的必经检查、错误白名单或自动裁决器；Supervisor 根据事实决定修复方法，新问题可直接调查。

## 最短处理路径

先读当前失败原文、准确组件/端点和最后成功项，分清“缺失”“不可用”“未知”。保留已完成准备，只修受影响项并复验，不重走全部准备。真实必需条件未成立就不派 CELL；建议耗时不是硬期限。

| 发现 | 优先动作 |
| --- | --- |
| 缺完整 SLK、Skill、DSH/OCRV/Temporal 或 BI 成品 | 用已验版本的完整交付包补缺、核对清单与哈希；先看已有安装，不现场编译或重新搭建整套环境。见[运行包说明](../../docs/runtime/SLK-WINDOWS-RUNTIME.md)。 |
| BI 启动失败、读库版本不匹配 | 先核对实际二进制/BI版本、数据根与原始错误；用兼容成品或标准生产者迁移修复。BI 只读，不手改库、不以重建空库掩盖数据。 |
| 地址、权限或凭据不能使用 | 核对当前登记、原生身份、adapter、密封消费者和保存后认证；确定性配置错先改错，不轮换所有凭据。身份/Session 变化交 `$slk-replace-member`。 |
| 没有真实消息却被要求“恢复交接” | 回当前登记/能力检查；未派 CELL 不必创造消息、候选或 D1。已有精确消息才用 `$slk-recover-communication`。 |
| 角色理解错误，OCRV 没有任意聊天入口 | 简明解释错误点，只复核变化；不伪造 Eval 回答。核对当前原生工具/config、MCP及已验证等价能力，首次真实审查保留准确 harness 与 start/result。 |
| Temporal 未就绪、OW 证据 UNKNOWN | 用 `$slk-manage-temporal` 查当前服务/workflow identity 和准确 parent/child/activation proof；UNKNOWN 不等于 child 已退出，不先强制重启。 |
| 工具查新失败、兼容更新或未选可选增强 | 记为提示继续；实际必需能力不可用才修复。升级先看兼容及正在运行成员，不自动换模型或影响其他 Run。 |

修复记录只需错误事实、原因/假设、实际动作、复验结果与下一合法动作。工具输出是事实，不是产品 D1；不要为准备搭检查项目、重演历史全链或等首 CELL/cycle 成功。无法安全继续，向 Supervisor/Owner 报准确缺口；不借排障新增费用、账号、破坏性操作或 Docker。
