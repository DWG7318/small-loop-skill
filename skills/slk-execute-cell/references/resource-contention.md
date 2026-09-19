# SLK 独占资源恢复

> 本参考只在 Small Loop Skill（SLK）当前节点因资源占用、锁或排他使用无法继续命令时读取，不单独启动流程。

资源占用是环境事实，不自动成为产品缺陷、D0/D1/D2 FAIL 或返工。当前角色保留 `SLK TOKEN`，用 `slk-state write` 追加 `RESOURCE_CONTENDED`；不推进 `SLK TOKEN`，也不计入 D1 返工。

建议按当前事实逐级处理：

1. 识别资源、锁范围、占用进程和它是否仍存活；无法确认时记录 unknown，不猜测 stale。
2. 优先隔离可分离的生成物。Cargo 建议通过 `slk-cargo` 为当前 Run 复用独立 `CARGO_TARGET_DIR`，命令与清理参数查看 `slk-cargo --help`；数据库、端口、临时目录和 GPU 可使用本次工作自己的实例、分配或目录，只要不改变产品契约。
3. 确实共享且仍被正常使用时，只对冲突命令做有界等待和重试；同一 CELL 内不依赖该资源的工作可以继续。
4. 只有占用者已被证明不存在时，才清理对应 stale lock；不要删除来源不明的锁，也不要结束无关进程。
5. 恢复后追加 `RESOURCE_RECOVERED`，从同一 CELL、同一检查节点继续。仍无法恢复时，把资源、占用者、尝试和剩余影响按既有 Checker/Supervisor 路径报告，用现有角色调整资源或顺序。

这个处理不增加角色、CELL、检查层或常驻锁管理器，也不允许绕过当前 CELL 进入下一 CELL。
