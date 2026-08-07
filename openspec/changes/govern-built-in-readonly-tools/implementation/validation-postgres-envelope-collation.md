# PostgreSQL Agent Built-in Tool Envelope 排序回归

执行日期：2026-08-07（Asia/Shanghai）

## 现象与根因

Agent r45 草稿已通过普通校验并选择 8 个 HEALTHY Built-in Tool Release，但发布返回
`agent_builtin_tool_envelope_hash_mismatch`。

现场 PostgreSQL 自动回滚诊断证明 8 条事实的 Release、Handler、Implementation
Digest、Public Schema Hash、Model Description 和 Envelope Hash 全部精确一致。差异仅
来自排序：

```text
Python:     diagnose_loki_label_values, diagnose_loki_labels
PostgreSQL: diagnose_loki_labels, diagnose_loki_label_values
```

原实现直接比较 Python 排序的快照列表与依赖数据库 collation 的 `ORDER BY` 结果，因而
在 PostgreSQL 上产生假完整性失败；SQLite 测试使用的排序恰好与 Python 一致，没有暴露
该问题。

## 修复

`AgentBuiltinToolEnvelopeService` 现在对期望 Envelope 和数据库事实都使用 Python
Identifier 排序进行规范化，再执行完整字典比较。该修复只消除跨数据库排序差异，不
放宽任何字段、版本、digest、schema 或 hash 校验。

新增回归：

```text
backend/tests/test_agent_publication_runtime.py::test_agent_publication_envelope_integrity_is_independent_of_fact_order
```

该用例先把事实读取顺序反转；修复前稳定失败，修复后通过。既有篡改
`model_description` 必须失败的完整性用例继续通过。

## 验证

- 定向回归：`2 passed`；
- 后端全量：`947 passed, 23 skipped, 18 subtests passed`；
- Ruff、`git diff --check`、OpenSpec strict validation：通过；
- API 及使用同一 Agent Worker 镜像的相关服务已重建且健康；
- 重建后的 API 容器对真实 PostgreSQL 执行自动回滚冻结验收：
  `expected_count=8`、`actual_count=8`、`exact=True`。

现场验收事务已主动回滚，没有修改 r44 或 r45。由于可控浏览器没有当前用户的登录会话，
未绕过 RBAC 代替用户执行最终发布；当前 Chrome 刷新后可继续发布已验证的 r45。
