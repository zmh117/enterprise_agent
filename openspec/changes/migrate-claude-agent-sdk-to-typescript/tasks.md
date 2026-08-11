## 1. 基线与契约

- [x] 1.1 记录当前 `mcp_new` Python Runtime、Tool、模型连接、Worker 和 Compose 基线，并建立不覆盖现有未提交改动的移植清单
- [x] 1.2 固化 Python Runtime 成功、Tool 事件、timeout、最大轮次、权限拒绝、瞬时错误和矛盾结果的 golden 测试
- [x] 1.3 移植并核对执行请求、Runtime Grant、NDJSON 事件、取消、终态和错误码 JSON Schema
- [x] 1.4 从单一 schema 生成或校验 Python/TypeScript 类型，并覆盖未知字段、版本、摘要、sequence 和大小上限

## 2. TypeScript Runtime 基础设施

- [x] 2.1 移植独立 `agent-runtime` workspace、精确 SDK lockfile、strict TypeScript、lint、test 和 build 配置
- [x] 2.2 实现配置启动校验、结构化脱敏日志、health、ready 和 version，健康检查不得调用模型
- [x] 2.3 实现 Runtime Grant 验证、JTI 重放保护、invocation registry、terminal ledger 和 digest 冲突处理
- [x] 2.4 实现流式执行和取消端点，保证单调 sequence、唯一终态、断线取消和有界输出

## 3. 模型与SDK执行

- [x] 3.1 实现与 Python encrypted Secret 兼容的只读模型连接/active Secret 解析及交叉 fixture
- [x] 3.2 实现 TypeScript Claude SDK adapter，强制 `settingSources: []`、固定模型/限制、AbortController 和独立 env
- [x] 3.3 实现精确远程 MCP 配置、`allowedTools`、`canUseTool` 失败关闭及内置危险 Tool denylist
- [x] 3.4 归一化文本、Tool、usage、completed/failed 事件并实现稳定 retry/error 分类和敏感内容屏蔽
- [x] 3.5 实现无 Tool、单轮、短超时的 `/internal/v1/model-probes`

## 4. 当前工具的远程MCP边界

- [x] 4.1 盘点 `mcp_new` 当前进程内只读 Tool 与受治理业务查询，形成 TypeScript 灰度必需的等价映射
- [x] 4.2 为灰度 Application 实现受治理远程 MCP 服务或适配器，复核短期 Token、Job、主体、Application、scope、schema hash 和资源绑定
- [x] 4.3 验证未映射 Tool、未授权 Tool、伪造主体/resource/header、过期 Token 和写 Tool 均失败关闭且不自动回退 Python

## 5. Python Worker与模型连接集成

- [x] 5.1 移植 Python Runtime protocol/client，验证服务身份、流式 schema、sequence、digest、大小和唯一终态
- [x] 5.2 改造 `AgentExecutor` 通过路由客户端调用 Runtime，同时保持 Python claim、授权、retry、结果事务和 Delivery 所有权
- [x] 5.3 实现冻结到 Job/Application 的 `python-v1`/`typescript-v1` migration gate，单次 attempt/retry 不跨 Runtime fallback
- [x] 5.4 按 sequence 持久化安全 Tool event 与 runtime provenance，并覆盖 Worker/Runtime 重启和终态恢复
- [x] 5.5 将模型连接测试接入 TypeScript probe，同时保持 Python RBAC、SSRF、redirect、host allowlist 和 revision/hash 校验
- [x] 5.6 聚合 TypeScript Runtime readiness，不在 API 健康检查中调用模型或 MCP Tool

## 6. 部署与自动验证

- [x] 6.1 增加 Runtime 最小只读数据库授权、Master Key/服务 Token 文件挂载和部署前权限检查
- [x] 6.2 更新 Worker 镜像与 Compose，加入非 root、只读文件系统、tmpfs、`cap_drop: ALL`、私有网络和健康依赖的 Runtime/MCP 服务
- [x] 6.3 运行 TypeScript lint、typecheck、unit、contract、build 和容器策略测试
- [x] 6.4 运行后端 Ruff、聚焦单元/集成、模型连接、Worker、重试/失败投递、迁移和敏感日志测试
- [x] 6.5 运行 OpenSpec strict validation、`git diff --check` 并记录仍需真实凭据验证的门禁

## 7. 灰度、真实链路与双Runtime长期运行

> 后续拓扑由 `separate-agent-worker-and-dual-runtimes` 取代：7.1-7.3 的真实链路与敏感扫描并入新变更 8.6-8.8；7.4 的 RuntimeMigrationGate 验收被 Agent Publication 固定 Runtime 取代；已完成的 7.5 仅记录旧阶段事实，不再作为最终 Worker 镜像或 Python 进程内 SDK 的保留门槛。

- [ ] 7.1 在可丢弃 Application 显式选择 `typescript-v1`，验证真实模型、只读 MCP、取消、重试、Runtime 重启和失败投递
- [ ] 7.2 验证真实 `DingTalk → Inbox/Outbox → RabbitMQ → Python Worker → TypeScript Runtime → MCP → Result → Delivery` 链路
- [ ] 7.3 扫描数据库、RabbitMQ、日志、Runtime ledger、事件和 Tool provenance，确认不存在 Key、Token、Secret、完整 Prompt或私有推理
- [ ] 7.4 验证未命中显式 TypeScript 门禁的新 Job 始终默认 `python-v1`，并完成 TypeScript Application 对未开始 Job 的回滚演练
- [x] 7.5 固化双 Runtime 长期兼容门禁：保留 Python SDK、进程内真实适配器和 CLI/Node Worker 镜像层，禁止以 TypeScript 灰度完成为由删除
