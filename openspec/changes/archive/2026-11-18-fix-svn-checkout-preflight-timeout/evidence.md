# 检出预检范围与超时验证

日期：2026-11-11。现场输入：Windows 部署，A 整目录与 B/d、B/e 混合选择，约一分钟后报旧错误 `code_svn_unavailable`。没有远端进程、失败命令或原始响应证据，不能确认历史任务具体在哪条 SVN 命令失败。

## 已确认的代码问题和修复

- 旧外部引用检查从整个分支根递归读取；新检出和更新按固定目标版本的所选项类型，仅递归检查选中的目录。所选文件不扫描父目录；未选范围的声明不影响结果，所选范围的声明仍拒绝。更新中特别覆盖文件变成目录时不能漏检。
- 旧批量元数据检查按普通命令的 60 秒处理。递归清单、外部引用和工作副本整体 status/info 现在使用 300 秒；默认普通查询保持 60 秒。管理操作的 1800 秒总截止、取消和 heartbeat 逻辑未改，也不重试写操作。
- 旧错误丢弃超时/本地 OS 分类。新错误按固定操作名报告超时，并区分程序缺失、执行拒绝、启动失败和本地 I/O；认证、证书、网络分类继续保留。错误和文档不含真实凭据、源码、原始标准错误或命令参数。
- 无新表、服务、配置层、依赖、模型调用或 Runtime 发布。字节、文件数与磁盘限制继续生效。

## 本机验证

- 后端 `test_code_svn_execution.py`、`test_code_svn_access.py`、`test_code_checkout.py`、`test_code_operations_store.py`：63 passed。
- 使用真实受控子进程验证超时、输出 EOF 后 wait 超时、程序缺失、执行拒绝、本地 I/O 分类及子进程停止。一次测试在宿主负载下未进入预期 EOF 分支；将该测试时钟固定以隔离启动耗时后重新通过，没有改变产品的终止逻辑。
- 模拟单命令已经经过 61 秒，递归清单与属性读取成功；普通 info 在相同时间触发明确超时。模拟上层取消后，300 秒批量命令依然停止并等待退出。这是虚拟时间边界测试，不是现场网络或真实五分钟性能测试。
- 容器内真实 SVN 测试：`test_code_checkout_svn_integration` 和 `test_code_svn_history` 共 20 passed、4 skipped。隔离仓库验证 A 全选与 B/d、B/e 文件/目录多选；只扫描所选目录的属性；未选祖先的 externals 不被跟随；选中属性拒绝；更新与稀疏范围、目标类型变化、固定版本和历史查询正常。跳过的 4 项需要独立认证/网络 fixture，本次未配置，不算现场认证验收。
- SVN 测试使用现有 knowledge-sync 镜像，当前 backend 只读挂载，容器 `--network none --read-only`、UID/GID 10003:10010、1 GiB 临时内存盘；无生产连接、凭据或数据库写入。
- 连续修复中前端 `code-checkout-panel.test.tsx`：10 passed；中文错误提示、旧错误回退已覆盖。此后前端文件未改，ESLint 和 `tsc -b` 通过。
- 三个生产 Python 文件 Mypy、变更 Python 文件 Ruff、OpenSpec strict validate 与 `git diff --check` 通过。

## 目标部署

本次代码尚未提交、推送或部署。按层浏览修复已部署的环境，更新本次源代码后执行：

```sh
docker compose build knowledge-sync admin-web
docker compose up -d --no-deps knowledge-sync admin-web
```

应用镜像前等待现有 SVN 检出/更新结束。无需数据库迁移或 Agent 重新发布。页面刷新后发起新的检出验证，历史失败错误不改写；若仍失败，以新错误定位具体步骤。Windows 真实仓库、网络、挂载磁盘和最终完成状态尚待现场确认，本机测试不等同于已恢复。
