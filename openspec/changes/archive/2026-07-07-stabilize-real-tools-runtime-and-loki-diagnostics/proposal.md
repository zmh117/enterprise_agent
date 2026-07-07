## Why

当前代码已经具备真实 DB/MQ/worker、`local-tools` 真实 Loki 测试入口，以及拓扑化 `internal-api-platform` 雏形，但运行模式边界还不够稳定：`real-tools` 主线不清晰，Loki 查询命中为空时缺少 label/tenant/selector 诊断能力，真实 Claude/DeepSeek 端到端验证也缺少安全测试边界。

这一步先把“真实工具平台运行链路”做稳：让开发者能明确启动 real-tools，能证明 Agent 通过 Internal API Platform 查询 Loki/DB/Redis，能在 Loki 无命中时定位原因，并能用合成或脱敏数据安全验证真实模型闭环。

## What Changes

- 明确 `internal-api-platform` 是正式 real-tools 主线，`local-internal-api-platform` 保留为本地 Loki 快速联调入口，`mock-internal-api-platform` 保留为假数据入口。
- 整理 Docker Compose profile 与文档，使 fake / mock-tools / local-tools / real-tools 四种模式的启动命令、环境变量和预期服务清晰可验证。
- 为 Loki 增加诊断能力：健康检查、tenant 验证、label 列表、label values、selector dry-run / bounded probe，以及空结果原因提示。
- 将 Loki 查询从“只看 HTTP 200”升级为“可证明 selector 与时间窗口是否命中日志”的验证流程。
- 为 real-tools 增加 smoke test 命令文档：启动服务、检查拓扑、检查权限、查询 Loki labels、查询 Loki logs、提交 debug job、查询 job/steps/tool-calls。
- 明确真实 Claude/DeepSeek 测试安全边界：默认使用合成日志或脱敏工具摘要；未经确认不把真实业务日志、密钥、个人信息或内部敏感内容发送到外部模型。
- 不引入写操作，不做自动修复、删 Redis key、改数据库、重启服务或提交代码。

## Capabilities

### New Capabilities

- `real-tools-runtime`: 定义正式 `internal-api-platform` 在 Docker Compose 和本地开发中的运行模式、profile、环境变量、服务依赖和 smoke test 验证链路。
- `loki-diagnostics`: 定义 Loki 诊断 API 与验证行为，包括 tenant/labels/label values/selector probe/空结果说明，帮助定位真实 Loki 查询为何无命中。
- `safe-real-model-tool-testing`: 定义真实 Claude/DeepSeek 与真实工具链联调的安全边界，要求使用合成数据或脱敏摘要，避免把敏感日志直接发送到外部模型。

### Modified Capabilities

- `readonly-tool-platform`: 扩展只读工具平台要求，使真实 Loki 查询除了 bounded query 外，还必须提供受限诊断能力和清晰错误分类。
- `agent-job-debug-api`: 扩展调试验证要求，使 real-tools smoke test 能通过 job、steps、tool-calls 观察真实工具链结果。

## Impact

- 代码：影响 `docker-compose.yml`、`backend/app/internal_api_platform.py`、`backend/app/modules/internal_api_platform/`、`backend/app/modules/internal_tools/`、`backend/app/modules/agent/` 真实工具调用与调试链路。
- API：新增或扩展 Internal API Platform 的 Loki 诊断 endpoint；保持工具调用仍走 Internal API Platform，不让 Agent 直连 Loki。
- 配置：梳理 `FEATURE_REAL_INTERNAL_TOOLS`、`INTERNAL_API_BASE_URL`、`INTERNAL_PLATFORM_TOPOLOGY_FILE`、`LOKI_*`、`SECRET_*`、真实模型相关环境变量。
- 文档：更新中文 README、backend README、real-tools/Loki 测试记录文档。
- 测试：增加 Loki 诊断单元测试、real-tools contract 测试、空结果/tenant 错误/selector 错误分类测试，以及可选真实 Loki smoke test 记录。
