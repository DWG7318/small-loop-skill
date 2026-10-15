# BI/WebBI 1.1.3 与 4.x 维修实施记录

范围：Owner 批准的两项工程。SLK 3.1.0 暂缓；本记录不是正式发布、部署或现场 Run 关闭回执。

工作区：`C:/Users/DWG/.config/superpowers/worktrees/SLK/bi-113-run09-repair`。
分支：`feature/bi-113-run09-repair`；基线 `7b2bb026d5c08ab1d46cd629ed845c2b25b3bc9a`。
BI 版本为 1.1.3；4.x 下一补丁号未选，源码方法版本保持 4.5.2，不能把本地候选称为已发布的 4.5.3。

## BI 的实际变化

- 1–30 个有效 CELL 按真实数量画格子，每行最多十格、最多三行；四个就是四格，短行不补空格或拉宽。超过三十个只压缩图形，精确总数、计划、详情不受限。
- 从初始计划与正式拆分历史生成只读计数摘要，例如 `0/(3+1) CELL`。缺少历史、非拆分增减或无法核对时显示实际总数，不猜初始数量；拆分父节点不重复算入有效总数。
- 齿轮设置改为 0–100%、步长 1% 的标准透明度滑条。保留默认值、显式 0 和旧设置；仅背景颜色使用 alpha，未给整个窗口或文字设置 opacity；删除原解释文字。
- 桌面/WebBI 共用展示规则。WebBI 仍只消费桌面上传的投影；没有引入其他 Run 数据来源、通知分类或同步组件。旧 1.1.0/.1/.2 上传仍兼容。
- 普通轻预检允许 BI 1.1.3 和规范的后续 1.1.x 补丁；原最低版本及 Run/schema/可见状态等检查保留。**预检收据本身不能证明二进制与源码匹配**，成品另用实际 hash 和构建 provenance 验证。

原有未开工详情隐藏、最新在上、单 Run 展开、双层滚动、绿点和 ntfy 行为由回归测试覆盖。没有用测试结果冒充真实 Windows 窗口的鼠标命中、100% 透明度或视觉验收；遵守 Owner 不用 Computer Use 的要求。

## 4.x 七类问题的处理边界

| 类别 | 已实施的最小变化 | 不能据此宣称的事情 |
| --- | --- | --- |
| R1 OCRV 材料入口 | 将不随材料体积增长的轻量入口与完整、hash-bound 原件/清单分开；要求判断前读完整目标与标准；读取工具未新增字符上限或截断 | 原生 OCRV 仍有自己的输入限制；未调用付费模型，不能保证模型每次都遵从指引 |
| R2 恢复关联 | 合法恢复输入归回中央原调用；历史记录显式绑定原冻结 Host 的路径/hash，当前 Host 仍掌握当前权限；Desktop 恢复记录走既有原件校验 | 不能从当前 Host 猜出丢失历史，不能补造旧启动或停止证据 |
| R3 OW/Temporal | 同 child 新回合需提交既有中央 resume 并读回后再改 adapter 指针；独立复现并修复关闭发生在 audit/notice await 中间时继续产生新工作的竞态 | 现场 audit83 缺原始输入快照，根因仍未完全确证；未重启、关闭或更改真实 Run |
| N1 暂停撤回 | 补 REQUESTED 的显式撤回，复用密封 resume-run 和原 pause/request/hash；不伪造 PAUSED、不扣未暂停时间、不重置 TOKEN | 撤回不是停稳证明，也不允许绕过其他故障保护修改参数 |
| N2 OW 指引 | 去掉不存在的顶层 verdict；分开 OW 自身活跃和观察对象 UNKNOWN；示例通过真实消费者与中央 writer 的隔离测试 | 自身证据缺失时不能编造 IN_PROGRESS/UNKNOWN/MISSING 或声称已记录巡查 |
| N3 收尾重复计数 | 保留全部投递行，只将已逐项验证为同一个原生协调回合的别名归并；单次查询复用原观测，不续写 observed_at | 不豁免所有 Supervisor 调用，不抹掉其他回合、执行器或未确认状态 |
| N4 探针投影 | 消费原生 compact diagnostic 时保留真实 UNKNOWN 和原因，避免合同不一致二次遮蔽 | launcher 退出、报告文件存在、transport FAILED 都不等于 executor 已停止 |

独立复核曾发现历史 OCRV 扫描在拒绝链接目录后仍将其入队；`6df4d0f` 已修复，独立验证 symlink/junction 均“拒绝后不读、不遍历”，该 finding 关闭。缺证和过期观测继续保留 UNKNOWN；本次不声称现场 76 行 UNKNOWN 已全部消失。所有实现均经过独立 spec、quality 复核；N2 另外做了指引应用测试。

## 验证与产物登记

以下均为本次在隔离工作区实际执行的结果，重复组合不能简单相加成独立用例总数。

- 前端：221 tests / 20 files、typecheck、生产构建通过。
- 轻预检/Skill/OW 示例组合：253 passed，另补普通 4.5.0/.1/.2 admission × 两入口的 BI 1.1.3 六项通过。
- Temporal 纯测试：238 passed，四个 service-starting case deselected，四个服务测试文件未运行；一个既有 asyncio marker 收集警告。
- 两份真实 Run09 历史已离线 SDK replay 成功；它们早于 audit74–83，只证明这些历史的兼容性，见 [R3 核验](2026-10-15-r3-ow-temporal-verification.md)。
- 完整 transport：**1760 passed、5 skipped，800.15 秒**。五个跳过均因 Windows 无真实 symlink 创建权限（另以 `-rs` 重核）；新 OCRV link 防回归有不依赖权限的模拟用例并独立通过。
- 完整 Rust workspace：**198 passed**，最终单独命令退出 0；包含 76 个 OW writer、39 个 write-flow、8 个 query 测试。
- 新编译 release 的 state/query 二进制：**97 passed**（state、Worker recovery、closure census）；含审查后补入的 host/cwd 错配用例。首次完整 transport 收集后新增的两项由这组及八项 bridge 回归覆盖。
- OCRV 材料/预检、独立 Python 模块、BI 状态合同：**62 passed**。首次发现两处测试仍断言 BI 1.1.2，只将发布断言改为 1.1.3，保留所有只读/窗口权限断言，再全部通过。
- 曾在完整 Rust 测试之后并行重建 debug CLI，遇到正在运行的隔离 Python 测试占用 EXE，附加 build 返回 Windows access denied；不是 Rust test 失败。最终单独 Rust 全测退出 0，并以不被占用的新 release 成品通过上述 97 项集成，不绕过文件锁或结束用户进程。
- 仓库/构建元数据/归档工具：**43 passed**。README 初次遗漏 1.1.3 源码候选说明，已补上“未发布、未部署”边界后通过；没有把已发布 1.1.2 的模块映射伪改成新版本。仓库结构/身份/Manifest 校验及 `git diff --check` 通过。

## 已准备好的本地成品

目录：`C:/Users/DWG/.config/superpowers/worktrees/SLK/bi-113-run09-repair/.codex/.tmp/bi113-run09-candidate`。

- `public/`：既有五产物构建脚本生成的自包含 BI EXE、state/query/cargo EXE、transport.pyz 及 `BUILD-PROVENANCE.json`；构建前捕获源输入，构建后封存产物，最终 `verify-release` 通过。
- BI 文件版本与产品版本均为 **1.1.3**，13,714,944 bytes，生产 custom-protocol 指纹通过，无 Vite 开发资源标记。没有打开真实窗口。
- `module-archives/`：BI、state-core、state、query、cargo、transport、OCRV、Temporal 共八个本地未发布模块归档，源码 hash 与当前工作区匹配，全部通过实际还原校验；BI 包含 WebBI dist。
- Temporal wheel 用 `pip wheel --no-deps --no-build-isolation --no-index` 离线构建，仅模板候选，没有启动或重新安装服务。state-core 另执行 `cargo build --release -p slk-state-core --locked --offline` 生成独立 rlib。
- OCRV 恢复既有 hash-verified 运行时，再覆盖八个当前接入文件；原生 `1.12.13-slkprobe.1.0.1` 二进制 SHA-256 仍为 `644cd50c1f3295e380a8da6a3d2818a8a3f585980a139ca9dfffff3a88e0f0e8`，不是声称重编了原生程序。

| 成品 | SHA-256 |
| --- | --- |
| BI EXE | `0cd66831bd33b119278fa233fb60082ced52199d212c033855e68f81c5a5bbc4` |
| state EXE | `b901751fce130a467df3b7f92b6a0ea9786ad32731f56760ce274dc298066d2c` |
| query EXE | `8bfc9581317596e58eb46a19fe8bc25a346c8c586b8ce19a77f8ee6c5ef8f65e` |
| cargo EXE | `6ae9fa9e80b915de014a6a62644f15f511dd55782218b9a4cdf07b7e7c60d556` |
| transport.pyz | `3ec400584652da76d3ab82b460259ed2991c5d9eb76be9a7a00d47ff3c36b0c7` |
| BUILD-PROVENANCE.json | `c3dbe91d203bc2c971370673aaf798e1bec962cf868c6b2cd4a7255a9feb9f63` |
| Temporal wheel | `f958c1d188ae96d70f26f8d84762bdc6c8c262351bb0cab6103e138854e59a2f` |

这些是开发阶段准备好的本地候选，不是完整离线安装包或已部署版本。发布号确定后仍需更新正式模块映射、发布包及部署回执；不得把候选路径直接当成在用版本。

## 发布边界

未 push、tag、release、改 Cloudflare、替换安装版、清理旧运行时或操作 3.x。`SLK-TOOL-MODULES.json` 仍是此前已发布版本的映射，不伪造新的独立仓库 commit/tag。新的本地成品与发布映射分开，正式发布时再对齐模块及成品。

Supervisor 的现场责任不变：根据真实情况补漏、排障并记录；本实现不把现场所有缺证都变成“必须等源码升级”。真实 Run 的验收、停止和行政收尾仍由原 Supervisor 负责。
