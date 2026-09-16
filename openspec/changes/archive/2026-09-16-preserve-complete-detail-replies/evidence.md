# 本地验证记录

日期：2026-09-16。

## 已确认实现

- `backend/app/python_runtime/claude_client.py` 在统一系统 Prompt 注入通用明细规则；无 Skill、ONES 工具和钉钉工具上下文均适用。
- `backend/app/shared/tool_contract.py` 的共享 Prompt template version 从 v6 升为 v7；保留历史版本审计测试和漂移拒绝行为。
- 未修改 Skill、ONES 查询/分页、MCP Schema、Runtime 协议、数据库、权限及 Delivery 分片算法。

## 自动验证

```sh
env -u GOVERNED_RESOURCE_POSTGRES_DSN .venv/bin/pytest backend/tests/test_python_agent_runtime.py backend/tests/test_runtime_http_client.py backend/tests/test_mcp_tool_runtime.py backend/tests/test_delivery_outbox_chunk_idempotency.py backend/tests/test_dingtalk_delivery.py -q --tb=short
```

结果：153 passed。

```sh
env -u GOVERNED_RESOURCE_POSTGRES_DSN .venv/bin/pytest backend/tests/test_agent_run_audit_repository.py backend/tests/test_file_version_delivery.py -q --tb=short
```

结果：31 passed。两组共 184 项通过。

新增回归包括 6 种无 Skill/有 Skill、无工具/ONES/钉钉上下文组合，以及 3 种分片长度下的 20 条唯一编号、完整长标题清单；原文中的合法省略号保留，重组内容与输入完全一致。

针对改动 Python 文件的 Ruff 检查和格式检查、`git diff --check`、`openspec validate preserve-complete-detail-replies --strict`、`docker compose config --quiet` 均通过。

## 验证边界与后续验收

这是代码化 Prompt 行为约束，不是程序级记录完整性校验。自动测试证明规则已注入以及合成文本分片无损，不能证明真实模型一定列全记录。没有调用真实 ONES、钉钉或模型，没有复现 Windows 环境的特定 Job，也没有部署、重新发布 Agent/应用或提交代码。

部署时 Worker、Runtime 及相关控制面组件需使用一致的共享 Prompt 版本，不回写历史 Job。后续以新 Job 请求完整清单，核对工具实际获取数、筛选后的稳定 ID 集合、模型实际展示集合与收到的全部消息分片；不能只凭 `truncated=false` 或测试通过判定真实验收完成。用户明确要求摘要或前 N 条的请求仍按其范围回答。
