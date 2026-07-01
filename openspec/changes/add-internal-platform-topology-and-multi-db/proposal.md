## Why

当前 Internal API Platform 只有一个扁平 `datasource="default"` 概念，Loki 单 upstream，DB/Redis 仍是 placeholder。真实排障要面对多环境（三九、mmk）、每个环境多个基地（观澜、华南…）、基地内多个车间（GL001、GL002），且数据库要兼容 MySQL / SQL Server / Oracle。没有拓扑模型和多方言安全查询，工具层无法把「三九观澜 GL001 订单卡住」这类问题落到正确的数据源，也无法保证只读、只查本车间、不跨基地。本 change 把 `local_internal_api_platform` 升级为正式 platform module，引入拓扑寻址与多方言只读数据库网关。

## What Changes

- 将 `local_internal_api_platform` 升级/重命名为正式的 `internal_api_platform` 模块（保留兼容启动入口），按 `domain / application / infrastructure / api` 分层。
- 引入拓扑领域模型：`Environment`（三九/mmk）→ `Base`（业务 code，如 `guanlan` 观澜）→ `Workshop`（车间 code，如 `GL001`）。
- **资源归属定级**：数据库/Redis/Loki 均为 **基地级** 资源；数据库引擎为 **基地级**（一个基地一种引擎）；车间为逻辑分区，仅通过命名区分（DB 表前缀 `GL001_EBR_`、Redis key 前缀、Loki 标签）。
- 工具请求契约从扁平 `datasource` 升级为结构化寻址：`environment` + `base` + `workshop`（Loki/Redis 可只到 base + workshop 标签）。
- 新增多方言只读数据库网关：支持 MySQL / SQL Server / Oracle，统一只读校验、按方言处理分页与标识符、强制车间表前缀。
- 新增基地级 Redis / Loki 网关：按基地路由 upstream，按车间 code 约束 key 前缀 / 日志标签。
- 新增平台侧访问控制（第二层）：校验用户可访问的 environment / base / workshop 范围，与 Agent 侧 permission 形成纵深防御。
- 配置来源：先 YAML + seed 描述拓扑与连接（密钥用引用而非明文），预留后续迁移到 DB registry。
- 更新 Docker Compose / 文档，提供三九（观澜 1 基地 + GL001/GL002）与 mmk（无车间分层的 degenerate 拓扑）的样例配置与验证路径。

非目标：

- 不引入任何写操作（仍严格只读）。
- 不实现 Web 配置台 UI。
- 不实现拓扑配置的 DB 持久化后台（本期 YAML + seed，DB 仅预留接口）。
- 不改动 Claude 运行时、RabbitMQ、DingTalk 主流程（仅扩展工具契约）。
- 不接入除 MySQL / SQL Server / Oracle 外的其它数据库引擎。

## Capabilities

### New Capabilities

- `internal-platform-topology`: 环境/基地/车间拓扑领域模型、YAML+seed 配置加载、结构化寻址解析（把 environment/base/workshop 解析为具体资源绑定），支持三九多车间与 mmk degenerate 拓扑。
- `multi-dialect-database-gateway`: MySQL / SQL Server / Oracle 只读数据库网关，统一只读校验、方言分页与标识符处理、强制车间表前缀与跨基地/跨车间隔离。
- `base-scoped-redis-loki`: 基地级 Redis 与 Loki 网关，按基地路由 upstream，按车间 code 约束 Redis key 前缀与 Loki 日志标签。
- `platform-access-control`: 平台侧第二层访问控制，按用户可访问的 environment/base/workshop 范围校验工具请求并审计。

### Modified Capabilities

- None（现有 platform 结构 spec 尚未归档到 `openspec/specs/`；本次以新增 capability 承载，模块 rename 在 design 中说明）。

## Impact

- 代码：`backend/app/modules/local_internal_api_platform/` 升级为 `internal_api_platform`（domain/application/infrastructure/api 分层）；保留 `backend/app/local_internal_api_platform.py` 兼容入口或迁移启动目标。
- 工具契约：`internal_tools`（`InternalApiClient`、`HttpInternalApiClient`、`ReadOnlyToolService`、`mcp_tool_registry`、Claude tool schema）需支持结构化寻址字段。
- 配置：新增拓扑 YAML（三九/mmk）、连接密钥引用、Compose 环境变量；`datasource_registry` 表语义演进（预留）。
- 依赖：新增数据库驱动（MySQL、SQL Server、Oracle 对应 Python driver）。
- 测试：拓扑解析、多方言 SQL 安全（表前缀提取、只读、分页、跨车间拒绝）、基地级 Redis/Loki 路由、平台访问控制。
- 文档：README 平台章节、Compose 样例、排障寻址说明。
