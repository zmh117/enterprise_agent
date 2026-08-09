## 1. 基线、版本与跨语言契约

- [x] 1.1 在当前 `mcp_dev` 状态记录 MCP 前置变更、未完成验收项和可回退 commit，确认不从 `master` 恢复旧 API/Internal Platform 代码
- [x] 1.2 为现有 Python Claude Runtime 增加 golden characterization，覆盖成功、Tool 事件、timeout、最大轮次、权限拒绝、瞬时错误和矛盾 result
- [x] 1.3 从官方 npm registry 解析实施日期最新非 prerelease `@anthropic-ai/claude-agent-sdk`，验证官方 changelog/Node 要求并将精确版本写入 lockfile 与验收记录
- [x] 1.4 定义 `AgentExecutionRequestV1`、Runtime Grant、NDJSON Event、Cancel 与 Terminal Result JSON Schema，并设置字段/事件/总字节上限
- [x] 1.5 从单一 schema 生成 Python 与 TypeScript 类型和校验器，增加未知字段、版本不支持、摘要不一致和超限 contract test
- [x] 1.6 定义跨语言稳定错误码、retry class、Tool event、usage、runtime provenance 与敏感字段 denylist 的 golden fixture
- [ ] 1.7 在前置 `simplify-platform-with-mcp` 归档后重新对照 main specs 处理 delta 冲突，并运行本变更 strict validation

## 2. TypeScript Runtime 服务骨架

- [x] 2.1 创建独立 `agent-runtime/` TypeScript workspace、package scripts、strict tsconfig、lint、test 和精确 package lock
- [x] 2.2 实现配置加载和启动校验，拒绝未知环境配置、浮动 SDK 版本及不安全 Runtime/Provider 地址
- [x] 2.3 实现不调用模型的 `/health`、`/ready` 和版本端点，报告 protocol、SDK/CLI、Secret/DB 与依赖的脱敏状态
- [x] 2.4 实现非 root、只读文件系统、分阶段构建的 Runtime Dockerfile，并验证镜像无 Python Claude SDK 和启动时安装
- [x] 2.5 实现 Runtime Grant 验签、audience/azp/Job/invocation/digest/expiry/JTI 校验及有界拒绝审计
- [x] 2.6 实现 invocation registry/terminal ledger，相同 ID+digest 可恢复、不同 digest 冲突且并发重复只启动一次执行
- [x] 2.7 实现 `POST /internal/v1/executions` NDJSON 流与严格 sequence/单终态规则
- [x] 2.8 实现取消端点、客户端断线处理和 AbortController 传播，并覆盖重复取消与已终态取消
- [x] 2.9 实现结构化日志、trace/correlation 和全路径敏感值屏蔽/截断

## 3. 模型连接与 Secret 边界

- [x] 3.1 为 Runtime 新增最小 PostgreSQL service role/grant，只允许读取固定模型连接和 active Secret 必需字段
- [x] 3.2 使用只读文件挂载 Master Key，在 Node 实现 encrypted DB Secret 版本/tag/AEAD 解密与失败关闭
- [x] 3.3 增加 Python/Node 加密 fixture 交叉兼容、错误 Key、篡改 tag、禁用/缺失 Secret 和输出扫描测试
- [x] 3.4 实现按模型连接 revision/config hash/Secret binding 解析 attempt 运行绑定，拒绝 `latest`、全局 URL/model/key fallback
- [x] 3.5 为每个 invocation 构造隔离的 SDK env/options，禁止修改共享 `process.env` 或跨 Job 缓存认证材料
- [x] 3.6 将 Model Connection 真实测试委托给 Runtime 的无 Tool、单轮、短超时 probe，并保留 API/RBAC/SSRF 双重校验
- [x] 3.7 覆盖 active Key 轮换、连接停用、Provider host/DNS 变化和两个并发 Job 使用不同连接的隔离测试

## 4. TypeScript Claude SDK 与 MCP 执行

- [x] 4.1 实现 TypeScript `query()` adapter，显式设置 `settingSources: []`、Job 固定 system prompt/model/limits 和 AbortController
- [x] 4.2 从请求构造精确远程 MCP Server config 和 `allowedTools`，禁止无 eligible Tool 时注册 Server
- [x] 4.3 实现 deny-by-default `canUseTool` 与 Bash/Write/Edit/NotebookEdit/WebFetch/WebSearch/Shell denylist
- [x] 4.4 验证 Runtime 只能使用 Worker 传入的短期 MCP Token，Token 不进入 Prompt、Tool input、事件、日志或 terminal ledger
- [x] 4.5 归一化 SDK message、文本、usage、Tool start/result/failure 和 final result，丢弃 thinking/private reasoning 与原始 payload
- [x] 4.6 实现 timeout、最大轮次、最大 Tool Call、cancel、认证、模型、429/5xx、transport、CLI decode 和矛盾 result 分类
- [x] 4.7 增加 MCP 旧协议客户端到 MCP v2 ONES/Data Server 的真实协议测试，并校验 Tool Schema hash 与 scope
- [x] 4.8 增加提示注入、不可信 MCP 输出、伪造主体/resource/header、未授权 Tool 和内置写 Tool 的失败关闭测试

## 5. Python Worker 集成与状态所有权

- [x] 5.1 实现 Python Runtime client，验证服务身份、流式 schema、sequence、digest、大小和单终态
- [x] 5.2 让 AgentContextBuilder 构造 TypeScript 请求所需的固定安全上下文，但不包含模型 Key、Secret value 或任意可编辑权限字段
- [x] 5.3 让 Worker 为 invocation 签发 Runtime Grant 和精确 MCP Token，并验证 TTL、audience、Job/Publication 与撤销语义
- [x] 5.4 改造 AgentExecutor 使用 Runtime client，继续由 Python claim、授权、决定 retry、提交 Job/result 和创建 Delivery outbox
- [x] 5.5 按 sequence 持久化成功/失败前 Tool event 与 Runtime provenance，拒绝重复、缺口和摘要冲突
- [x] 5.6 实现 Worker timeout/Job cancel/连接断开到 Runtime cancel，以及 Runtime 终态重取后的本地事务恢复
- [x] 5.7 聚合 Runtime health/readiness 到 `/api/ready`，不在检查中调用模型或业务 MCP Tool
- [x] 5.8 实现按环境/Application Publication 冻结的迁移 gate，保证单次 attempt/retry 不自动跨 Python/TypeScript fallback
- [x] 5.9 增加 Worker 重启、Runtime 重启、终态后断线、重复 RabbitMQ delivery 和 retry/dead-letter 集成测试

## 6. MCP Tool Publication 治理

- [x] 6.1 设计并迁移 MCP Tool stable identity、Draft、Verification、immutable Publication/Revision、lifecycle、usage 与 expected revision 约束
- [x] 6.2 建立由 ONES/Data MCP 代码/构建产物拥有的安全 Tool catalog，同步 Server version、Tool name、Schema hash、scope 与 Resource kind
- [x] 6.3 实现 Tool Draft 创建/修改/校验/发布/历史/回退/停用 service，拒绝自由 Tool、URL、Schema、查询、脚本和认证字段
- [x] 6.4 实现 Data Tool 到精确 active Resource Deployment/Revision 校验和 ONES Tool 不绑定共享用户 Credential 的规则
- [x] 6.5 在 Agent Publication 冻结最大 Tool Publication 集合，并在 Application Publication 只允许选择其合法子集
- [x] 6.6 更新 Job freeze/effective intersection，精确组合 Agent、Application、主体/凭据、Resource 和 Server scope
- [x] 6.7 实现停用/依赖 usage guard、既有 Job 调用前撤权复核和过期 Token/停用/scope/resource 的 `DENIED` provenance
- [x] 6.8 提供 Session/RBAC/CSRF 管理 API 与复用同一 service 的 `platformctl mcp publication` 命令
- [x] 6.9 覆盖并发冲突、重复发布、跨 Agent/Application 引用、多个活动版本、回退和脱敏审计测试

## 7. Agent 与 Application 后端控制面恢复

- [x] 7.1 恢复/重建 Agent Definition/Draft/Validation/Publication/rollback/lifecycle 管理 API，使用当前 MCP/模型契约而非旧 Capability 依赖
- [x] 7.2 扩展 Agent 管理 service 支持多个 Agent 的创建、停用和无活动引用归档，并保留默认诊断 Agent seed
- [x] 7.3 恢复/重建 Business Application create/edit/validate/publish/history/activate/deactivate/lifecycle service 与 API
- [x] 7.4 更新 Application Draft/snapshot/schema hash，使其冻结 Agent、MCP Tool/Resource、Channel/Trigger/Delivery 和 Runtime contract
- [x] 7.5 更新 Resolver 与 Job 创建链，使显式环境激活接管新入口、多个 Application 路由确定且既有 Job 不漂移
- [x] 7.6 实现 Agent/Application/MCP Tool 的交叉 usage、依赖保护和防枚举查询
- [x] 7.7 为所有写路由补 RBAC、CSRF、expected revision、幂等键、字段级错误和脱敏审计
- [x] 7.8 增加静态/运行测试，证明 Capability、Handler、Connection、旧 Resource Composition 和 Internal API Platform 未复活

## 8. Agent Publication 与 Application 前端

- [x] 8.1 重建 Agent 和 Application 的 TypeScript domain、API client、TanStack Query key/mutation 与统一错误映射
- [x] 8.2 实现权限感知 Agent 列表、loading/empty/error、生命周期和 Publication/Runtime/Application usage 摘要
- [x] 8.3 实现 Agent 详情的业务指令、模型连接、执行限制、Skill、MCP Tool 最大集合、校验、发布历史和回退
- [x] 8.4 实现模型连接 configured/版本/测试 UI，确保无 Secret 权限时不显示写动作且任何响应不含 Secret ref/value
- [x] 8.5 实现 Business Application 列表、详情、Agent Publication 与 MCP Tool 子集/Resource 选择
- [x] 8.6 实现 Channel/Trigger/Delivery、校验错误、Publication 历史、test/production 激活/停用和 effective preview
- [x] 8.7 替换 `/applications` 退役页并恢复 Agent/Application 权限导航，继续保留 `/platform/resources` 等旧平台退役状态
- [x] 8.8 增加 revision 冲突刷新、重复提交幂等、未认证/无权、防枚举和敏感字段扫描测试
- [x] 8.9 完成键盘、焦点、标签、状态非颜色语义、窄屏和大数据列表可用性验收

## 9. 部署、迁移与旧 Runtime 删除

- [x] 9.1 将 `agent-runtime` 加入 Compose，配置私有网络、服务认证、Master Key 只读挂载、最小 DB role、资源限制和健康依赖
- [x] 9.2 调整 Worker 镜像和 Compose，使 Python Worker 不挂载 Master Key、不安装 Node/Claude CLI，并为 Runtime 配置独立 egress
- [x] 9.3 增加部署前 contract/SDK/CLI/DB grant/Secret permission 检查和 runtime version provenance
- [x] 9.4 编写测试环境 canary、无自动 fallback、在途 Job、取消、回滚和观察窗口 Runbook
- [ ] 9.5 在可丢弃环境把指定 Application 显式切到 `typescript-v1`，验证后再切换测试环境默认新 Job
- [ ] 9.6 生产切换前确认所有真实 E2E 和安全门禁通过，并要求用户明确安排维护/观察窗口
- [ ] 9.7 观察通过后删除 Python Claude SDK adapter、依赖、测试替身、线程/event-loop bridge、全局 CLI 镜像层和旧 feature gate
- [x] 9.8 更新架构、数据链路、配置、故障诊断、升级和回滚文档，并记录精确 Node/SDK/CLI/协议版本

## 10. 验收与发布门禁

- [x] 10.1 运行 TypeScript Runtime lint、typecheck、unit、contract、build 和生产镜像非 root/只读/依赖扫描
- [x] 10.2 运行后端 Ruff、format、Mypy、unit/integration、migration、service grant 和敏感日志测试
- [x] 10.3 运行前端 lint、typecheck、unit、production build 和浏览器可访问性/响应式测试
- [x] 10.4 验证至少两个 Agent、两个 Application 和不同 MCP Tool/Resource 子集，不发生 Tool、主体、模型环境或路由串用
- [ ] 10.5 使用真实 TypeScript SDK 验证 Claude/DeepSeek → ONES/DB/Redis/Loki MCP 只读链路、精确 allowlist、取消发布和 Secret 轮换
- [ ] 10.6 验证 `DingTalk Runtime → Inbox → Outbox → RabbitMQ → Python Worker → TypeScript Runtime → MCP → Result → Delivery` 完整真实链路
- [x] 10.7 验证过期 Runtime/MCP Token、模型 401/429/5xx、MCP 401/403、Resource generation failure、Runtime/Worker 重启和 Delivery retry 均失败关闭且审计完整
- [ ] 10.8 扫描数据库、RabbitMQ payload、日志、trace、API、前端产物、Runtime ledger 与 Tool provenance，确认不存在 Key、Token、Secret、连接信息和私有推理
- [x] 10.9 运行 `openspec validate --all --strict`、仓库全量回归和 `git diff --check`，记录版本、告警、剩余风险和最终验收证据
- [ ] 10.10 只有用户明确确认 TypeScript 运行时、Publication 前端和完整真实链路验收通过后，才允许关闭生产门禁并归档变更
