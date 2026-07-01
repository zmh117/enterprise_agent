## 1. Schema Directory 平台能力

- [ ] 1.1 在 `internal_api_platform` domain/application 层定义 schema directory 结果模型，包含表、列、类型、nullable、truncated、metadata 和安全限制原因。
- [ ] 1.2 为 MySQL 实现 schema directory 读取器，通过平台连接配置查询 `information_schema`，并按 workshop `table_prefix`、limit 和权限过滤结果。
- [ ] 1.3 为 SQL Server / Oracle executor 增加明确的 unsupported 或占位实现，返回安全错误，不静默假装有 schema。
- [ ] 1.4 新增 `/tools/schema/directory` 或等价 endpoint，复用 `X-Agent-User-Id`、topology registry、access policy 和 request envelope。
- [ ] 1.5 扩展平台错误摘要，把表不存在、字段不存在、空 schema、跨 workshop、非 SELECT 等限制转换为结构化 safe result。
- [ ] 1.6 增加平台单元测试：schema 目录按 workshop 过滤、不泄露连接密钥、truncated 标记、空 schema、安全错误摘要。

## 2. Internal Tools Client 和 Agent Context

- [ ] 2.1 扩展 `InternalApiClient` 协议、`HttpInternalApiClient`、fake/mock client，支持 `get_schema_directory` 工具契约。
- [ ] 2.2 扩展 `ReadOnlyToolService` 和 `mcp_tool_registry`，注册只读 schema directory 工具并写入审计/工具调用摘要。
- [ ] 2.3 扩展 Claude SDK 工具定义，暴露 schema directory 参数 schema，要求传入 environment/base/workshop。
- [ ] 2.4 更新 `AgentContextBuilder`：在可唯一解析目标时预取 schema directory；无法唯一解析时把 addressing 和 schema 工具使用规则注入上下文。
- [ ] 2.5 更新 prompt/tool restrictions：SQL 只能引用 schema directory 中存在的表和列，不得猜测未列出的业务表名。
- [ ] 2.6 增加 context builder 和 internal client 测试，覆盖唯一目标、目标不明确、schema 目录为空和 schema tool 请求 payload。

## 3. 失败路径工具事件持久化

- [ ] 3.1 在真实 Claude runtime 中引入带 `tool_events` 的安全运行时错误或等价包装，覆盖 timeout、SDK 错误和 max-turns exhaustion。
- [ ] 3.2 调整 `_run_async()` 异常映射，确保抛错前已收集的 handler tool events 不丢失且仍做 bounded/脱敏。
- [ ] 3.3 调整 `AgentExecutor`，在 `claude_client.run()` 失败时持久化异常携带的工具事件，再记录 error step 和交给现有失败处理。
- [ ] 3.4 防止 retry 或重复 delivery 时重复写入同一批失败工具事件，必要时增加事件去重 key 或 repository 级保护。
- [ ] 3.5 增加 fake SDK 测试：工具调用后抛 max-turns、timeout、SDK transient，断言 `/tool-calls` 能看到失败前工具摘要。

## 4. 停止试错和 Retry 分类

- [ ] 4.1 将明确的 `Reached maximum number of turns` / max-turns exhaustion 映射为诊断循环收敛失败，区别于网络、429、503、transport transient。
- [ ] 4.2 更新 `JobRetryService` 或错误类型，使 max-turns exhaustion 不再作为普通 transient 立即重复重试同一无效工具循环。
- [ ] 4.3 更新诊断 prompt：schema 缺失、表不存在、字段不足、连续策略拒绝、关键字段缺失时必须停止工具调用并输出“不具备诊断证据”。
- [ ] 4.4 为连续结构化拒绝增加模型侧提示和工具结果标记，避免把平台拒绝解释成继续猜相邻表名。
- [ ] 4.5 增加 runtime 测试：缺 schema/缺字段时返回证据不足报告，且工具调用次数不会跑到 `AGENT_MAX_TURNS`。

## 5. Debug API、文档和端到端验证

- [ ] 5.1 扩展 `GET /api/agent/jobs/{job_id}/tool-calls` 测试，覆盖 FAILED 和 retry-pending job 的失败前工具调用可见性。
- [ ] 5.2 更新 README 本地验证：启动真实 Internal API Platform、验证 schema directory、提交订单诊断、查看 job/steps/tool-calls。
- [ ] 5.3 增加本地 MySQL 样例验证说明：当库里只有 `GL001_EBR_PI(ID)` 这类不足 schema 时，Agent 应返回证据不足而不是反复猜表。
- [ ] 5.4 运行相关后端测试：`test_claude_code_agent_client.py`、`test_agent_runtime_and_worker.py`、`test_internal_api_platform_service.py`、`test_internal_api_client.py`。
- [ ] 5.5 运行 `openspec validate stabilize-diagnostic-tool-loop`，确认 proposal/design/specs/tasks 可进入 apply 阶段。
