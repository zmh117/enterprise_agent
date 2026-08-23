## Why

Internal API Platform 已经从运行架构中退役，但当前 Docker 构建、说明文档和 canonical specs 仍保留旧目录、独立 HTTP 平台、YAML topology、旧功能开关及旧执行者描述。这些残留已经导致镜像构建失败，并使已接受规范同时描述互相冲突的旧平台与标准 `tool-mcp` 链路。

## What Changes

- 删除 Docker 构建对已移除 `backend/config` 目录的依赖，并阻止本地 Python bytecode 进入镜像构建上下文。
- 将 Oracle Instant Client 当前构建说明从已退役服务修正为 `tool-mcp` 镜像和 Compose 服务。
- 将仍宣称旧平台存在的 canonical requirements 同步为当前 `python-agent-runtime -> tool-mcp -> Published Resource Revision` 语义。
- 删除或改写旧 HTTP endpoint、fake client、YAML runtime fallback、activation/Last Known Good、Application Resource Mapping、旧功能开关和旧健康检查描述。
- 将数据库、Redis、Loki 的连接配置与数据范围统一保存在同一个 Resource Draft/Revision 中：数据库发布目标表前缀、Redis 发布完整 namespace 前缀、Loki 发布平台 Environment/Base 到精确 label selector 的显式映射。
- 完成“平台治理 → 工具资源”的统一编辑体验：连接与范围分区编辑，但共享保存、技术验证、内容哈希和不可变发布版本；Loki 在连接后有界发现 label key/value，不假设 label 名称与平台 topology 同名。
- 保留历史 archive、不可变 migration 证据、ONES 身份边界，以及阻止旧平台和专用密钥回归的负向约束。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-model`: Dashboard 目标链路改为当前标准 MCP Tool Runtime 与资源执行链。
- `builtin-tool-resource`: 工具资源解析、只读执行、Secret、Loki/schema 诊断和运行配置统一由 `tool-mcp` 当前代码 Manifest 与 Published Resource Revision 契约表达。
- `execution-delivery`: 调试、授权复核、诊断上下文和 Tool Call 证据改为当前 `tool-mcp` 链路。
- `identity-access`: 内置只读工具审计场景改为当前 `tool-mcp` 执行与拒绝语义。
- `platform-operations`: 测试资源、功能开关、资源注册、运行配置、migration 与验收描述移除旧平台依赖。

## Impact

- 构建：`backend/Dockerfile`、`.dockerignore`、`backend/vendor/oracle/README.md`。
- 工具资源：新增单调 migration；同步 Resource repository/service/API、`tool-mcp` 解析与只读执行、前端 Resource Draft 表单和回归测试。
- 规范：上述五个 canonical domain 的 delta 与同步结果。
- 验证：退役平台契约测试、Oracle 镜像契约、OpenSpec strict validation、Compose 配置和 `api-server`/`file-service`/`tool-mcp` 定向镜像构建。
- 不改变标准 MCP Tool 的公开标识、RBAC、Secret 隔离、Job provenance、ONES 身份或历史 archive；只把当前缺失的数据范围补入同一个 Resource Revision 并落实既有只读策略。
