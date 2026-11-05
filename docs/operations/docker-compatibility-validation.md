# Docker 兼容修改的本地验证记录

日期：2026-11-05。代码基线：`0321ba6c` 上的本次兼容修改工作区。
按用户确定的交付范围，本次交付代码，Windows WSL2 和真实 x86 Linux VM 整套验收稍后执行。

## 已验证

| 检查 | 实际环境与范围 | 结果 |
| --- | --- | --- |
| Compose/初始化/权限回归 | 本机 Python；合成配置、临时测试材料，不读取真实 `.env` 或凭据 | 相关测试通过；两个需显式启用的隔离 PostgreSQL 用例跳过 |
| 路径合同 | Linux 路径、含空格和中文路径、Windows 盘符形式、WSL daemon 路径的合成配置 | 固定容器目标与 daemon 源路径正确区分；缺失/重复/可写/错误项目挂载被拒绝 |
| 控制器真实容器 | Docker Desktop Engine `linux/arm64`；临时独立项目、固定 `/deployment` 和三份合成文件 | 容器内 `knowledge_deployment_check` 通过；嵌套 Compose 成功启动只读挂载探针 |
| amd64 控制器探针 | 同一 ARM Docker Desktop 中模拟运行 `linux/amd64` 的 Python + Docker CLI 镜像 | 相同路径检查和嵌套 Compose 文件/Secret 挂载通过；不是实体 x86 VM 验收 |
| Linux ACL | 真实 Docker Linux 命名卷、`setfacl`、非 root 且移除 capabilities 的临时容器 | 指定 UID 可读取并复制为自身所有的 `0400` 文件；无关 UID 被拒绝 |
| ACL 重复初始化 | 先加入一个不在合同内的旧 UID，再运行 `--docker-acl` | 旧 UID 权限被移除，固定消费者仍可读取；不依赖 world-readable |
| 质量检查 | Ruff、相关后端 Mypy、OpenSpec、diff 空白检查 | 通过 |

路径探针只带合成文件，未访问现有知识内容、模型凭据或业务数据；ACL 探针材料只用于临时
测试。临时容器、网络、卷和测试镜像在结束后清理。未重建或重启当前业务项目。

相关回归入口：

```sh
.venv/bin/pytest -q \
  backend/tests/test_windows_container_compatibility.py \
  backend/tests/test_knowledge_compose.py \
  backend/tests/test_knowledge_operations.py \
  backend/tests/test_knowledge_online_compose.py \
  backend/tests/test_knowledge_sync_compose.py \
  backend/tests/test_identity_aware_ones_mcp_architecture.py \
  backend/tests/test_compose_migrator_gate.py \
  backend/tests/test_document_processing_compose.py \
  backend/tests/test_agent_runtime_compose_security.py \
  backend/tests/test_initial_admin_bootstrap.py
```

## 未验证

- Windows 10/11 WSL2 的整套首次启动、网页构建/启停、完整 Job 与文件处理。
- 真实 x86-64 Linux VM 的整套部署、性能和长时间同步/检索并发。
- 真实 ONES、钉钉、模型 Provider，以及现场用户权限与实际业务数据。

后续在每个目标环境分别按[部署和验收手册](docker-deployment.md)运行 `check`、`accept`，
再完成业务验收表；保留安全状态和错误码，不把本记录的局部通过填作目标机通过。
