# SLK 4.0 Windows 运行环境配置指引

本指引用于在一台新 Windows 电脑上建立可运行 SLK 4.0 的机器环境。它不改变 SLK 方法，也不替代项目内的 14 个 Skill。

## 先分清三个层级

1. **电脑级环境，只配置一次**：DSH、OCRV、`slk-transport`、`slk-state`、`slk-bi-query`，以及它们的凭据和数据目录。多个项目复用这一层。
2. **项目级部署**：把 SLK 4.0 的 14 个 Skill 放入该项目使用的 Skill 根目录。SLK 不因此变成电脑全域工程方法。
3. **Run 级绑定**：每个 Run 重新登记 Supervisor、OCRV Checker、DSH Worker 的精确身份、会话和端点，并完成通讯测试。

仅完成第 2 层不能启动跨 Agent SLK。

## 已验收基线

SLK 4.1.1 验收时使用：

- Windows、PowerShell 7、Git、Python 3.10 或更高版本、Node.js/npm 与 Rust/Cargo；
- `@deepseek-ai/dsh@0.1.5-rc.2`；
- `@alibaba-group/open-code-review@1.12.7`；
- DSH：`deepseek-official / deepseek-flash`；
- OCRV：`dashscope-tokenplan / qwen3.8-max / medium`；
- SLK 4.1.1 源码，用于构建无第三方依赖的 `slk-transport.pyz` 和状态 CLI。

升级这些版本应重新验证，不把“能够启动”直接当作与上述基线兼容。

## 推荐目录

盘符可以调整，但同一台电脑应保持稳定并使用绝对路径。例如：

```text
D:\SLK                 SLK 4.0 源码
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
slk\SLK-D1-REVIEW.md
tests\...
```

锁定依赖应包含：

```json
{"dependencies":{"@alibaba-group/open-code-review":"1.12.7"}}
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

OCRV 是 D1 Checker，不是附加证据工具。`PASS`、`FAIL`、`INCOMPLETE` 分别使用既定闭合结果；API、模型、工具或候选覆盖异常应保持 `INCOMPLETE`，不改由 Worker 或 Supervisor代替给出 D1 PASS。

## 4. 构建 SLK 传输和状态工具

从受信的 SLK 4.1.1 源码构建机器级工具：

```powershell
Set-Location D:\SLK
New-Item -ItemType Directory -Force D:\SLK-RUNTIME\bin | Out-Null
python scripts\build_transport_zipapp.py --output D:\SLK-RUNTIME\bin\slk-transport.pyz
$env:CARGO_TARGET_DIR = 'F:\SLK\build'
cargo build --release -p slk-state-cli -p slk-bi-query
Copy-Item F:\SLK\build\release\slk-state.exe D:\SLK-RUNTIME\bin\
Copy-Item F:\SLK\build\release\slk-bi-query.exe D:\SLK-RUNTIME\bin\
```

检查版本和入口：

```powershell
python D:\SLK-RUNTIME\bin\slk-transport.pyz --version
D:\SLK-RUNTIME\bin\slk-state.exe --help
D:\SLK-RUNTIME\bin\slk-bi-query.exe --help
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

`slk-state` 保存权威状态，`slk-bi-query` 只读查询。桌面 BI 是可选展示组件，不是启动 SLK Run 的前提。

## 5. 部署一个项目

把 SLK 4.1.1 `skills\` 下的 14 个目录复制到该项目所使用的 Skill 根目录，并在项目中调用 `$small-loop-skill`。不要因为电脑已配置 DSH/OCRV，就把 SLK 自动应用于其他项目。

首次启动 Run 时：

1. Supervisor 用 `slk-state init-run` 建立 Run；
2. 登记精确的 Codex Supervisor、OCRV Checker 和 DSH Worker 角色实例；
3. DSH Worker 端点记录唯一 `instance_id`、当前 `session_id`、运行根、项目绝对路径和命令；
4. OCRV Checker 端点记录命令、运行根和超时；
5. 完成 Supervisor → Checker、Checker → Worker 的真实双向通讯测试；
6. 只有原生启动证据成立后，才通过 `slk-state handoff` 推进 SLK TOKEN。

端点和信封字段、命令及重试语义以 [`../transport/SLK-TRANSPORT.md`](../transport/SLK-TRANSPORT.md) 为准。不要按对话标题猜测目标，也不要把数据库记录当作消息已经投递。

## 6. 新电脑验收清单

以下各项都成立，才把新电脑标记为可运行 SLK 4.0：

- DSH 版本命令成功，真实 headless 请求返回预期结果；
- 两个不同 `instance-id` 的 DSH Worker 不共用 session；
- OCRV 版本命令和 Adapter 测试通过；
- 两次并行 OCRV D1 使用不同 review/session identity；
- `slk-transport.pyz`、`slk-state.exe`、`slk-bi-query.exe` 可执行；
- 状态数据根位于产品仓库之外；
- 使用一次可丢弃仓库完成四段传输演练，精确验证 `Supervisor → Checker → Worker → Checker → Supervisor`；
- 演练后产品项目没有文件变化；
- 凭据未出现在端点、信封、日志、状态库或证据中。

传输演练及其证据要求见 [`../transport/SLK-TRANSPORT-LIVE-ACCEPTANCE.md`](../transport/SLK-TRANSPORT-LIVE-ACCEPTANCE.md)。

## 更新与故障边界

- 已配置的电脑先验证再复用，不为每个项目重复安装 DSH、OCRV 或机器级工具。
- DSH/OCRV 包版本、模型、Provider、Adapter 或 SLK 传输协议发生变化时，重新执行对应验收。
- DSH 外层退出码不能单独证明 Worker 完成；应检查闭合 Worker 结果和命令证据。
- OCRV 返回 `INCOMPLETE` 时保留事实并修复运行环境，不把它改写成 PASS。
- 传输未出现原生启动证据时，发送者仍持有原 TOKEN；恢复沿用同一消息身份，不额外创建确认回合。
- 当前 SLK 4.1.1 源码发布不把 DSH/OCRV 的机器启动配置混入 14 个 Skill。新电脑应从受信的内部配置包或已验收电脑复制上述配置文件，排除 `node_modules`、临时目录、运行状态、日志和任何凭据后，再执行本指引的锁定安装与验收。
