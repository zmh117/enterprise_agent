## 1. 基线与规格协调

- [x] 1.1 记录当前 Worker、Python 进程内 SDK、TypeScript Runtime、RuntimeMigrationGate、协议、模型 probe、Tool/MCP 和 Compose 接线基线，并保护现有未提交改动
- [x] 1.2 在 `migrate-claude-agent-sdk-to-typescript` 的实施记录中标明本变更取代“Python SDK 保留在 Worker”和“门禁选择 Runtime”的决策，协调其 7.1-7.5 未完成/冲突验收项
- [x] 1.3 固化 Python 进程内路径与现有 TypeScript Runtime 的成功、Tool、取消、timeout、最大轮次、错误分类和终态恢复 golden fixtures
- [x] 1.4 固定 MCP 阶段边界：本变更永久删除 `runtime-tool-mcp` 及 HS256 key 并接入官方 MCP SDK 标准服务；API Capability 等控制面退役延后，且不得新增 MCP Token、签名或治理层

## 2. Agent与Job数据模型迁移

- [x] 2.1 为 Agent Definition 增加非空、受限且创建后不可变的 `runtime_kind`，并更新领域对象、repository、API schema 和审计投影
- [x] 2.2 升级 Agent Publication snapshot schema，将 Definition runtime kind 写入 canonical snapshot/hash，并在读取、发布和回滚时校验一致性
- [x] 2.3 编写可重复执行的数据迁移，把现有 `default-diagnostic-agent` 及历史 Publication 确定性回填为 `python-v1`，同时保留历史 Job 已存 runtime kind
- [x] 2.4 新增可重复执行 seed，创建固定 `typescript-v1` 的 `typescript-diagnostic-agent` 及合法初始草稿/Publication，且不自动改写任何 Application
- [x] 2.5 为新 schema Job 固定 Agent Definition/Publication、revision/hash、runtime kind 和协议版本，并为 legacy Job 定义显式兼容读取规则
- [x] 2.6 增加迁移、hash、防篡改、runtime 不可变、重复 seed、历史 Job 和回滚测试

## 3. 统一Runtime协议与客户端

- [x] 3.1 扩展单一 Runtime JSON Schema，使执行、事件、取消、终态恢复和 model probe 同时支持 `python-v1` 与 `typescript-v1`
- [x] 3.2 从 schema 生成或校验 Python/TypeScript 类型，并覆盖未知版本/字段、大小上限、sequence、唯一终态和 digest conflict
- [x] 3.3 实现平台固定 `RuntimeClientRegistry`，仅把受支持 runtime kind 映射到配置的内部服务 URL，拒绝请求或 Publication 提供任意 URL
- [x] 3.4 复用现有 Runtime Grant 并扩展为双 Runtime 可验证的 service identity/runtime claims，明确其不得进入 MCP 请求或替代已删除的 MCP signing key
- [x] 3.5 建立同一组 provider/consumer contract 与 golden fixtures，强制两个 Runtime 返回等价的 accepted/tool/diagnostic/completed/failed/cancel 语义

## 4. 独立Python Agent Runtime

- [x] 4.1 新增 `python-agent-runtime` 服务入口与配置，提供 health、ready、version、执行流、取消、终态读取和 model probe 端点
- [x] 4.2 将现有 Python Claude Agent SDK adapter、事件归一化、执行限制和稳定错误分类迁入 Python Runtime 边界
- [x] 4.3 实现 Python Runtime invocation registry/terminal ledger，覆盖相同 invocation/digest 恢复、摘要冲突和取消/完成竞争
- [x] 4.4 在 Python Runtime 内按 Job 固定模型连接 revision/hash 只读解析 active Secret，确保 Worker 请求、日志和终态不含 provider 明文凭据
- [x] 4.5 让 Python Runtime 使用 Job 冻结的 Tool 配置调用标准 MCP SDK Tool Server，不发送 MCP Token、Runtime Grant 或任意 Server URL
- [x] 4.6 为 Python Runtime 增加 SDK fake、Tool fake、probe、timeout、错误、敏感屏蔽、ledger 重启和 contract 测试

## 5. Worker纯编排改造

- [x] 5.1 改造 `AgentExecutor`/Job handler，使 Python、TypeScript 两条路径都通过 `RuntimeClientRegistry`，公共编排代码不 import SDK 类型
- [x] 5.2 删除新 Job 对 RuntimeMigrationGate、environment allowlist 和 Application allowlist 的读取，Runtime 只从 Agent Publication 冻结到 Job
- [x] 5.3 在调用 Runtime 前复核 Job/Agent/Application Publication、hash、授权、协议和 runtime kind 一致性，未知或冲突值失败关闭
- [x] 5.4 保持 Worker 对 retry/终态、Tool 事件、结果、Delivery Outbox 和 RabbitMQ ack 的唯一事务所有权
- [x] 5.5 实现 Runtime 已完成但 Worker 提交失败、重复 RabbitMQ 消息和 Worker 重启时使用相同 invocation/digest 恢复终态
- [x] 5.6 将 Job 取消、attempt timeout 和 Worker shutdown 传递到原固定 Runtime，并处理唯一取消/超时终态
- [x] 5.7 更新安全 provenance 与管理查询，展示 runtime/协议/SDK/CLI/invocation/digest/稳定错误码且不泄漏 Prompt、Secret 或私有推理
- [x] 5.8 聚合双 Runtime readiness，阻止依赖未就绪 Runtime 的新激活/新 Job，同时保留管理 API 和另一 Runtime 的真实状态

## 6. Agent与Application管理体验

- [x] 6.1 移除后端“只有默认 Agent 可编辑”的管理限制，让两个内置 Agent 都支持草稿、校验、发布、历史和回滚
- [x] 6.2 改造 Agent 前端为可选择的 Agent 列表/详情，分别管理 Python 与 TypeScript Agent 并只读展示 runtime kind
- [x] 6.3 更新 Business Application 管理 API，校验精确 Agent Publication、runtime kind 与 Definition 一致，拒绝独立 runtime override/runtime URL
- [x] 6.4 更新 Application 前端选择器，展示 Agent code、Publication revision 和 runtime 标签，并支持选择 Python 或 TypeScript Agent Publication
- [x] 6.5 验证发布新 Agent 不自动切换 Application；只有显式更新、发布和激活新的 Application revision 才影响后续 Job
- [x] 6.6 增加 Agent/Application 权限、字段校验、并发 revision、Publication 完整性和前端交互回归测试

## 7. 依赖、镜像与Compose部署

- [x] 7.1 将 `claude-agent-sdk` 从公共 Python dependencies 拆到 Python Runtime 专属、精确锁定的依赖组/清单，保证 API、Migrator 和 Worker 不安装它
- [x] 7.2 新增 Python Runtime 镜像 target，只在其中安装 Python SDK、Node/Claude Code CLI、协议和必要 Runtime 代码
- [x] 7.3 将 `agent-worker` 改为纯 Python 编排镜像 target，移除 `claude-runtime` 继承、Node/CLI、SDK 和 `.claude` 执行配置
- [x] 7.4 保持 TypeScript SDK 只位于 TypeScript Runtime 镜像，并统一两个 Runtime 的非 root、只读文件系统、tmpfs、cap drop、资源限制和健康检查
- [x] 7.5 更新 Compose 服务名、固定内部 URL、私有网络、启动依赖、双 Runtime readiness 和最小只读数据库/Secret 文件授权
- [x] 7.6 增加镜像内容与部署权限测试，证明 Worker 无两种 SDK/CLI、Runtime 无 RabbitMQ/Job/Delivery 写权限且各镜像只含所需 SDK
- [x] 7.7 新增仅在固定私有网络可达、无宿主机端口、无 Token/签名密钥的官方 MCP SDK 标准 Tool Server，并让两个 Runtime 使用同一 Tool schema
- [x] 7.8 删除 `runtime-tool-mcp` 容器/模块、`RuntimeToolTokenIssuer`/verifier、HS256 signing key secret、`RUNTIME_TOOL_MCP_*` 配置、专用 claims 和兼容测试，确认不存在双运行路径

## 8. 自动验证、真实链路与清理

- [x] 8.1 运行 Python Runtime、TypeScript Runtime 的 lint/typecheck/unit/contract/build，并对相同 golden fixtures 比较稳定终态和错误分类
- [x] 8.2 运行后端 Ruff、聚焦单元/集成、迁移、Agent/Application、Worker、RabbitMQ retry、Delivery 和 readiness 测试
- [x] 8.3 运行前端 lint/typecheck/test/build，验证两个 Agent 的独立发布与 Application Agent Publication 选择流程
- [x] 8.4 运行 Compose fake-provider 闭环，分别证明 Python/TypeScript Job 成功、失败、延迟重试、dead-letter 和一次 Delivery
- [x] 8.5 演练 Worker/两个 Runtime 在执行前、流式中和 Runtime 完成后本地提交前重启，证明 invocation 恢复且不重复模型执行/Delivery
- [x] 8.6 使用可丢弃配置分别完成 Python 与 TypeScript 的真实模型、只读 Tool、取消、重试和失败投递 smoke
- [x] 8.7 分别验证真实 `DingTalk -> Application Publication -> Agent Publication -> RabbitMQ -> Worker -> selected Runtime -> standard MCP Tool Server -> Result -> Delivery` 两条链路
- [x] 8.8 扫描数据库、RabbitMQ、日志、Runtime ledger、Job/Tool 事件和 Delivery，确认无 Key、Token、Secret、完整 Prompt、原始 payload 或私有推理
- [x] 8.9 在应用完成显式迁移后删除 Worker 进程内 SDK adapter、RuntimeMigrationGate 代码/配置和旧镜像层，并验证新 Job 无双事实源或跨 Runtime fallback
- [x] 8.10 运行 OpenSpec strict validation、`git diff --check` 和全量相关回归，证明旧 MCP 服务/key 已删除、Runtime Grant 未泄漏到 MCP，并记录后续控制面退役 change 的明确边界
