## 1. 运行模式与 Compose 稳定化

- [x] 1.1 梳理 `docker-compose.yml` 中 fake、mock-tools、local-tools、real-tools 四种模式，确保服务 profile、注释和默认环境变量含义一致。
- [x] 1.2 将 `internal-api-platform` 明确为 real-tools 主线服务，补齐或恢复 `real-tools` profile，并确认不依赖 `local-internal-api-platform`。
- [x] 1.3 更新 `api-server` 和 `agent-worker` 的 real-tools 启动说明，明确 `FEATURE_REAL_INTERNAL_TOOLS=true` 与 `INTERNAL_API_BASE_URL=http://internal-api-platform:9000` 的组合。
- [x] 1.4 增加配置一致性检查文档或脚本命令，能确认 worker 容器内的 `INTERNAL_API_BASE_URL`、`FEATURE_REAL_INTERNAL_TOOLS`、真实模型开关和 platform 服务状态。

## 2. Internal API Platform Loki 诊断能力

- [x] 2.1 在 `internal_api_platform` 模块中设计 Loki 诊断 application service，复用 topology resolve、access policy、tenant、workshop label 和 Loki client。
- [x] 2.2 新增 bounded labels endpoint，返回当前授权目标和时间窗口内可见的 label 名称、truncated 标记和安全 metadata。
- [x] 2.3 新增 bounded label values endpoint，仅允许 allowlist label，返回候选值、truncated 标记和安全 metadata。
- [x] 2.4 新增 selector probe 或等价诊断能力，返回 selector、query、minutes、stream_count、line_count 和 empty result hints。
- [x] 2.5 将 Loki tenant/auth 错误、upstream timeout/5xx、policy violation、empty result 分成可审计错误分类，避免把空结果误报成平台失败。
- [x] 2.6 确保所有 Loki 诊断响应执行响应大小限制、日志片段脱敏和 secret/token/password/authorization 脱敏。

## 3. Agent 工具契约与调试可观测性

- [x] 3.1 扩展 `InternalApiClient` / `HttpInternalApiClient` 契约以支持 Loki labels、label values、probe 诊断调用。
- [x] 3.2 如需暴露给 Claude 工具，更新 `ToolRegistry` JSON schema，保持只读、bounded、受权限控制，并避免任意 LogQL。
- [x] 3.3 确保 `agent_tool_call` 持久化时包含诊断工具的脱敏 request summary、response summary、metadata source、duration 和 status。
- [x] 3.4 调试 API 查询 tool-calls 时能看出工具结果来自 `internal-api-platform`，并能区分 empty result、policy rejection 和 upstream failure。

## 4. 安全真实模型联调

- [x] 4.1 明确真实 Claude/DeepSeek smoke test 的安全前置：默认只用合成问题、合成 Loki 日志或已脱敏工具摘要。
- [x] 4.2 更新真实模型启动文档，说明 `FEATURE_REAL_CLAUDE=true`、DeepSeek Anthropic-compatible 环境变量和外部模型数据边界。
- [x] 4.3 提供 `FEATURE_REAL_CLAUDE=false` 的真实工具链验证路径，用于只验证 real-tools/Loki 而不调用外部模型。
- [x] 4.4 提供 `FEATURE_REAL_CLAUDE=true` 的安全 debug job 示例，示例内容不得包含真实业务敏感日志。

## 5. 测试覆盖

- [x] 5.1 增加 Loki labels / label values / probe 的单元测试，覆盖成功、截断、allowlist 拒绝、tenant/auth 错误和 upstream retryable 错误。
- [x] 5.2 增加 topology + access policy 下的 Loki 诊断测试，覆盖 GL001/GL002 车间隔离和未授权用户拒绝。
- [x] 5.3 增加 `HttpInternalApiClient` 契约测试，确认诊断 payload 携带 environment/base/workshop、selector、minutes、limit 并解析 envelope。
- [x] 5.4 增加 debug API/tool-call 持久化测试，确认诊断工具调用能被 `/api/agent/jobs/{job_id}/tool-calls` 查询到。
- [x] 5.5 增加 compose/docs smoke test 记录，至少覆盖 real-tools health、resolve、labels、probe/query 和 debug job 查询路径。

## 6. 文档与验收

- [x] 6.1 更新根 `README.md` 和 `backend/README.md`，明确 fake、mock-tools、local-tools、real-tools 的用途和命令。
- [x] 6.2 新增或更新 real-tools Loki 诊断测试文档，记录命令、预期输出、常见 `line_count=0` 排查路径。
- [x] 6.3 更新 `.env.example`，补齐 real-tools 与 Loki 诊断所需环境变量，不写入真实 token/key。
- [x] 6.4 运行 `make check`，确保格式、lint、类型检查、测试和 OpenSpec 校验通过。
- [x] 6.5 运行 `openspec validate stabilize-real-tools-runtime-and-loki-diagnostics` 并修正所有规格问题。
