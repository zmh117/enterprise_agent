## 1. 模型连接领域与持久化

- [x] 1.1 新增下一顺序 migration，创建 `model_connection`、`model_connection_revision`、唯一约束、revision/hash 索引和内部 Secret 绑定字段
- [x] 1.2 新增 `ModelConnectionConfig` 值对象，严格规范化 `anthropic_compatible`、HTTPS Base URL、主模型、默认模型、Subagent 模型和 effort
- [x] 1.3 实现空 Opus/Sonnet/Haiku/Subagent 映射确定性继承主模型，并拒绝未知字段、未知协议、空模型和非法 effort
- [x] 1.4 实现模型 Provider URL 安全策略，校验部署 allowlist、HTTPS、userinfo、fragment、redirect、DNS 和回环/私网/链路本地/保留地址
- [x] 1.5 实现 `ModelConnectionRepository` 的定义、追加式 revision、乐观并发、状态、hash 校验和 runtime/public 双投影
- [x] 1.6 实现 `ModelConnectionService` 的列表、详情、保存 revision、启用/禁用和读取固定 revision
- [x] 1.7 复用 encrypted DB Secret Provider 创建和轮换一个模型 Credential，确保同一值供 API Key 与 Auth Token 使用且查询不返回 Secret ID/ref
- [x] 1.8 增加模型连接领域、仓储和 Secret 单元测试，覆盖默认映射、revision 冲突、hash 不一致、Key 缺失、轮换和脱敏

## 2. Agent Profile草稿与Publication

- [x] 2.1 扩展 Agent 草稿 `model_policy` schema，仅接受 `runtime=claude_agent_sdk`、模型名和 `model_connection_revision_id`
- [x] 2.2 扩展 Agent 草稿规范化与字段级校验，验证模型连接状态、revision/hash、Credential configured 和管理员权限
- [x] 2.3 修改 Agent 发布服务，在 Agent Publication 中固定连接 ID/revision/hash、协议、Base URL、有效模型映射、effort 和内部 Credential binding
- [x] 2.4 增加 Agent Publication runtime/public sanitizer，公共 API、Effective Config、审计和日志不得返回 Credential ID/ref
- [x] 2.5 规定上线后新 Agent Publication 必须包含合法模型连接，缺失时失败关闭；现有旧 Publication 标记为 `legacy_global_connection`
- [x] 2.6 扩展 Agent Profile 查询，返回当前草稿、当前 Publication、模型连接公共状态、Effective Config 和 `management_mode`
- [x] 2.7 新增 Agent Publication 使用关系查询，只读返回引用它的 Business Application Publication、活动 local Deployment 和是否仍使用旧版本
- [x] 2.8 保持 publish/rollback 不调用 Business Application 保存、发布、激活或回退服务，并增加事务边界测试
- [x] 2.9 增加 Agent Profile API 契约测试，覆盖默认 Agent 可编辑、其他 Agent 只读、草稿冲突、校验、发布、历史、Effective Config 和回滚
- [x] 2.10 增加 Publication 不可变与使用关系测试，证明连接变更不修改旧 Publication，业务应用和已入队 Job 不自动切换

## 3. 按Job固定模型连接的Runtime

- [x] 3.1 新增不进入 Prompt 的 `ModelRuntimeBinding`，包含非敏感模型连接 provenance 和内部 Credential binding
- [x] 3.2 修改 `AgentContextBuilder`，从 Job 固定 Agent Publication 构造并校验新模型连接 binding，不读取 Agent 当前指针
- [x] 3.3 新增 Worker 内部模型 Credential resolver，在每个 attempt 开始时解析同一 Credential 的 active Secret 版本
- [x] 3.4 重构 `RealClaudeCodeAgentClient`，让新 Publication 的 URL、模型映射、Subagent 模型、effort 和 Key 来自 `ModelRuntimeBinding` 而非启动单例配置
- [x] 3.5 将规范字段准确映射到 `ANTHROPIC_BASE_URL`、API Key/Auth Token、主模型、三类默认模型、Subagent 模型和 effort 环境
- [x] 3.6 对完整 Claude Agent SDK session 实现进程级环境隔离或显式子进程 env，确保不同连接的串行和并发 Job 不串用配置
- [x] 3.7 保留迁移前 Publication 的 DB-backed runtime config/env fallback，并在新 Publication 路径禁止 fallback
- [x] 3.8 在模型连接 hash 不一致、Credential 缺失/禁用或 URL 不合法时，于调用 SDK、CLI、模型和 Tool 前不可重试地失败关闭
- [x] 3.9 扩展 Job/运行记录安全 provenance，返回模型、effort、连接 revision/hash 和 Provider Host，不保存 Key、Secret ref、Prompt 或模型正文
- [x] 3.10 增加 Runtime fake SDK 测试，覆盖固定连接、排队后新发布、retry复用、Key轮换、旧 Publication fallback、hash错误和禁用Key
- [x] 3.11 增加双模型连接交错/并发测试，证明 Base URL、模型映射、effort 和 Key 环境在 Job 之间完全隔离

## 4. 模型连接管理API与安全测试

- [x] 4.1 新增 `/api/admin/model-connections` 列表、详情和保存 revision API，使用严格 Pydantic schema 并拒绝额外字段
- [x] 4.2 新增独立 Key 创建/轮换 API，请求允许一次明文输入，响应只返回 configured、masked summary、active version 和更新时间
- [x] 4.3 新增模型连接测试 API，只接受已保存 revision ID，不接受临时 URL、临时 Key、任意环境变量或 Prompt
- [x] 4.4 实现无 MCP、无 Tool、单轮、短超时的真实 Claude Agent SDK 连接探测，不返回模型响应正文
- [x] 4.5 为 Profile读取、草稿编辑、发布/回滚、Secret写入和真实连接测试分别接入现有 RBAC并补充拒绝测试
- [x] 4.6 为模型连接保存、Secret轮换、连接测试和 Agent发布增加安全审计，记录脱敏 host、revision/hash、模型、耗时和稳定错误码
- [x] 4.7 增加 API 安全测试，覆盖 HTTP、userinfo、fragment、redirect、未批准host、DNS私网结果、超时、认证失败和响应脱敏
- [x] 4.8 全仓搜索并增加回归断言，确保用户提供的旧 Key 和任何测试 Key 不进入 OpenSpec 之外的源码、fixture、快照、日志、审计或 Git diff

## 5. Agent Profile管理Web

- [x] 5.1 在前端新增 `contexts/agent-profiles/{domain,application,infrastructure,presentation}` bounded context，不复用静态 Dashboard mock
- [x] 5.2 增加“Agent 配置 / Agent Profile”侧栏菜单、`/agent-profiles` 列表路由和 `/agent-profiles/:code` 详情路由
- [x] 5.3 实现 Profile 列表，展示名称、code、管理模式、当前 Publication、模型连接状态和引用应用数量
- [x] 5.4 实现默认 Profile 详情的基本信息、模型与连接、行为指令、执行策略、Tool与Skill、校验结果和Publication历史标签
- [x] 5.5 实现模型连接表单，显示 Base URL、主模型、默认模型映射、Subagent模型、effort和Key配置状态，不显示Secret ID/ref
- [x] 5.6 实现 Key首次配置和轮换对话框，输入框不预填、不缓存、不回显，保存成功后清空本地表单状态
- [x] 5.7 接通保存草稿、校验、发布、Effective Config、Publication历史和回滚，并使用 expected revision 处理并发冲突
- [x] 5.8 实现真实连接测试按钮及 loading/success/failure 状态，只展示 Provider Host、模型、耗时和安全错误摘要
- [x] 5.9 发布成功后展示仍引用旧 Agent Publication 的业务应用和详情链接，不提供自动切换、发布或激活动作
- [x] 5.10 对非默认 Agent、无 Secret 权限和无 publish 权限用户显示只读状态，且不以仅隐藏按钮代替后端授权
- [x] 5.11 增加前端 schema、页面和交互测试，覆盖加载、草稿、映射继承、Key脱敏/轮换、连接测试、发布、引用提示、回滚、权限和窄屏

## 6. 迁移与端到端验证

- [x] 6.1 从现有 DB-backed DeepSeek 配置创建默认模型连接 revision，只复制非敏感字段和已有 Secret 绑定，不读取或输出 Key 明文
- [x] 6.2 若无法复用安全 Secret 绑定，将默认连接标记为需要轮换并在 Web 阻止发布，不从环境、日志、对话或历史审计恢复旧Key
- [x] 6.3 更新运维文档，说明旧 Publication global fallback、新 Publication固定连接、Key轮换语义、业务应用显式切换和回滚顺序
- [x] 6.4 轮换用户已暴露的现有 Key，确认旧 Secret version不再解析，仓库和运行输出均无该明文
- [x] 6.5 运行完整后端测试，覆盖Agent配置、Publication、Job/Worker、真实Claude client、Secret、RBAC、审计、Business Application固定引用和失败Delivery
- [x] 6.6 运行前端lint、typecheck、全量测试和生产构建，修复所有新增契约和可访问性问题
- [x] 6.7 以同一提交重建api-server、agent-worker、dingtalk-stream-ingress和admin-web，验证没有新旧Runtime混跑
- [x] 6.8 在Web配置并测试轮换后的DeepSeek Anthropic-compatible连接，保存默认Agent草稿、校验并发布新Agent Publication
- [x] 6.9 验证默认业务应用仍使用旧Agent Publication且钉钉Job行为不变，再显式选择新Publication、发布并激活local Deployment
- [x] 6.10 创建真实钉钉Job，核对Agent/Business Application Publication、模型连接revision/hash、模型、Provider Host、工具执行和原会话Delivery
- [x] 6.11 再轮换一次测试Key但不重发Publication，验证后续Job使用新active version且不泄漏Key
- [x] 6.12 验证未增加OpenAI Runtime、其他Provider、多Agent创建、API Capability、Channel、Workflow或自动业务应用切换功能
- [x] 6.13 运行 `openspec validate add-agent-profile-model-connection-management --strict` 并保存最终验证结果
