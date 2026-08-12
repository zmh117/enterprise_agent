## 1. 协议与契约测试

- [x] 1.1 为固定版本 Python Claude Agent SDK 增加真实 MCP `CallToolResult._meta` 保真测试，验证 `mcp_call_id` 与 `agent_tool_call_id` 能从 Tool Result 提取且不进入模型可见正文
- [x] 1.2 为固定版本 TypeScript Claude Agent SDK 增加同等 `_meta` 保真测试，并让任一 SDK 不保真时验收失败而不是启用模糊关联
- [x] 1.3 新增 Agent Runtime v1.1 JSON Schema、limits/errors 与 Python/TypeScript 生成类型，定义 `tool_origin`、可空 `server_code`、`mcp_call_id` 和 `persisted_tool_call_id`
- [x] 1.4 增加 v1.0/v1.1 协议矩阵测试，证明 Worker 先双读、旧事件保守归类、新事件不会被旧 Worker 提前接收

## 2. 数据库 Expand Migration

- [x] 2.1 增加下一顺序 migration，扩展 `agent_tool_call` 的 invocation、Runtime Tool Use、origin、server、MCP Call 和 writer 字段及约束
- [x] 2.2 通用化 `mcp_operation_audit`，增加 `mcp_call_id`、parent、invocation、通用授权/资源/业务载荷字段，并将 ONES 专用身份字段改为可选扩展
- [x] 2.3 增加一对一/一对多唯一约束、外键与 Job/server/tool/status/retention 查询索引，确保删除 MCP 审计不会级联删除 Agent Tool Call
- [x] 2.4 对现有 ONES 审计做非破坏、确定性回填并标记 legacy/unlinked；不得按 `job_id + tool_name` 猜测 `agent_tool_call_id`
- [x] 2.5 更新 SQLite/PostgreSQL migration、Schema fact source、数据库 grants 和迁移回归，验证现有业务数据与历史审计保持可读

## 3. 通用 MCP 审计协调器

- [x] 3.1 新建共享 `McpAuditCoordinator` 与 Repository，事务性创建相互关联的 `agent_tool_call(STARTED)` 和 MCP TOOL 根事件
- [x] 3.2 实现 AUTHORIZATION、RESOURCE、PROVIDER、CREDENTIAL 子事件写入和成功/失败/拒绝终态完成，所有事件使用同一 `mcp_call_id`
- [x] 3.3 实现有界完整业务 JSON 序列化、截断标志与认证材料递归拒绝，覆盖请求、响应和异常路径
- [x] 3.4 实现幂等 begin/complete/recovery 语义和审计不可用失败关闭，保证外部访问前已存在根事实
- [x] 3.5 实现 MCP `CallToolResult._meta` 平台命名空间投影，禁止 Agent Input、Principal 或 Provider 响应覆盖服务端 ID

## 4. tool-mcp 接入通用审计

- [x] 4.1 在 `tool-mcp` 有效 Job/Tool 校验后调用协调器首写根事实，并移除 `ReadOnlyToolService` 分散创建 `agent_tool_call` 的职责
- [x] 4.2 为业务应用授权、Tool/schema 校验和数据范围决策写 AUTHORIZATION 事件，拒绝路径不建立资源连接
- [x] 4.3 为数据库、Redis、Loki 和 Schema Tool 的唯一资源解析、placement、Resource Revision 与执行结果写 RESOURCE/TOOL 事件
- [x] 4.4 在成功、失败和业务拒绝结果中返回关联 `_meta`，保持业务 structured content 与 Tool Schema 不暴露内部 ID
- [x] 4.5 增加 tool-mcp 单次、同名重复、并发、授权拒绝、资源失败、审计失败和无认证材料回归测试

## 5. ones-mcp 接入通用审计

- [x] 5.1 用共享协调器替换 ONES 专用审计 Repository 写入，同时保留 Principal、External Identity、Team、Credential Revision 扩展上下文
- [x] 5.2 让一次 ONES Tool Call、首次 Provider Attempt、Token 刷新、重试和终态共享同一 `mcp_call_id` 与 Agent Tool Call
- [x] 5.3 覆盖 Principal/业务授权拒绝、Provider 失败和 Credential 失败事件，未进入 Provider 时不得产生伪造 Provider 成功证据
- [x] 5.4 在 ONES 成功、失败和拒绝结果中返回关联 `_meta`，证明 JWT、Token、密码和 Header 不进入审计或模型正文
- [x] 5.5 更新 ONES MCP2 Mock/容器回归，验证成功查询、401 刷新一次、同名并发、审计失败关闭和精确关联

## 6. 双 Runtime 来源分类与精确回传

- [x] 6.1 修复 Python Runtime，使用 `tool_use.id`/`tool_result.tool_use_id` 聚合同一调用，并只按完整 MCP 名称与 Job Binding 设置 `tool_origin=mcp`
- [x] 6.2 为 Python SDK builtin、平台注册 SDK Tool 和未知 Tool 建立代码目录与 `sdk_builtin`/`sdk_custom`/`unknown` 分类，删除未知工具的 `tool-mcp` 缺省值
- [x] 6.3 修复 TypeScript Runtime 未识别和拒绝 Tool Event 的来源分类，使非 MCP Tool 的 `server_code` 与 `mcp_call_id` 为空
- [x] 6.4 让两个 Runtime 从 MCP Tool Result `_meta` 提取服务端 ID，并在终态 Tool Event 中携带真实 SDK Tool Use ID、`mcp_call_id` 与 `persisted_tool_call_id`
- [x] 6.5 增加 Python/TypeScript 等价性测试，覆盖 MCP、SDK builtin 拒绝、SDK custom、unknown、STARTED/终态和失败前证据

## 7. Worker 持久化与 API 查询

- [x] 7.1 将 Worker Tool Event 持久化改为按 `(job_id, invocation_id, runtime_tool_call_id)` 幂等 upsert，一次 SDK Tool Use 只形成一条 `agent_tool_call`
- [x] 7.2 对 MCP Event 按 `persisted_tool_call_id + mcp_call_id` 更新服务端首写行并跳过重复插入；对 SDK/unknown Event 由 Worker 创建行
- [x] 7.3 删除 `job_id + tool_name` 批量关联实现和调用点，增加同名连续/并发 Tool Call 不串链回归
- [x] 7.4 扩展 Job Tool Call API 投影 origin、server、Runtime/MCP Call ID，同时保持既有路径、授权和安全摘要兼容
- [x] 7.5 扩展管理员 MCP 审计 API 的 server/tool/event/status/job/mcp_call 筛选和详情投影，并验证 `audit:*:read` 与读取审计

## 8. 保留期、部署与端到端验收

- [x] 8.1 将 MCP 审计保留任务迁移到共享 Repository，按批次删除到期详细事件且不删除 `agent_tool_call`、Job 或平台审计
- [x] 8.2 更新 readiness，验证通用 Schema、写权限、保留期配置和两个 MCP Server 的审计依赖，失败时阻止业务调用
- [x] 8.3 按 Worker 双读 → migration/shared code → tool-mcp → ones-mcp → 双 Runtime v1.1 → 新 Publication 的顺序完成 Compose 部署验证
- [x] 8.4 执行 Python/TypeScript 双 Runtime E2E，证明 tool-mcp 与 ones-mcp 均形成 Agent Tool Call、TOOL 根事件和精确子证据关联
- [x] 8.5 检查在线数据库无新增模糊/空关联、同名调用不串链、SDK Tool 不进入 MCP 审计、认证材料扫描为零
- [x] 8.6 运行相关后端、前端、Runtime、MCP2 容器、migration、strict OpenSpec 和 `git diff --check` 验证并记录可复现证据

## 验证证据（2026-08-12）

- 相关后端回归：144 passed；固定版本 Python/TypeScript Claude Agent SDK 真实远程 MCP `_meta` 保真：2 passed（需允许监听本机临时端口）。
- 全量后端回归：783 passed、28 skipped、2 subtests passed；另有 2 个与本 change 无关的既有失败，均仍引用 migration 103 已移除的旧 `agent_session` 列。
- PostgreSQL migration/并发回归：16 passed；migration head 为 105，同名并发 MCP 调用保持精确一对一根关联。
- TypeScript Runtime：contract generation check、typecheck、lint 全部通过，38 tests passed。
- 前端：build、lint 通过，96 tests passed；构建只有既有 chunk size warning。
- 隔离 Compose 双 Runtime 验收：10 个 Agent Runtime v1.1 Job 全部达到预期终态；基础场景覆盖 Python/TypeScript 成功、重试一次后成功、失败，MCP 场景覆盖两个 Runtime 分别调用 tool-mcp 与 ones-mcp。
- MCP 全链路验收形成 4 个成功 Job、5 条 `agent_tool_call`、15 条 `mcp_operation_audit` 和 5 个互异 `mcp_call_id`；其中 ONES 首次 Provider 401、Credential 刷新、成功重试共享同一根，TypeScript 两次同名并发调用保持两个独立根。
- 验收逐 Job 校验 TOOL 根、AUTHORIZATION/PROVIDER/CREDENTIAL 子事件的精确主键关联；无新增 legacy/空关联，SDK Tool 未进入 MCP 审计，认证材料跨审计、Runtime 事件、Tool Call 与 Job 持久化扫描为零。
- `openspec validate unify-mcp-operation-audit --strict` 与 `git diff --check` 通过；模糊关联实现扫描无命中。
