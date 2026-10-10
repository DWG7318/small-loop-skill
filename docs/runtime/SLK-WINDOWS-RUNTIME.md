# SLK 4.4.4 Windows 运行环境配置指引

本指引用于在一台新 Windows 电脑上建立可运行 SLK 4.4.4 的机器环境。它不改变 SLK 方法，也不替代项目内的 17 个 Skill。

## 先分清三个层级

1. **电脑级环境，只配置一次**：DSH、OCRV、`slk-transport`、`slk-state`、`slk-bi-query`，以及它们的凭据和数据目录。多个项目复用这一层。
2. **项目级部署**：把 SLK 4.4.4 的 17 个 Skill 放入该项目使用的 Skill 根目录。SLK 不因此变成电脑全域工程方法。
3. **Run 级绑定**：每个 Run 重新登记 Supervisor、OCRV Checker、DSH Worker 与必需 Overwatcher 的精确身份、Session 和端点，打开 BI 1.1.1，证明共享 Temporal 服务/本 Run 工作流就绪，并完成七条通讯演练后才可派工。

仅完成第 2 层不能启动跨 Agent SLK。

## 已验收基线

SLK 4.4.4 验收时使用：

- Windows、PowerShell 7、Git、Python 3.10 或更高版本、Node.js/npm 与 Rust/Cargo；
- `@deepseek-ai/dsh@0.1.5-rc.2`；
- `@alibaba-group/open-code-review@1.12.13`；
- DSH：`deepseek-official / deepseek-flash`；
- OCRV：`dashscope-tokenplan / qwen3.8-max / medium`；
- SLK 4.4.4 源码，用于构建无第三方依赖的 `slk-transport.pyz`、状态/查询/Cargo CLI 和只读 BI；Temporal SDK/服务由独立受控环境提供，不进入核心导入路径。

升级这些版本应重新验证，不把“能够启动”直接当作与上述基线兼容。

## 推荐目录

盘符可以调整，但同一台电脑应保持稳定并使用绝对路径。例如：

```text
D:\SLK                 SLK 4.4.4 源码
D:\DSH                 DSH 程序和启动配置
D:\OCRV                OCRV 程序和 Checker Adapter
D:\SLK-RUNTIME\bin     SLK 机器级可执行文件
F:\SLK                 SLK 状态、记录与传输证据
F:\DSH                 DSH 可变状态
F:\OCRV                OCRV 可变状态
```

程序与可变状态分开，方便多个项目复用，也避免把运行记录写入产品仓库。

## 1. 检查基础工具

在 PowerShell 中检查：

```powershell
git --version
python --version
node --version
npm --version
pwsh --version
cargo --version
```

缺少的基础工具先按组织认可的来源安装。SLK 不需要 Docker。

## 2. 配置 DSH Worker

在 `D:\DSH` 放置受信的 DSH 机器配置，至少包含：

```text
package.json
package-lock.json
dsh-slk.cmd
dsh-slk.ps1
slk-template\settings.yaml
```

锁定依赖应包含：

```json
{"dependencies":{"@deepseek-ai/dsh":"0.1.5-rc.2"}}
```

然后安装锁定依赖：

```powershell
npm ci --prefix D:\DSH
```

`settings.yaml` 的验收模型为：

```yaml
agent-default-model:
  provider: deepseek-official
  model: deepseek-flash
```

在 Windows **用户环境变量**中配置 `DEEPSEEK_API_KEY`，凭据值不写入脚本、项目、端点、状态库或证据。设置后打开新的终端，再检查：

```powershell
D:\DSH\dsh.cmd --version
D:\DSH\dsh-slk.cmd runtime-check --profile headless "只回复 DSH_RUNTIME_OK"
```

`dsh-slk.cmd` 应为每个并行 Worker 接受唯一的 `instance-id`，并把可变状态隔离到 `F:\DSH\runs\<instance-id>`。多个 Worker 可以并行；首次使用相同冷前缀时可以错开第一条请求，以提高 DeepSeek 缓存命中，后续无需人为串行化。

如需 RTK、Probe CLI 或 Ponytail，把经 Owner 选择的工具配置到 DSH 的共享 Skill 目录即可；它们不是 DSH 或 SLK 的启动前提。

准备 Eval/报告通过既有已授权原生准备请求，让原 Worker 在 `workspace-write` 允许的工作区内输出完整原件；可信准备宿主只原字节保存到 Git 外证据目录、核hash并执行 `validate-role-eval --response <原件路径>`。准备不借Checker权限、不伪造正式WORKER_TASK，也不算正常通讯腿；不得直写未授权外部目录、依赖易消失TEMP或从stdout代码块另造答卷。正式任务才沿现有标准描述符的工作区 `result_path`（`.slk-transport/<message_id>/worker-result.json`），由可信适配器原样保存到Git外attempt根后清理drop。接收者必须实际回读原件并核hash；路径已发、宿主可读或unit tests都不代表成员回读通过，失败如实保留，不扩大沙箱。

## 3. 配置 OCRV Checker

在 `D:\OCRV` 放置受信的 OCRV Checker 配置，至少包含：

```text
package.json
package-lock.json
ocr.cmd
ocr-slk.cmd
ocr-slk.ps1
slk-checker.cmd
slk_checker_adapter.py
slk\slk-d1-rule.json
tests\...
```

锁定依赖应包含：

```json
{"dependencies":{"@alibaba-group/open-code-review":"1.12.13"}}
```

然后安装锁定依赖：

```powershell
npm ci --prefix D:\OCRV
```

在 Windows 用户环境变量中配置 OCRV 所使用的 DashScope Token Plan 凭据。凭据名称由已验收启动配置读取；不得把值复制到 D1 请求、结果或仓库。OCRV 的机器配置应选择：

```text
provider = dashscope-tokenplan
model    = qwen3.8-max
effort   = medium
state    = F:\OCRV
```

检查原生运行时与 Checker Adapter：

```powershell
D:\OCRV\ocr-slk.cmd version
Set-Location D:\OCRV
python -m unittest discover -s tests -p "test_*.py" -v
```

OCRV 是 D1 Checker，不是附加证据工具。先原样交出全部输出；只有原 Checker 的显式 `slk_checker_decide` 才记录整个 CELL 的 `PASS`、`FAIL` 或 `INCOMPLETE`。宿主不从退出码、格式或覆盖猜结论，不由 Worker/Supervisor 代判；原件读取和规则配置见 [OCRV 配置指引](../../integrations/ocrv/OCRV-SLK-CONFIGURATION.md)。

OCRV、PowerShell、Codex App Server、DSH 和传输辅助进程默认使用统一的 hidden/no-window 启动参数；后台检查不弹出控制台窗口。只有 Owner 明确需要交互窗口时才改为可见启动。

## 4. 构建 SLK 传输和状态工具

从受信的 SLK 4.4.4 源码构建机器级工具。正式 artifact 入口先用 Tauri production build 嵌入 BI 前端，再构建其余工具；不要用普通 `cargo build --release -p slk-bi-desktop` 生成可发布 BI：

```powershell
Set-Location D:\SLK
pwsh -NoProfile -NonInteractive -File scripts\build_release_artifacts.ps1 `
  -OutputDirectory D:\SLK-RUNTIME\bin `
  -CargoTargetDirectory F:\SLK\build
```

该脚本只在当前 headless 控制台运行 `tauri build --no-bundle`，并用 release fingerprint 与开发资源标记检查 `slk-bi-desktop.exe`。`build_local_package.py` 会再次拒绝仍含 Vite 开发入口的 BI。正式本机替换随后执行：

```powershell
python scripts\build_local_package.py --repo . --artifacts <artifact-root> --output <package-root>
python scripts\verify_local_install.py --root <package-root> --package-mode
pwsh -NoProfile -NonInteractive -File scripts\install_local.ps1 -PackageRoot <package-root> -CodexHome $env:USERPROFILE\.codex
python scripts\verify_local_install.py --root $env:USERPROFILE\.codex
```

安装器只交换 manifest 声明的 17 个 Skill、`tools\slk\bin`、共享文档/Schema 和安装 manifest；旧集合保存到 `tools\slk\backups`。任一暂存、哈希或安装后核验失败都会恢复完整旧集合，并在 `.codex\.tmp` 写失败报告。安装器不会运行 `slk-state configure`，数据库迁移仍需对明确选择的数据根单独执行。

LE BI 发布验收时先确认本机没有 1430 listener，再从已安装路径冷启动；进程应保持运行、无 localhost:1430 连接，WebView2 新证据不得出现 `ERR_CONNECTION_REFUSED`，并应能从现有全域只读数据根显示项目/Run。正常 UI 使用单实例 mutex；`--help`、`-h`、`--version`、`-V` 仅作无窗口探测并在创建 Tauri 窗口前退出。Node、pnpm 与 Vite 只参与构建，不属于新机器运行依赖。

检查版本和入口：

```powershell
python D:\SLK-RUNTIME\bin\slk-transport.pyz --version
D:\SLK-RUNTIME\bin\slk-state.exe --help
D:\SLK-RUNTIME\bin\slk-bi-query.exe --help
D:\SLK-RUNTIME\bin\slk-cargo.exe --help
```

配置一次电脑全域状态数据根：

```powershell
D:\SLK-RUNTIME\bin\slk-state.exe configure --data-root F:\SLK\data
```

升级已有电脑时，在启动只读查询或 LE BI 前，用配置文件里的现有根目录显式触发一次可写迁移；迁移会先在该根目录的 `backups` 下建立并验证备份：

```powershell
$dataRoot = (Get-Content "$env:LOCALAPPDATA\SLK\config.json" | ConvertFrom-Json).data_root
D:\SLK-RUNTIME\bin\slk-state.exe configure --data-root $dataRoot
```

`slk-state` 保存权威状态，`slk-bi-query` 只读查询。BI 仍不写工程事实，但 4.4.4 readiness 必须证明 BI 1.1.1 已打开并显示当前 Run。

## 5. 部署一个项目

把 SLK 4.4.4 `skills\` 下的 17 个目录作为同一已校验包部署到该项目使用的 Skill 根目录，并在项目中调用 `$small-loop-skill`。不要因为电脑已配置 DSH/OCRV/Temporal，就把 SLK 自动应用于其他项目。

首次启动 Run 时：

1. Supervisor 用 `slk-state init-run` 建立 Run；
2. 先用现成 `slk-transport validate --endpoint <path> --envelope <path>` 校验准确原生地址，再登记 Owner 确认的 Codex Supervisor、OCRV Checker、DSH Worker 和指定 OW；全部身份/权限/消费者验证完成后才冻结 Temporal startup，不能把后续 revision 拼入旧输入；
3. DSH Worker 端点记录确定且不超过 64 字符的 `instance_id`、当前 `session_id`、运行根、项目绝对路径和命令；启动前验证 Git worktree/common-dir 存在且可写；
4. OCRV Checker 端点记录命令、运行根和超时；
5. 独立样本由原责任成员实跑七腿：初始 Supervisor→Checker、Checker→Worker→Checker、FAIL Checker→Supervisor→同一 Worker、末项 Checker→Supervisor 和 OW→Supervisor；异常补救不算正常演练；
6. DSH/OCRV 在终态结果前写出匹配 `slk.native-start/v2`，并通过安装后的 capability 声明支持 `inspect-native-activity`；发送者只通过 `slk-state commit-delivery-start` 原子提交正常交接，不能从退出码、legacy marker、wrapper PID 或终态结果倒推启动。Worker→Checker 的 DSH 只密封候选包，由独立 OCRV 宿主启动；TOKEN 已在 Checker 的假启动恢复不得重放 Worker 或再次移动 TOKEN。
7. 必须登记 Overwatcher 并证明其 600 秒前台主动巡查能力；一个 Run 一个独立绑定，同一精确 Session 只有在全部身份/模型/端点/cadence 一致时才可服务多个 Run。不得创建 heartbeat、automation、cron、Windows 计划任务、daemon、后台 Agent 或第二观察者。只有 Supervisor 可请求停止；任何退出先触发 runtime guard 和二次确认。
8. 证明共享 headless Temporal 服务、worker、五函数 adapter 与本 Run 的 `SLK.Start`/`SLK.Run` 都 READY。不得由安装器安装 Docker；服务不可用、OW 审计/退出异常或未解除 guard 时禁止派发下一 CELL。
9. `bind-overwatcher`、`replace-overwatcher` 或 `rotate-overwatcher-credential` 成功后先核对真实结果、中央绑定及密封消费者，再通知成员；一次性的 `overwatcher_write_credential` 保存并立即用 `authenticate-role` 验证，`overwatcher_credential_id` 只是非秘密身份。凭证丢失时只允许 Supervisor 针对精确当前 ACTIVE binding 轮换，不替换 Session/turn/binding、不伪造 continuity violation 或直接编辑状态库。

端点和信封字段、命令及重试语义以 [`../transport/SLK-TRANSPORT.md`](../transport/SLK-TRANSPORT.md) 为准。不要按对话标题猜测目标，也不要把数据库记录当作消息已经投递。

## 6. 新电脑验收清单

以下各项都成立，才把新电脑标记为可运行 SLK 4.4.4：

- DSH 版本命令成功，真实 headless 请求返回预期结果；
- 两个不同 `instance-id` 的 DSH Worker 不共用 session；
- OCRV 版本命令和 Adapter 测试通过；
- 两次并行 OCRV D1 使用不同 review/session identity；
- 完整包中的五个本地工件、17 个 Skill、文档、Schema、VERSION 与 manifest 哈希一致，`slk-transport.pyz`、`slk-state.exe`、`slk-bi-query.exe`、`slk-cargo.exe` 和只读 BI 可执行；
- 状态数据根位于产品仓库之外；
- 使用隔离可丢弃仓库完成上述七腿，包括真实 FAIL→指引→同 Worker 返工→Checker PASS 和原件读取；
- 演练后产品项目没有文件变化；
- 凭据未出现在端点、信封、日志、状态库或证据中。

传输演练及其证据要求见 [`../transport/SLK-TRANSPORT-LIVE-ACCEPTANCE.md`](../transport/SLK-TRANSPORT-LIVE-ACCEPTANCE.md)。

## 更新与故障边界

4.4.4 是4.4.3的准备纠错补丁；安装版本、manifest与hash标识新包，旧Run/样本、OW绑定、startup和历史保留原方法身份，不自动迁移或重标。新Run使用4.4.4；4.4.3/4.4.4 readiness核验BI1.1.1，既有4.4.2回执保持兼容。原生未公开的 `context_capacity/task_context_estimate` 可省略或填null并保留 `TASK_CONTEXT_UNKNOWN` advisory，不填猜测数字，也不因此删除真实身份、能力、工具和通讯核验。

- 已配置的电脑先验证再复用，不为每个项目重复安装 DSH、OCRV 或机器级工具。
- DSH/OCRV 包版本、模型、Provider、Adapter 或 SLK 传输协议发生变化时，重新执行对应验收。
- DSH 外层退出码不能单独证明 Worker 完成；应检查闭合 Worker 结果和命令证据。
- OCRV 返回 `INCOMPLETE` 时保留事实并修复运行环境，不把它改写成 PASS。
- 传输未出现原生启动证据时，发送者仍持有原 TOKEN；空闲目标恢复沿用同一消息身份一次，活跃 Supervisor 的当前 D1 FAIL 只用绑定准确 turn 的新消息，其他变化交回 Supervisor。
- 当前 SLK 4.4.4 源码发布不把 DSH/OCRV 的机器启动配置混入 17 个 Skill，也不读写 LCaS 产品候选。DSH/OCRV activity integration 与 Checker recovery companion 随包保存在 `integrations`，只能对明确指定且已含已验收 runtime 的 root 执行各自独立安装脚本；脚本只备份并替换已声明文件、不安装依赖，失败自动恢复。新电脑应从受信配置包或已验收电脑复制其他配置文件，排除 `node_modules`、临时目录、运行状态、日志和凭据后，再执行锁定安装与验收。
