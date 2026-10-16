# 通用 BI：直接使用成品

BI 是独立工具，不要求换成另一系列 SLK。使用已安装的 `slk-bi-desktop.exe`（BI 1.1.4 起）；没有时取官方 `DWG7318/slk-bi` 对应发布的 Windows 预编译包。启动原 exe，不编译，不加后台组件。此能力同样适用于仍使用 3.0.9 的 Supervisor。

由创建 Supervisor 在自身原生对话环境中执行一次登记：

```text
slk-bi.ps1 --bi-register "<工作簿绝对路径>" --project-id "<准确项目ID>" --project-name "<项目名>"
slk-bi.ps1 --bi-read "<RUN-ID>"
```

BI 读取原工作簿的 Run 定义、唯一当前摘要、成员与计划；不读取 Agent 私有对话或把全本历史送给 WebBI。新工作簿保留创建 Supervisor 的原生任务 ID；更换成员不改创建者。CLI 从当前 Codex 宿主注入的线程/会话 ID 核对调用者，不接收一个可随意填写的 `--supervisor` 参数。不要伪造环境变量冒充其他成员。其它平台身份适配尚未提供时，保留只读来源，不借同名身份取得归档权限。

当前摘要写真实状态、当前责任、更新时间和 D1 通过数/有效 CELL 总数；不以 TOKEN 归属冒充在线。计划可用 `CELL | 目标 | 状态 | 次数` 表（状态为 planned、working、d1_passed、d1_failed、split、exempt 或 unknown）；该表只是原计划的形式，不再复制第二份计划。成员表可增加 Agent、模型、推理列。拆分初始数与净增加数只有明确记录时才显示，不从总数差推测。

完成本方法收尾、根记录的当前状态为 `CLOSED`（废止为 `ABANDONED`）后，由创建 Supervisor 执行：

```text
slk-bi.ps1 --bi-archive "<RUN-ID>"
```

BI 保存只读来源的归档快照和创建者身份，保留历史；源仍未收尾会明确拒绝，不代写 D2 PASS 或 CLOSED。更换归属需 Owner 另行决定并保留原创建事实，不能静默重登记。原方法归档、BI 已读取、WebBI 已上传是不同事实，分别核验。

桌面按原刷新周期读取和上传，WebBI 不直连工作簿。来源缺字段显示未提供，来源格式不明确时报错；BI 不从自由文字生成正式消息类型或 ntfy 通知。读取失败先核对登记路径/当前摘要，交回 Supervisor 现场处置，不加工程开工门槛。
