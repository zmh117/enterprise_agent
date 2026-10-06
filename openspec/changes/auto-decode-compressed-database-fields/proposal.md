## Why

数据库查询中的 `C_OPTEXT` 在 MySQL 使用 `MEDIUMBLOB`、SQL Server 使用 `VARCHAR(MAX)`、Oracle 使用 `BLOB`；字段可能承载 zlib 压缩字节或其字符串包装，现有 `query_database` 无法自动还原可读内容。需要在受治理查询的结果处理阶段完成有界、可追溯的自动解码，避免把长压缩值交给模型搬运或为各资源增加发布配置。

## What Changes

- 在 `tool-mcp` 的数据库取值层自动识别原始标准 zlib 字节、严格 Base64 包装和严格 Hex 包装；按实际值类型和内容判断，不硬编码 `C_OPTEXT`、表名或列名。
- 共用 Python 标准库 `zlib` 解码逻辑，覆盖 MySQL `MEDIUMBLOB`、SQL Server `VARCHAR(MAX)` 和 Oracle `BLOB`。Oracle BLOB 在连接有效期间按预算读取，不把 LOB 对象的字符串表示作为字段正文。
- 第一版仅接受完整、校验通过的单个标准 zlib 流和严格 UTF-8 明文；不猜字符集、不递归解压、不把解压字符串自动转换成 JSON 对象。
- 普通字符串、NULL 和非候选普通值保持既有语义。已取得完整原值的候选解码失败、依赖预置字典、明文不是 UTF-8 或展开超限时，保留原始值的有界表示并提供安全状态。
- **BREAKING（未解码二进制的结果表示）**：二进制回退从不可靠的 `str(bytes)` / `str(LOB)` 改为明确、可逆的 Base64 对象；依赖旧字符串表示的结果消费端需要适配，不能把该对象当作解码明文。普通字符串和工具输入合同不变。
- 同时约束输入处理、解压展开、查询墙钟时间和最终响应容量；不能完整取得或返回原值时，按现有容量边界报告查询不完整或安全失败，不返回部分明文冒充成功。
- 给数据库响应增加可选、有界的字段解码元数据，区分查询覆盖、结果文件保存完整性与候选字段解码状态；解压后的正文先脱敏再进入现有只读结果文件链路。
- 保持现有 `query_database` identifier、输入 schema、只读 SQL、实时授权、资源解析、审计和 Job 文件生命周期。无需新增 CLI、独立 zlib Tool、Resource/Agent/Application/RBAC 配置项、数据库迁移或新服务。

## Capabilities

### New Capabilities

无独立新领域；能力增量归入现有 canonical 领域。

### Modified Capabilities

- `builtin-tool-resource`：增加三种数据库的类型适配、自动检测、严格 UTF-8 解码、有界失败回退和安全解码诊断合同。
- `task-file-workspace`：增加数据库解码结果的只读文件传递、元数据校验及查询完整性与解码状态分离合同。

## Impact

- **变更前基线**：三个驱动共用 `_rows_from_cursor`，原先以 `fetchmany(max_rows + 1)` 取行，没有 zlib 识别或 Oracle BLOB 的显式读取处理。
- **Confirmed-current（代码及本地验证）**：已修改上述驱动、`infrastructure/db/executor.py`、`direct_executor.py`、`backend/app/python_runtime/tool_result_bridge.py`，增加标准库字段解码模块并更新安全审计摘要、工具描述和结果消费说明。实现及测试证据见 [evidence](evidence.md)。
- **Confirmed-current**：`backend/app/shared/query_result_contract.py` 固定查询结果容量为 8 MiB；`backend/app/services/tool_mcp.py` 对最终响应脱敏和限界；Runtime 已把数据库正文物化为当前 Job 的只读临时文件。本提案不提高这些容量。
- **真实环境待验收**：用户已确认第一版仅支持严格 UTF-8；实际业务写入端的包装格式及字节保真仍需在现场验收时核对，DDL 不构成解码成功证据。本次未部署、未接入真实业务数据库，不声称现场 PI 已可解码。
- 新增测试必须纳入 `backend/tests/test_suite_tiers.toml`。本地合成数据、驱动替身和三种真实数据库验收分别记录；真实验收只使用获准的合成记录，不读取或保存原始业务内容及凭据。
