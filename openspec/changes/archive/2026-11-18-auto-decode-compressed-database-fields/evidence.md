# 实施与验证证据

日期：2026-10-06。范围：`auto-decode-compressed-database-fields` 的本地实现与合成数据验证。未提交、推送、部署、同步 canonical 或归档。

## 已实现

- 共用标准库解码模块识别原始字节、严格标准 Base64/Hex，仅接受完整单个 zlib 流及严格 UTF-8。候选失败保留完整原值，未解码二进制采用明确 Base64 对象。
- MySQL SSCursor、SQL Server 字符串/字节、Oracle 固定 BLOB 类型接入；Oracle 连接内 size 检查和 64 KiB 分块读取。未知 read 对象不被读取，BFILE/CLOB/NCLOB 安全拒绝。敏感列在适配前遮蔽。
- 累计输入、累计尝试展开、逐块期限检查与实际 JSON 行/诊断容量限界。完整行及诊断原子接纳；超限后停止读取，MySQL 不排空结果尾部。处理超时返回 `database_query_timeout`。
- Runtime 验证可选诊断版本、状态、格式、引用、唯一性、大小、二进制表示和计数；失败不发布文件。内联摘要仅保留固定事实，正文及逐字段诊断进入原只读 Job 文件链路。
- 普通 Tool timeline 仅投影安全计数、策略版本及完整性；既有受限 MCP 业务审计保留原合同。
- 代码拥有的工具描述和结果消费说明已更新。工具集合及所有输入 schema hash 与 HEAD 一致，没有新增配置、授权、服务或迁移。

## 本地验证

| 检查 | 实际结果 |
| --- | --- |
| `.venv/bin/pytest -q backend/tests/test_database_field_decoding.py backend/tests/test_database_driver_boundaries.py` | 122 passed，1.15 秒 |
| 专项及既有 MCP/查询文件/摘要/授权/审计/外部 I/O 边界/分类回归 | 251 passed，25.14 秒；此轮之后增加的 5 个专项用例已在上行验证 |
| `.venv/bin/mypy` 受影响的 9 个源文件 | Success: no issues found |
| `.venv/bin/ruff check` 受影响源文件及专项测试 | 通过 |
| `.venv/bin/ruff format --check` 受影响 Python 文件 | 通过 |
| `.venv/bin/python scripts/check_markdown_links.py` | MARKDOWN_LINK_CHECK_SUCCEEDED |
| `docker compose config --quiet` | 通过；仅为配置检查，不证明构建或部署 |
| `OPENSPEC_TELEMETRY=0 openspec validate auto-decode-compressed-database-fields --strict` | 通过 |
| `OPENSPEC_TELEMETRY=0 openspec validate --specs --strict` | 10 passed，0 failed；不作为真实运行证据 |
| `git diff --check` 及新增文件独立空白检查 | 通过 |
| 对比 HEAD 中工具目录和所有输入 schema hash | 完全一致 |

回归命令的完整用例集合：

```text
.venv/bin/pytest -q
  backend/tests/test_database_field_decoding.py
  backend/tests/test_database_driver_boundaries.py
  backend/tests/test_mcp_tool_runtime.py
  backend/tests/test_tool_query_results.py
  backend/tests/test_tool_response_summary.py
  backend/tests/test_tool_mcp.py
  backend/tests/test_mcp_audit_coordinator.py
  backend/tests/test_agent_run_audit_repository.py
  backend/tests/test_python_runtime_run_audit.py
  backend/tests/test_external_io_transaction_boundaries.py
  backend/tests/test_test_suite_governance.py
```

测试覆盖合成中文/空文本、三种包装及字节类型、普通值、字段别名、损坏/截断/尾随/多流、预置字典、非 UTF-8、非规范 Base64、gzip/raw DEFLATE、单次解码、累计预算、失败扣款、边界探测、期限、行与诊断容量、BLOB 生命周期和错误、敏感内容遮蔽、非法协议、旧响应、只读/跨 Job 拒绝、失败文件清理及安全审计摘要。新增测试已归入 `unit` tier。

## 真实环境验收待办

尚未确认三种测试资源、只读账号对应的授权入口，以及独立获准的合成记录准备流程；实际 PI 写入/读取代码的包装和编码规则也未提供。本次只使用合成内容和驱动替身，不读取、打印或保存凭据或真实字段正文。

| 引擎 | 待验收内容 | 当前状态 |
| --- | --- | --- |
| MySQL | MEDIUMBLOB 原始及 ASCII 包装，普通二进制、中文、超限与真实流式连接清理；新 Job 文件链路 | 未验收 |
| SQL Server | VARCHAR(MAX) Chinese_PRC_CS_AS 的 Base64/Hex、字符串保真、中文及容量；现场格式匹配 | 未验收 |
| Oracle | 11.2.0.4 / Instant Client 19c Thick 的 BLOB 读取、期限、连接生命周期和新 Job 文件链路 | 未验收 |

后续验收必须分别记录实际引擎/客户端版本、Job/调用关联、安全状态与计数、文件校验事实；不记录压缩值、明文或凭据。只读查询不负责准备或写入合成记录。缺少某引擎环境时对应任务保持未完成，不用另一个版本、Mock 或 DDL 替代。

当前任务进度为 21/27：第 1–4 组及 6.1 完成；5.1–5.5 真实验收待条件确认，6.2 待用户请求同步/归档。未提前改写 canonical，也未补勾真实验收任务。
