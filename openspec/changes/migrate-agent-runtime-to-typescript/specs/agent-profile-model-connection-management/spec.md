## ADDED Requirements

### Requirement: Web 必须提供多 Agent Publication 管理入口
系统 SHALL 在认证 Web 提供 Agent 列表与详情，使用真实管理 API 展示 Definition、Draft、校验结果、当前/历史 Publication、有效模型连接、MCP Tool 最大集合和引用 Application。页面 MUST 根据 RBAC 控制创建、保存、校验、发布、回退、停用和归档动作。

#### Scenario: 管理员打开 Agent 列表
- **WHEN** 具备 Agent read 权限的管理员进入 Agent 管理页
- **THEN** 页面只加载其可见 Agent、当前 Publication、Runtime version 和活动 Application 摘要

#### Scenario: 管理员编辑第二个 Agent
- **WHEN** 用户对目标 Agent 具有 edit/publish 权限
- **THEN** 页面允许按 expected revision 保存和发布，而不是限制为默认 Agent

## MODIFIED Requirements

### Requirement: Agent Profile必须管理限定的Anthropic-compatible模型配置
系统 SHALL 允许每个可编辑 Agent Profile 选择一个已注册 `anthropic_compatible` 模型连接，并 SHALL 以规范化字段管理 Base URL、主模型、默认模型、Subagent 模型和 effort。模型连接 MUST 由独立对象/version 管理；Agent Draft 只能引用 revision，不能提交自由 Provider URL、Runtime adapter 或 Key。

#### Scenario: 配置DeepSeek Anthropic-compatible连接
- **WHEN** 管理员选择一个已验证的 DeepSeek Anthropic-compatible 模型连接 revision
- **THEN** Draft 保存连接引用和模型策略，Effective Config 只展示非敏感字段及 Key configured 状态

#### Scenario: 默认模型映射留空
- **WHEN** 模型连接只填写主模型并将默认映射留空
- **THEN** 连接校验和 Publication 确定性补齐显式有效值

#### Scenario: 尝试配置不支持的协议
- **WHEN** 请求提交目录外协议、任意 HTTP Runtime 或自由 Base URL
- **THEN** 系统以字段级错误拒绝且不创建 Runtime Adapter

### Requirement: 模型API Key必须通过加密Secret管理
系统 MUST 使用 encrypted DB Secret Provider 加密保存模型 API Key；明文 MUST 只在创建/轮换请求及 TypeScript Runtime 单次内存解析中存在，并 MUST NOT 出现在 Agent/Application Draft或Publication、RabbitMQ、执行协议事件、查询、日志、审计、错误、前端或 Prompt。页面 SHALL 只显示 configured、版本和更新时间。

#### Scenario: 管理员首次保存API Key
- **WHEN** Secret 管理员提交新的模型 API Key
- **THEN** API 加密保存并绑定稳定 Credential，响应不包含明文、密文或可复制 Secret URI

#### Scenario: 普通Agent编辑者查看模型连接
- **WHEN** 用户有 Agent edit 但无 Secret 管理权限
- **THEN** 页面只显示 Key 状态，不能读取、创建、轮换、测试或禁用 Key

#### Scenario: Runtime解析Key
- **WHEN** TypeScript Runtime 执行固定模型连接的 attempt
- **THEN** Runtime 使用只读 Master Key 文件和最小数据库权限解析 active version，Key 不返回 Python Worker

### Requirement: Agent Publication必须固定非敏感模型连接版本
系统 MUST 在发布 Agent Profile 时校验所选模型连接 revision，并把连接 ID、revision、config hash、协议、Base URL、有效模型映射、effort、Runtime contract version 和稳定 Credential 绑定标识固定到不可变 Agent Publication；Publication MUST 不保存 Key 或受后续非凭据编辑影响。

#### Scenario: 发布合法Agent草稿
- **WHEN** Draft 引用 enabled、Key configured 且已验证的模型连接 revision
- **THEN** 系统创建包含完整非敏感模型快照、config hash 和 TypeScript Runtime version 的 Publication

#### Scenario: 发布后修改模型URL
- **WHEN** 管理员产生新的模型连接 revision
- **THEN** 既有 Agent Publication 保持原配置，只有新 Agent Publication 可采用新 revision

#### Scenario: 模型连接缺少Key
- **WHEN** Draft 引用没有 active Credential 的模型连接
- **THEN** 校验和发布失败关闭且不披露 Credential/Secret 内部标识

### Requirement: Agent Profile发布不得自动切换业务应用
系统 MUST 保持 Business Application Publication 对 Agent Publication 的不可变引用。发布、回退、停用 Agent MUST NOT 自动修改任何 Application revision、Publication、Deployment 或路由；Web SHALL 显示引用关系和显式升级提示。

#### Scenario: 应用仍引用旧Publication
- **WHEN** 管理员发布新的 Agent Publication，而活动应用仍引用旧版本
- **THEN** 当前路由继续使用旧版本，Agent 页面提示必须在应用中显式发布并激活

#### Scenario: 停用被活动应用引用的Agent
- **WHEN** 管理员尝试停用仍被活动 Deployment 使用的 Agent/Publication
- **THEN** 系统拒绝无保护操作并返回安全引用摘要

### Requirement: 模型连接测试必须使用真实受限Runtime并防止SSRF
系统 SHALL 通过 TypeScript Agent Runtime 提供模型连接测试；测试 MUST 使用保存后的 revision 和 active Secret，执行无 MCP Tool、单轮、短超时合成探测。API 与 Runtime MUST 校验 HTTPS、Provider host allowlist、重定向和 DNS/IP 边界，并只返回 host、模型、SDK version、耗时与安全结果。

#### Scenario: 测试已保存连接
- **WHEN** Secret 管理员测试已保存且 host 获批的模型连接
- **THEN** TypeScript Runtime 使用 active Key 执行无 Tool 探测并返回脱敏结果

#### Scenario: 测试未批准URL
- **WHEN** Base URL 为 HTTP、带 userinfo、回环、链路本地、私网或目录外 host
- **THEN** 系统在发出模型请求前拒绝并只审计脱敏 host 和原因码

#### Scenario: Python 测试路径已删除
- **WHEN** TypeScript 迁移完成
- **THEN** Model Connection Service 不再调用 Python Claude SDK tester

### Requirement: Agent Profile模型连接操作必须授权和审计
系统 SHALL 复用统一 RBAC：读取需要 Agent read，保存需要 edit，发布/回退需要 publish，创建/轮换 Key 和真实连接测试需要 Secret 管理权限。所有写操作和测试 MUST 记录 Runtime/SDK version 与非敏感模型 provenance。

#### Scenario: 无Secret权限的用户更新Key
- **WHEN** 仅有 Agent edit 的用户提交 Key 轮换或连接测试
- **THEN** 系统拒绝且不访问外部模型服务

#### Scenario: 发布审计
- **WHEN** 管理员发布 Agent Publication
- **THEN** 审计记录 Agent、Publication、模型连接 revision/hash、模型、Runtime version 和脱敏 host，不记录 Key、Secret ref、Prompt 或响应正文

## REMOVED Requirements

### Requirement: Web必须提供默认Agent Profile管理入口
**Reason**: 管理入口从只能编辑默认 Agent 扩展为正式多 Agent Publication 工作区。

**Migration**: 使用新增的“Web 必须提供多 Agent Publication 管理入口”；默认诊断 Agent 作为普通的预置 Agent 保留，不迁移或删除其历史。
