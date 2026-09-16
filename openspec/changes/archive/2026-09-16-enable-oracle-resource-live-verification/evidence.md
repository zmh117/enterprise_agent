# 本地验证记录（2026-09-14）

本记录为实现与测试证据，不替代 canonical spec，也不是目标环境真实 Oracle 验收。

## 已验证

- 下列相关回归合计 **94 passed, 1 skipped**：

  ```bash
  .venv/bin/pytest -q backend/tests/test_oracle_resource_verification.py backend/tests/test_database_resource_verifier.py backend/tests/test_governed_tool_resource_lifecycle.py backend/tests/test_governed_tool_resource_api.py backend/tests/test_governed_tool_resource_schema.py backend/tests/test_tool_mcp.py backend/tests/test_provider_contract_registry.py
  ```

  跳过项需要外部 PostgreSQL 测试库；本次没有读取或设置真实连接凭据。
- 新增验证覆盖：API 服务层 → 有界 HTTP 客户端 → tool-mcp 私有 HTTP 入口 → Oracle 探针 → 签名结果 → 当前草稿验证事实入库及发布。
  此链路使用进程内 HTTP 和替身 Oracle driver；不代表真实数据库连接。
- 未签名/错误签名/过期/篡改/重放/跨资源/草稿变化/非管理员/停用身份/超大请求在探针前被拒绝。
  超时、重定向、错误响应签名或关联、超大响应和不完整成功证据不能用于发布；解码后的请求仅含允许的标识字段，不含密码或 Secret reference。
- 保留非本地只读账号限制；Oracle 网络、认证、Service Name/SID、版本、字符集、客户端与只读权限错误返回安全分类。
- 涉及 Python 文件的 Ruff 检查通过；委派模块 Mypy 检查通过。
- `docker compose config --quiet`、严格 OpenSpec 验证及 `git diff --check` 通过。
- `docker compose build api-server tool-mcp` 成功：
  - API 镜像：`sha256:7dbffafaac81d3e8b842b883921c8379f4fc4f209f97ec4d76e2e2cb4dcd4acf`
  - tool-mcp 镜像：`sha256:373fcfcd6d188f7c9ccfd0e8711a327c1b6a8a6ccef293d0f7a291cdaeb5726f`
- 在无网络、只读文件系统、不挂载 Secret 的一次性镜像检查中：API 导入成功且没有 Instant Client；tool-mcp 探针明确返回 `BLOCKED / oracle_client_unavailable / connection=false`。

## 真实验收边界

- 本地构建上下文没有合规的 Instant Client 19c，构建日志明确提示 Oracle remains blocked。这是保留的客户端门槛，不是数据库账号或网络连接失败的证据。
- 未部署或重启运行中的服务，未修改真实资源或数据库配置，无本变更数据库迁移，未连接真实 Oracle。
- 目标环境须按 `backend/vendor/oracle/README.md` 提供匹配架构的 64 位 Linux 19c 客户端，更新 API/tool-mcp 镜像，并对当前草稿重新执行 Web 技术测试。
- 任务 2.3 保持未完成；只有目标环境真实 Oracle 11.2.0.4 检查通过，才能记录真实验收完成。
