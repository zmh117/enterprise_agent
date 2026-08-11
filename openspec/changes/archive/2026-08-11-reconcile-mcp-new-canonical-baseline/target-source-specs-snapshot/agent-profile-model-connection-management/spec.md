# agent-profile-model-connection-management Specification

## Purpose
TBD - created by archiving change add-agent-profile-model-connection-management. Update Purpose after archive.
## Requirements
### Requirement: Web必须提供默认Agent Profile管理入口
系统 SHALL 在管理 Web 增加“Agent 配置 / Agent Profile”菜单、Profile 列表和详情页，并 MUST 使用真实管理 API 展示草稿、当前 Publication、Effective Config、校验结果和 Publication 历史。第一版 MUST 只允许编辑现有 `default-diagnostic-agent`，MUST NOT 提供新建、复制或删除 Agent Profile。

#### Scenario: 管理员打开Agent Profile列表
- **WHEN** 具备 Agent 读取权限的管理员打开 Agent Profile 菜单
- **THEN** 页面从后端加载 Agent 定义、当前 Publication 和管理模式
- **AND** 默认诊断 Agent 显示为可编辑，其他 Agent 显示为只读

#### Scenario: 管理员尝试修改非默认Agent
- **WHEN** 管理员打开非 `default-diagnostic-agent` 的详情
- **THEN** 页面不展示可提交的保存、发布或回滚动作
- **AND** 后端继续拒绝该 Agent 的写请求

### Requirement: Agent Profile必须管理限定的Anthropic-compatible模型配置
系统 SHALL 允许默认 Agent Profile 配置一个 `anthropic_compatible` 模型连接，并 SHALL 以规范化字段管理 Base URL、主模型、Opus/Sonnet/Haiku 默认模型、Subagent 模型和 effort level。系统 MUST 将一个 API Key Credential 同时映射为运行时所需的 `ANTHROPIC_API_KEY` 与 `ANTHROPIC_AUTH_TOKEN`，MUST NOT 要求用户重复保存相同密钥。

#### Scenario: 配置DeepSeek Anthropic-compatible连接
- **WHEN** 管理员配置 HTTPS Anthropic Base URL、`deepseek-v4-flash` 主模型、默认模型映射、Subagent 模型和 `max` effort
- **THEN** 草稿保存规范化模型连接引用和模型策略
- **AND** Effective Config 能展示非敏感字段及 Key 已配置状态

#### Scenario: 默认模型映射留空
- **WHEN** 管理员只填写主模型并将 Opus、Sonnet、Haiku 或 Subagent 映射留空
- **THEN** 系统在校验和发布时确定性使用主模型补齐空映射
- **AND** Publication 保存补齐后的显式有效值

#### Scenario: 尝试配置不支持的协议
- **WHEN** 请求提交 OpenAI-compatible、任意 HTTP Runtime 或其他未支持 Provider
- **THEN** 系统以字段级错误拒绝保存或发布
- **AND** 不创建新的 Runtime Adapter 或模型连接

### Requirement: 模型API Key必须通过加密Secret管理
系统 MUST 使用现有 encrypted DB Secret Provider 加密保存模型 API Key，API Key 明文 MUST 只在创建或轮换请求中进入服务端，并 MUST NOT 出现在 Agent 草稿、Agent Publication、模型连接查询、日志、审计、错误响应、前端状态或 Agent prompt。页面 SHALL 只展示 configured 状态、脱敏摘要、版本和更新时间。

#### Scenario: 管理员首次保存API Key
- **WHEN** 具备 Secret 管理权限的管理员提交新的模型 API Key
- **THEN** 系统加密保存该值并把稳定 Credential 绑定到模型连接
- **AND** 响应不包含明文、可还原密文或可复制的 Secret URI

#### Scenario: 普通Agent编辑者查看模型连接
- **WHEN** 具有 Agent 编辑权限但不具有 Secret 管理权限的用户打开 Agent Profile
- **THEN** 页面只显示 Key 是否已配置及脱敏状态
- **AND** 用户不能读取、创建、替换、轮换或禁用 Key

#### Scenario: 轮换已暴露Key
- **WHEN** Secret 管理员为同一 Credential 提交新 Key
- **THEN** 系统创建新的 active Secret 版本并停用旧版本
- **AND** 既有 Agent Publication 无需改变即可在后续 attempt 使用新版本

### Requirement: Agent Publication必须固定非敏感模型连接版本
系统 MUST 在发布 Agent Profile 时加载并校验所选模型连接 revision，把连接 ID、revision、config hash、协议、Base URL、有效模型映射和 effort 固定到不可变 Agent Publication，同时只保存稳定 Credential 绑定标识而不保存 Key 明文。新 Agent Publication MUST 不受后续模型 URL、模型映射或 effort 编辑影响。

#### Scenario: 发布合法Agent草稿
- **WHEN** Agent 草稿引用已启用、已配置 Key 且通过连接校验的模型连接 revision
- **THEN** 系统创建包含完整非敏感模型连接快照和 config hash 的 Agent Publication
- **AND** Effective Config 显示该 Publication 的模型连接来源

#### Scenario: 发布后修改模型URL
- **WHEN** 管理员在 Agent Publication 创建后修改模型 Base URL
- **THEN** 现有 Publication 保持原 URL、revision 和 hash
- **AND** 只有重新保存并发布的新 Agent Publication 使用新 URL

#### Scenario: 模型连接缺少Key
- **WHEN** Agent 草稿引用的模型连接没有启用的 active Credential
- **THEN** 校验和发布失败关闭并返回安全字段错误
- **AND** 响应不披露 Credential ID、Secret ref 或内部解密错误

### Requirement: Agent Profile发布不得自动切换业务应用
系统 MUST 保持 Business Application Publication 对 Agent Publication 的不可变引用。发布或回滚 Agent Profile MUST NOT 自动修改任何 Business Application revision、Publication、Deployment 或运行路由；管理 Web SHALL 显示引用当前和历史 Agent Publication 的业务应用，并为仍引用旧版本的应用提供明确提示。

#### Scenario: 默认应用仍引用旧Publication
- **WHEN** 管理员发布新的 Agent Publication，而已激活默认诊断应用仍引用旧 Agent Publication
- **THEN** 当前钉钉路由继续使用旧 Agent Publication
- **AND** Agent Profile 页面显示受影响应用及“需要在业务应用中显式发布并激活”的提示

#### Scenario: 回滚Agent当前Publication
- **WHEN** 管理员把 Agent 当前指针回滚到历史 Publication
- **THEN** 未经 Business Application 路由创建的后续 Job 使用回滚版本
- **AND** 已发布业务应用及已入队 Job 保持各自固定版本

### Requirement: 模型连接测试必须使用真实受限Runtime并防止SSRF
系统 SHALL 提供模型连接测试动作，测试 MUST 使用保存后的模型连接和 active Secret，通过与生产 Job 相同的 Claude Agent SDK 兼容路径执行无工具、单轮、短超时探测。系统 MUST 只允许 HTTPS 和部署侧 Provider host allowlist，禁止 URL userinfo、fragment、未批准重定向、回环、链路本地和私有目标，并 MUST 返回 Provider Host、模型、耗时和安全结果，不返回 Key、Prompt、模型响应正文或内部异常详情。

#### Scenario: 测试已保存DeepSeek连接
- **WHEN** Secret 管理员测试已保存且 host 被允许的 DeepSeek Anthropic-compatible连接
- **THEN** 系统使用 active Key 完成受限 SDK 探测并返回成功状态和耗时
- **AND** 测试不调用任何内部 MCP 工具

#### Scenario: 测试未批准URL
- **WHEN** 管理员提交回环、私网、HTTP、带 userinfo 或 host 不在 allowlist 的 Base URL
- **THEN** 系统在发起网络请求前拒绝连接
- **AND** 审计只记录脱敏 host、actor、结果和 correlation ID

### Requirement: Agent Profile模型连接操作必须授权和审计
系统 SHALL 复用统一 RBAC：读取 Profile 需要 Agent read/edit 权限，保存草稿需要 Agent edit 权限，发布和回滚需要 Agent publish 权限，创建或轮换 Key 及执行真实连接测试需要 Secret 管理权限。所有写操作和连接测试 MUST 记录不含敏感值的审计事件。

#### Scenario: 无Secret权限的用户更新Key
- **WHEN** 仅具有 Agent edit 权限的用户提交 Key 创建、轮换或连接测试请求
- **THEN** 系统拒绝请求且不访问外部模型服务

#### Scenario: 发布审计
- **WHEN** 管理员发布包含模型连接的 Agent Publication
- **THEN** 审计记录 Agent code、Publication ID、模型连接 revision、config hash、模型和脱敏 Provider Host
- **AND** 审计不包含 Key、Secret ref、Prompt 或模型响应
