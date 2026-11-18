# 环境隔离实现与验证（2026-11-10）

## 当前实现

- 代码目录要求 `source_kind=code` 和精确环境编码，先核对当前用户明确的环境声明，再筛选已发布、当前授权且关联该启用环境的知识库。普通目录默认 ONES。
- 搜索、全文、SVN 工具和保存均要求环境。搜索凭证升级为 `code-search-receipt/v2-environment`；分析上下文、Runtime 读占用及历史结果读取继续逐次核对环境关联与启用状态。
- 迁移 162 为 `code_analysis`、`code_answer`、`code_qa_record` 增加环境外键和索引。触发器拒绝新无环境记录及环境改绑；旧 NULL 行不回填、不参与检索。迁移采用显式语句边界以保留触发器体中的分号，旧迁移文本不变。
- 答案身份包含稳定环境 ID，PG 在版本选择前按环境过滤，向量候选与全文再次核对。环境 A 的纠错不会更新 B 的答案。
- 私有问答历史记录环境，只接受同环境实际读取或保存的答案引用。单个 Job 仍只承载一个明确环境，不创建每环境数据库、向量集合或代码检出。
- 提示词版本更新为 v15，代码问答 Skill 和运维说明已同步；两份相关 canonical spec 已同步新增要求。

## 已执行验证

- `pytest backend/tests/test_code*.py --ignore=backend/tests/test_code_postgres_integration.py backend/tests/test_knowledge_directory.py backend/tests/test_knowledge_mcp_server.py backend/tests/test_knowledge_mcp_contract.py backend/tests/test_knowledge_database_policy.py`：280 passed，39 skipped。跳过用例需要额外 SVN、宿主环境或显式集成配置。
- 最后补充环境名称、未知环境及列表歧义识别后，`test_code_on_demand_bridge.py`、`test_code_answer_search.py`、`test_code_result_recorder.py`：53 passed。
- 独立临时 PostgreSQL 18 上运行 `test_code_postgres_integration.py`、`test_knowledge_database_policy_postgres.py`：38 passed，1 skipped。跳过项为未提供独立 Qdrant endpoint 的真实向量服务用例。环境身份、插入约束、改绑拒绝、查询最小列权限均实际在 PostgreSQL 执行。
- 补充同环境纠错不改变另一环境后，PostgreSQL 对应隔离测试单独复验：1 passed。
- 既有 ONES `test_knowledge_search.py` 和 Runtime `test_python_agent_runtime.py` 回归通过。迁移目录、升级和字段注释测试已验证；与迁移 161 相关的旧表数量断言、SVN 客户端测试桩已同步当前事实。
- 26 个相关生产 Python 文件通过 mypy；最后变更的环境解析模块单独复验通过。相关代码 Ruff 检查、格式检查与 `git diff --check` 通过。
- 本 change 以及 `builtin-tool-resource`、`platform-operations` canonical spec 均通过 OpenSpec strict validation。

## 验证边界和升级

数据与问答均为合成用例，未读取真实用户消息、凭据或业务源码。本轮没有真实模型、SVN 或真实向量检索验收；现有运行环境未部署。临时 PostgreSQL 容器及其匿名卷已清理。

部署需先执行迁移 162，协调更新 API、knowledge-mcp、knowledge-sync、Runtime，更新 `knowledge_mcp_reader` 对 `knowledge.code_answer.environment_id` 的列读取权限，并重新发布 Agent/Application 工具合同和版本化 Skill 后创建新 Job。旧无环境答案不可直接复用，应在明确环境下重新核验保存。
