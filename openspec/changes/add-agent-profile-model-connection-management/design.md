## Context

现有 `agent_definition`、`agent_revision`、`agent_publication` 和 `/api/admin/agents` 已经支持默认诊断 Agent 的草稿、校验、发布、Effective Config、历史和回滚，但管理 Web 没有 Agent Profile 页面。Agent 草稿的 `model_policy` 目前只保存模型名，并明确拒绝 `api_key`、`base_url` 等安全字段。

真实 Runtime 在 Container 启动时从 DB-backed runtime config/env 读取一组全局 Claude/DeepSeek 配置并构造单例 `RealClaudeCodeAgentClient`。Agent Publication 可以在每个 Job 中固定模型名，但 Base URL、Key、默认模型映射和 effort 仍由 Worker 进程全局决定，Web 更新配置后需要重启，而且多个 Agent Profile 无法选择不同连接。

本变更只服务当前 Claude Agent SDK 的 Anthropic-compatible DeepSeek 连接。当前配置中的 `ANTHROPIC_API_KEY` 与 `ANTHROPIC_AUTH_TOKEN` 是同一凭据，五个默认/子 Agent 模型均为同一模型。用户已在需求对话中提供现有 Key，因此该值视为已暴露；任何实现、测试和迁移不得复制该明文，验收前必须轮换。

必须保留以下边界：

- 第一版只编辑 `default-diagnostic-agent`，底层多 Agent 数据模型不变。
- Business Application Publication 继续固定 Agent Publication；发布 Profile 不自动切换路由。
- Job、retry 和 Worker 继续使用固定 Publication，不从 MQ payload 接收配置或 Secret。
- Claude Agent SDK、只读内部 MCP Tool、现有 Execution Policy 和失败 Delivery 不改变。
- Secret 明文不进入 Agent 草稿、Publication、日志、审计、API 查询或前端状态。

## Goals / Non-Goals

**Goals:**

- 接通 Agent Profile Web 菜单和现有草稿/校验/发布/回滚 API。
- 在 Profile 页面安全管理当前 Anthropic-compatible URL、Key、模型映射和 effort。
- 用可版本化模型连接 revision 作为 Agent Publication 的非敏感依赖。
- Worker 按 Job 固定的 Agent Publication 解析连接和 Secret。
- 让 URL/模型变更需要新 Publication，让同一 Credential 的 Key 轮换立即安全生效。
- 对真实连接测试实施 RBAC、SSRF 防护、审计和内容最小化。

**Non-Goals:**

- 不实现 OpenAI-compatible、Gemini、Ollama 或其他 Runtime Adapter。
- 不实现新建、复制、删除 Agent Profile。
- 不修改 API Capability、API Platform、Channel、Workflow、业务应用编排或 Tool。
- 不自动更新或激活 Business Application。
- 不提供 Secret 明文读取、下载、复制或回显。
- 不把模型连接配置放进 MQ 消息或 Agent prompt。

## Decisions

### 1. 增加独立模型连接聚合，页面嵌入Profile但领域不混合

新增稳定的 `model_connection` 和追加式 `model_connection_revision`：

```text
model_connection
  id
  code
  name
  protocol = anthropic_compatible
  current_revision_id
  status
  revision
  created_by / created_at / updated_at

model_connection_revision
  id
  connection_id
  revision
  status
  config_json
  config_hash
  api_key_secret_id
  created_by / created_at
```

`config_json` 只保存非敏感字段：

```json
{
  "schema_version": 1,
  "protocol": "anthropic_compatible",
  "base_url": "https://provider.example/anthropic",
  "model": "model-name",
  "default_opus_model": "model-name",
  "default_sonnet_model": "model-name",
  "default_haiku_model": "model-name",
  "subagent_model": "model-name",
  "effort_level": "max"
}
```

页面把模型连接编辑器放在 Agent Profile 的“模型与连接”标签中，但后端使用独立 application service、repository 和权限边界。这样既满足单页配置体验，也避免把 Credential 生命周期塞进 Agent Publication。

不直接复用 `platform_runtime_config_value` 作为 Agent Profile 连接，因为它是按服务和环境解析的可变全局配置，不能表达 Job 固定的 Profile 依赖。现有 runtime config 保留为旧 Publication 兼容来源。

### 2. 一个Credential同时提供API Key和Auth Token

模型连接 revision 只绑定一个 encrypted DB Secret ID。Worker 解析一次后，同时设置当前 SDK session 所需的 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_AUTH_TOKEN`。UI 只提供一个 Key 输入/轮换动作，避免两个值漂移。

Secret API 继续只返回：

```text
configured
masked_summary
active_version
updated_at
```

公开的 Agent/Profile/Publication 投影不返回 Secret ID、Secret ref 或密文。运行时 repository 使用内部模型读取绑定。

选择 Secret ID 而不是把 Secret ref 复制到 Publication，是因为前端和审计无需知道内部 URI，且现有 encrypted DB Secret 可以通过稳定 ID 轮换 active version。

### 3. Agent Publication固定模型连接revision

Agent 草稿的规范化 `model_policy` 改为：

```json
{
  "runtime": "claude_agent_sdk",
  "model": "model-name",
  "model_connection_revision_id": "model_connection_revision_x"
}
```

发布时 `AgentConfigService` 必须：

1. 读取指定连接 revision；
2. 验证 protocol、URL、模型字段、hash、状态和 Credential configured 状态；
3. 把连接 ID、revision ID、revision、config hash 和完整非敏感有效配置复制到 Agent Publication snapshot；
4. 只保存内部 Credential binding ID，不保存 Key；
5. 生成包含上述固定数据的 Agent config hash。

运行记录和管理 API 使用公共 sanitizer 隐藏 Credential binding，仅保留 `credential_configured=true`。

URL、模型映射或 effort 改动会创建新的连接 revision，并要求新 Agent Publication。Key 轮换只改变同一 Credential 的 active version，因此无需重写历史 Publication；这是为了允许泄露或失效密钥立即吊销，而不是让旧 Job 永久使用泄露值。

### 4. Worker按Job构建ModelRuntimeBinding

新增不进入 Prompt 的 `ModelRuntimeBinding`：

```text
protocol
provider_host
base_url
model
default_opus_model
default_sonnet_model
default_haiku_model
subagent_model
effort_level
credential_binding_id
connection_revision_id
connection_config_hash
```

`AgentContextBuilder` 校验 Job 固定 Agent Publication 后构造非敏感 binding；Worker/Runtime 基础设施在 attempt 开始时通过内部 SecretResolver 解析 active Key。`RealClaudeCodeAgentClient` 不再把启动时的全局 URL/Key作为新 Publication 的权威值。

当前 Claude Agent SDK 通过进程环境把 Provider 配置传给 CLI。为防止未来同一进程并发 Job 串用环境，SDK session 的环境设置、CLI 启动和恢复必须处于进程级互斥区，或改为向 SDK 子进程显式传入独立 env；测试必须覆盖不同连接的并发/交错执行。不能只创建多个 client 实例而继续无保护地修改 `os.environ`。

### 5. 规范字段确定性映射到现有环境变量

运行时映射如下：

```text
base_url             -> ANTHROPIC_BASE_URL
一个active Key       -> ANTHROPIC_API_KEY + ANTHROPIC_AUTH_TOKEN
model                -> ANTHROPIC_MODEL + CLAUDE_MODEL
default_opus_model   -> ANTHROPIC_DEFAULT_OPUS_MODEL
default_sonnet_model -> ANTHROPIC_DEFAULT_SONNET_MODEL
default_haiku_model  -> ANTHROPIC_DEFAULT_HAIKU_MODEL
subagent_model       -> CLAUDE_CODE_SUBAGENT_MODEL
effort_level         -> CLAUDE_CODE_EFFORT_LEVEL
```

空的默认模型/Subagent 映射在保存 revision 前统一补成主模型，使 Publication 和运行时看到完全相同的显式值。第一版 protocol 只允许 `anthropic_compatible`，不接受任意环境变量名或额外 CLI 参数。

### 6. 新Publication必填连接，旧Publication显式兼容

迁移不重写现有不可变 Agent Publication，也不自动重发 Business Application。已有 v1 Publication 缺少模型连接时继续使用当前 DB-backed runtime config/env fallback，并在管理端标为 `legacy global connection`。

本变更上线后创建的新 Agent Publication 必须固定连接 revision；缺失时发布失败关闭。这样现有钉钉路由不会在部署瞬间中断，同时所有新版本逐步收敛到可审计连接。

回滚到旧 Publication 会恢复旧的全局连接语义，UI 必须明确显示该差异。后续可以独立变更移除 legacy fallback，本次不做。

### 7. Profile发布不自动改变Business Application

新增只读使用关系查询，根据 Business Application Publication snapshot 中的 Agent Publication ID 返回：

```text
application_code
application_name
business_application_publication_id
deployment_active
deployment_environment
uses_current_agent_publication
```

Profile 发布/回滚事务只修改 Agent 当前发布指针。页面发布成功后若存在活动应用引用旧版本，显示提示和业务应用详情链接，不调用 Business Application 保存、发布、激活或回退 API。

### 8. 连接测试只能使用已保存配置

为避免把明文 Key混入测试请求或日志，连接测试必须先保存/轮换 Secret 和模型连接 revision，然后只提交 revision ID。服务端完成权限、状态、hash、URL和Credential校验后，用同一 Claude Agent SDK 基础设施执行：

```text
无MCP server
无工具
max_turns = 1
短timeout
固定最小探测Prompt
不返回模型正文
```

测试 URL 必须：

- 使用 HTTPS；
- host 位于部署侧 `MODEL_PROVIDER_HOST_ALLOWLIST`，第一版默认允许 `api.deepseek.com`；
- 不包含 userinfo 或 fragment；
- 禁止跨 host redirect；
- DNS 解析结果不得为回环、链路本地、私网或保留地址。

审计只记录 actor、connection/revision、脱敏 host、model、duration、status、error code 和 correlation ID。

## Risks / Trade-offs

- [用户已粘贴真实Key] → 将其视为泄露，不写入仓库或测试；实施验收前通过 Secret 轮换生成新 active version。
- [保存Web配置但Worker仍使用启动值] → 新 Publication 强制固定连接 revision，Worker按 Job 解析；只有旧 Publication保留全局 fallback。
- [修改全局os.environ导致并发串用Key] → 对完整 SDK session 使用进程级隔离或显式子进程 env，并增加双连接并发测试。
- [连接测试成为SSRF入口] → 只接受已保存 revision、HTTPS、部署 allowlist、DNS/IP 校验、禁重定向和短超时。
- [Key轮换破坏Publication不可变性] → 明确只固定 Credential 身份，不固定 Secret material；安全轮换优先于重放旧泄露凭据。
- [发布Profile后用户以为钉钉立即切换] → 显示 Business Application 使用关系，不自动变更应用，并要求显式重新发布/激活。
- [旧Publication与新Publication行为不同] → 公共投影明确标记 legacy global connection，新发布一律禁止 fallback。
- [Agent与Secret权限混淆] → Profile编辑、发布和Secret管理分别使用现有 RBAC action，前端按服务端权限隐藏动作但后端始终强制校验。

## Migration Plan

1. 增加模型连接定义/revision表、索引和内部 Credential 绑定字段，不改写现有 Agent Publication。
2. 从当前 DB-backed 模型配置创建默认 DeepSeek 模型连接 revision，只复制非敏感值和已有 Secret 绑定，不读取、输出或迁移明文 Key。
3. 若当前 Key 无法安全复用绑定，则把连接标记为“需要轮换”，由 Secret 管理员在 Web 中输入新 Key；不得从对话内容或日志恢复旧值。
4. 部署 Agent/Profile API、Runtime resolver 和管理 Web；旧 Publication继续走现有全局兼容路径。
5. 管理员打开默认 Agent，保存含模型连接的新草稿，执行连接测试并发布新的 Agent Publication。
6. Web 显示仍引用旧 Agent Publication 的业务应用；管理员在业务应用中显式创建草稿、发布并激活 local Deployment。
7. 创建新钉钉 Job，验证 Job 固定 Agent Publication、连接 revision/hash、模型和 Provider Host，运行记录与审计无 Key。
8. 轮换一次测试 Key，证明无需重发 Agent Publication即可使用新 active version，并确认旧版本不再解析。
9. 回滚代码时保留新增表和 Secret；旧 Worker仍使用原 DB-backed runtime config。已引用新 Publication 的业务应用必须先显式回退到旧 Agent Publication，不能直接混跑。

## Open Questions

无。范围固定为默认诊断 Agent、Anthropic-compatible DeepSeek 模型连接、指定变量映射、安全 Secret、Publication 和 Runtime 接线，不增加其他功能。
