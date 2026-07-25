## Why

Agent Profile 的草稿、校验和 Publication 后端能力已经存在，但 Web 没有可操作菜单；模型 URL、Key 和默认模型仍是 Worker 启动时读取的全局运行配置，无法随 Agent Publication 固定，也无法在管理界面中安全配置。当前默认诊断 Agent 使用 Anthropic-compatible DeepSeek 接口，因此需要把这一组模型连接配置纳入 Agent Profile 的受控发布链。

## What Changes

- 在管理 Web 增加“Agent 配置 / Agent Profile”菜单、列表和默认诊断 Agent 详情页。
- 第一版只允许编辑现有 `default-diagnostic-agent`，不增加新建、删除或复制 Agent Profile。
- Agent Profile 页面接通现有草稿、字段校验、发布、Effective Config、Publication 历史和回滚能力。
- 增加 Anthropic-compatible 模型连接配置，仅支持当前 Claude Agent SDK 运行方式；配置范围严格限定为：
  - `ANTHROPIC_BASE_URL`
  - `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` 的同一凭据
  - `ANTHROPIC_MODEL` / `CLAUDE_MODEL`
  - `ANTHROPIC_DEFAULT_OPUS_MODEL`
  - `ANTHROPIC_DEFAULT_SONNET_MODEL`
  - `ANTHROPIC_DEFAULT_HAIKU_MODEL`
  - `CLAUDE_CODE_SUBAGENT_MODEL`
  - `CLAUDE_CODE_EFFORT_LEVEL`
- API Key 明文只在创建或轮换请求中出现，使用现有 encrypted DB Secret Provider 加密保存；页面和查询 API 只显示是否已配置、脱敏摘要、版本和更新时间。
- Agent Publication 固定模型 URL、模型映射、effort、Credential 引用和配置 hash，绝不保存 API Key 明文。
- Worker 按 Job 已固定的 Agent Publication 解析模型连接和当前有效 Secret 版本，不再让新 Publication 依赖进程启动时的单一全局 URL、模型和 Key。
- 模型 URL、模型映射或 effort 变更必须创建新 Agent Publication；同一 Credential 的 Key 轮换不修改历史 Publication。
- 发布 Agent Profile 后不自动改写或激活 Business Application；Web 明确显示仍引用旧 Agent Publication 的应用，并引导管理员在业务应用中显式选择新 Publication。
- 提供使用真实 Claude Agent SDK 执行的受限连接测试，返回 Provider Host、模型、耗时和安全结果，不返回请求正文、响应正文、Key 或内部异常细节。
- 对 URL、重定向、协议、超时和访问主机执行服务端校验，避免任意 URL 探测和 SSRF。
- 用户在本次需求中提供的现有 Key 视为已暴露凭据；实施和验收使用轮换后的新版本，任何规划产物、代码、测试数据、日志和 Git 历史都不得写入该明文。
- 不增加 OpenAI-compatible Runtime Adapter、其他模型 Provider、API Capability、Channel、Workflow、多 Agent 创建、自动切换业务应用或其他管理功能。

## Capabilities

### New Capabilities

- `agent-profile-model-connection-management`: 规定默认 Agent Profile 的 Web 管理、Anthropic-compatible 模型连接、Secret 绑定、不可变 Publication、连接测试和发布使用关系。

### Modified Capabilities

- `claude-agent-runtime-integration`: 真实 Claude Agent SDK Runtime 从 Job 固定的 Agent Publication 解析模型 URL、模型映射、effort 和 Credential，而不是只使用 Worker 启动时的全局模型连接。

## Impact

- 管理 Web：新增 `agent-profiles` 前端 bounded context、菜单、列表、详情、模型连接表单和 Publication 历史。
- 后端 Agent 配置：扩展草稿 schema、校验、Publication snapshot、Effective Config、使用关系和回滚展示。
- 模型连接与 Secret：增加非敏感模型连接持久化及其 encrypted DB Secret 绑定，复用现有 Secret 轮换和脱敏能力。
- Agent Runtime：增加按固定 Publication 解析模型连接的应用端口和基础设施适配，保持 Claude Agent SDK、只读 MCP 工具和现有 Job/Retry 边界不变。
- Business Application：仅增加 Agent Publication 使用关系查询和界面提示，不自动修改现有 Application Publication 或 Deployment。
- 迁移：保留现有全局 DB-backed 模型配置作为旧 Publication 的兼容来源；新 Publication 必须使用新模型连接快照。
