# Agent Profile 模型连接运维

## 适用范围

当前管理面可以创建和治理多个 `python-v1` Agent；`default-diagnostic-agent` 是本地
bootstrap 内置项，不是唯一可管理 Agent。运行时只支持 Python Claude Agent SDK 使用
Anthropic-compatible 协议。默认模型连接为 `default-deepseek-anthropic`。模型连接独立
于 Agent、MCP Tool、Channel 和 Workflow。

## 配置与凭据边界

模型连接 revision 保存以下非敏感配置：

- Provider Base URL
- 主模型及 Opus、Sonnet、Haiku、Subagent 模型映射
- effort level
- 配置 hash 和 revision

API Key 通过独立的凭据轮换接口写入 encrypted DB Secret。查询、审计、
Agent Publication、Job provenance 和前端状态不返回 Secret ID、Secret ref
或明文。API Key 与 Auth Token 在每次 SDK attempt 开始时解析同一 active
Secret version。

默认连接首次迁移时只复用已有 encrypted Secret 的内部绑定，不恢复或输出
明文，并保持 `rotation_required`。管理员必须先在 Web 输入一个已经在
Provider 侧轮换的新 Key，连接才会变为 `ready`。

## 发布语义

新 Agent Publication 固定模型连接 ID、revision ID、revision、配置 hash 和
非敏感有效配置。修改 URL、模型映射或 effort 后，必须：

1. 保存新的模型连接 revision；
2. 保存并校验 Agent 草稿；
3. 发布新的 Agent Publication。

仅轮换同一连接的 Key 不需要重发 Agent Publication。后续 Job 和 retry 会在
每个 attempt 开始时解析新的 active Secret version。

历史 Agent Publication 不可修改。代码仍能只读解释迁移前缺少模型连接的
`legacy_global_connection` Publication，并从旧全局配置读取；该分支只用于已有历史
快照，不是新 Agent/Publication 可选择的配置。

## 业务应用不会自动切换

发布或回滚 Agent Profile 只改变 Agent 的当前 Publication 指针，不修改任何
Business Application 草稿、Publication 或 local Deployment。已激活业务应用
继续使用其快照固定的旧 Agent Publication。

切换顺序为：

1. 在 Agent Profile 发布并验证新 Agent Publication；
2. 进入业务应用详情，显式选择该 Agent Publication；
3. 保存、发布业务应用；
4. 激活 local Deployment；
5. 通过运行记录核对业务应用、Agent 和模型连接 provenance。

## 回滚顺序

模型配置异常时，优先把业务应用回退到上一个已验证的 Business Application
Publication。若需要回退 Agent Profile，只改变 Agent 当前指针，不会自动改变
已激活应用。若 Key 泄露或失效，应在 Provider 侧撤销旧 Key，并通过模型连接
页面轮换凭据；不要通过回滚恢复旧 Key。

## 运行记录

运行记录只保存：

- model 与 effort
- model connection revision ID/revision/hash
- Provider Host
- 是否使用 legacy fallback

运行记录不保存 Key、Secret ref、Prompt 或模型响应正文。连接测试使用已保存
revision，执行无 MCP、无 Tool、单轮、短超时的最小探测，并只返回 Host、模型、
耗时和安全错误摘要。
