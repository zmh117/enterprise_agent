# agent-model Specification

## Purpose

定义 Agent Definition、Draft、Publication、模型连接和 Workflow 配置资产的当前合同。

## 领域边界

本领域负责配置和发布；应用组合见 `business-application`，运行协议与审计见 `execution-delivery`，ONES 查询与写操作合同见 `governed-api-capability`。Workflow 是配置资产，当前未自动执行图。

## 实现依据与验证边界

代码：`backend/app/modules/agent_config/application/service.py`、`backend/app/modules/agent_config/api/controller.py`、`backend/app/modules/model_connection/`、`backend/app/modules/workflow/`、`frontend/src/contexts/agent-profiles/`。

测试定义：`backend/tests/test_agent_profile_model_connections.py`、`test_deepseek_model_connection_setup.py`、`test_workflow_fact_sources.py`（后三者同在 backend/tests）。

本规格于 2026-09-16 按当前代码重建。代码与测试定义可定位实现和覆盖范围；本次文档重建不代表执行了真实模型、Provider、数据库升级或部署验收。

## Requirements

### Requirement: Agent Profile必须管理限定的Anthropic-compatible模型配置
系统 SHALL 允许 Python Agent Profile 配置一个 `anthropic_compatible` 模型连接，并 SHALL 以规范化字段管理 Base URL、主模型、Opus/Sonnet/Haiku 默认模型、Subagent 模型和 effort level。系统 MUST 将一个 API Key Credential 同时映射为运行时所需的 `ANTHROPIC_API_KEY` 与 `ANTHROPIC_AUTH_TOKEN`，MUST NOT 要求用户重复保存相同密钥。

#### Scenario: 配置DeepSeek Anthropic-compatible连接
- **WHEN** 管理员配置 HTTPS Anthropic Base URL、当前发现列表中的主模型、默认模型映射、Subagent 模型和 `max` effort
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
系统 SHALL 提供模型连接测试动作，测试 MUST 使用保存后的模型连接和 active Secret，通过独立 Python Runtime 的官方 Claude Agent SDK 路径执行无工具、单轮、短超时探测。Python API MUST 先执行 RBAC、官方 HTTPS 或显式允许的内部网关、Provider host allowlist、userinfo、fragment、重定向、官方地址的回环、链路本地和私网拒绝校验；内部网关仅接受部署白名单目标；重定向校验只允许下述永久同源尾斜杠规范化例外。Runtime MUST 再按固定 revision/config hash 解析连接。响应 MUST 只包含 Provider Host、模型、Runtime/SDK 版本、耗时和安全结果，不得包含 Key、Secret ref、Prompt、模型响应正文或内部异常详情。

#### Scenario: 测试已保存DeepSeek连接
- **WHEN** Secret 管理员测试已保存、host 被允许且 revision/config hash 固定的 DeepSeek Anthropic-compatible 连接
- **THEN** Python 服务把受限 probe 委托给 `python-agent-runtime`，Runtime 使用 active Key 完成无 Tool 探测并返回安全状态和耗时

#### Scenario: 测试未批准URL
- **WHEN** 管理员提交官方服务的回环/私网/HTTP目标、带 userinfo 的 URL 或不在 allowlist 的 host
- **THEN** Python 服务在调用 Runtime 前拒绝连接
- **AND** 审计只记录脱敏 host、actor、结果和 correlation ID

#### Scenario: 连接版本发生漂移
- **WHEN** Runtime 读取到的模型连接 revision 或 config hash 与 probe 请求不一致
- **THEN** Runtime 在调用 Provider 前失败关闭并返回稳定配置漂移错误

### Requirement: Agent Profile模型连接操作必须授权和审计
系统 SHALL 复用统一 RBAC：读取 Profile 需要 Agent read/edit 权限，创建 Agent 需要 `agent:*:edit` 全局权限，保存草稿需要目标 Agent edit 权限，发布和回滚需要目标 Agent publish 权限，创建或轮换 Key 及执行真实连接测试需要 Secret 管理权限。所有写操作和连接测试 MUST 记录不含敏感值的审计事件。
#### Scenario: 无Secret权限的用户更新Key
- **WHEN** 仅具有 Agent edit 权限的用户提交 Key 创建、轮换或连接测试请求
- **THEN** 系统拒绝请求且不访问外部模型服务
#### Scenario: 发布审计
- **WHEN** 管理员发布包含模型连接的 Agent Publication
- **THEN** 审计记录 Agent code、Publication ID、模型连接 revision、config hash、模型和脱敏 Provider Host
- **AND** 审计不包含 Key、Secret ref、Prompt 或模型响应
#### Scenario: 无全局编辑权限的用户创建Agent
- **WHEN** 用户具备某个既有 Agent 的编辑权限但不具备 `agent:*:edit` 全局权限并提交创建请求
- **THEN** 系统拒绝请求且不写入 Agent Definition 或 Draft
- **AND** 权限拒绝通过统一 RBAC 审计记录
#### Scenario: 创建Agent审计
- **WHEN** 管理员成功创建 Agent
- **THEN** 审计记录 actor、Agent code、Runtime kind、项目编码和初始 Draft revision
- **AND** 审计不包含模型凭据、Secret、Prompt 或业务消息

### Requirement: Agent workflow templates are persisted
系统 SHALL 在 PostgreSQL 中持久化 Agent 诊断流程模板，并 MUST 支持草稿、已发布、禁用等状态。

#### Scenario: Create diagnostic workflow template
- **WHEN** 管理端创建一个订单诊断流程模板
- **THEN** 系统保存模板编码、名称、项目编码、状态、版本、入口节点和扩展设置

#### Scenario: Disable workflow template
- **WHEN** 管理端禁用一个流程模板
- **THEN** 后续运行时选择流程模板时 MUST 不使用该禁用模板

### Requirement: Workflow nodes and edges support drag-and-drop graph editing
系统 SHALL 持久化流程节点、节点位置、节点配置、边、端口和条件配置，以支持后续 Web 拖拽编排。

#### Scenario: Add tool call node
- **WHEN** 管理端在画布中添加一个 Loki 查询节点
- **THEN** 系统保存节点 key、节点类型、标题、画布位置和只读工具调用配置

#### Scenario: Connect two nodes
- **WHEN** 管理端把上下文检索节点连接到工具调用节点
- **THEN** 系统保存边 key、源节点、目标节点、端口和条件配置

### Requirement: Workflow graph is validated before save and publish
系统 SHALL 校验 workflow graph 的结构，至少包括入口节点存在、边引用的节点存在、节点 key 唯一、边 key 唯一和 代码固定的只读节点边界。

#### Scenario: Edge references missing node
- **WHEN** 管理端保存一条指向不存在节点的边
- **THEN** 系统拒绝保存并返回图校验错误

#### Scenario: Workflow contains mutation node
- **WHEN** 管理端保存包含写库、删 Redis、重启服务或改代码动作的节点
- **THEN** 系统拒绝保存，因为 Workflow 图校验仍限制为只读诊断节点；这与 MCP 外部操作确认链相互独立

### Requirement: Workflow发布形成不可变配置快照
系统 SHALL 在发布流程模板时创建不可变发布快照，后续引用 MUST 使用发布快照而不是正在编辑的草稿图；当前不因发布而自动执行Workflow。

#### Scenario: Publish workflow template
- **WHEN** 管理端发布一个合法流程模板
- **THEN** 系统创建新版本发布快照，保存完整 graph snapshot、配置 hash、发布人和发布时间

#### Scenario: Edit draft after publish
- **WHEN** 管理端在发布后继续编辑草稿节点
- **THEN** 已发布快照 MUST 保持不变，直到下一次发布生成新版本

### Requirement: Workflow templates remain configuration until explicitly wired to runtime
系统 SHALL 把 workflow 模板作为配置资产管理，当前 MUST NOT 因保存或发布模板而自动改变 Agent job 执行链路。

#### Scenario: Save workflow template
- **WHEN** 管理端保存或发布流程模板
- **THEN** 系统只更新配置表和发布快照，不立即启动 Agent job 或执行工具调用

### Requirement: 管理Web必须提供连续的DeepSeek模型连接配置向导
系统 SHALL 在Python Agent Profile 的“模型与连接”区域提供单一连续向导，依次完成 DeepSeek Anthropic Base URL 与 Credential 输入、模型发现、模型映射、真实配置测试和最终保存。系统 MUST NOT 再要求管理员通过独立的连接 revision 保存、Credential 弹窗和已保存版本测试完成一次配置。

#### Scenario: 首次配置模型连接
- **WHEN** 具有 Agent 编辑与 Secret 管理权限的管理员打开尚未配置 Credential 的所选模型连接
- **THEN** 页面按 URL 与 Key、模型发现、模型映射、配置测试和最终保存的顺序引导操作
- **AND** 在最终保存成功前不把连接显示为 ready

#### Scenario: 输入变化使下游结果失效
- **WHEN** 管理员在模型发现后修改 Base URL 或 Credential，或者在配置测试后修改任一模型映射或 effort
- **THEN** 页面清除所有受影响的发现或测试结果
- **AND** 管理员必须从相应步骤重新检测

### Requirement: 系统必须从固定契约的DeepSeek服务发现模型
系统 SHALL 只接受满足部署 allowlist 的 DeepSeek 官方 HTTPS Anthropic Base URL 或内部 Anthropic-compatible 网关。官方地址 MUST 通过移除末尾 `/anthropic`、追加 `/models` 确定性派生模型发现 URL；内部网关 Base path MUST 精确为 `/api`，模型发现 URL MUST 固定为 `/api/v1/models`，且原始 Base URL MUST 原样交给 Claude Agent SDK，使消息请求固定落在 `/api/v1/messages`。系统 MUST 拒绝 userinfo、query、fragment、未批准 host、非法或不兼容 path 和 redirect；唯一例外是 Base URL 无凭据 `HEAD` 预检返回 `301` 或 `308`，且 `Location` 解析后与原地址保持相同 scheme、host 和有效 port，不含 userinfo、query 或 fragment，唯一路径差异为增加末尾 `/`。系统对该例外 MUST 只判定为可接受规范化，不得跟随跳转、改写已保存 Base URL 或把 Credential 发送到 `Location`。`302`、`307`、跨 scheme/host/port、其它 path 变化及缺失或歧义 `Location` 仍 MUST 拒绝。官方目标还 MUST 拒绝非 443 端口以及解析到回环、链路本地、私网或保留 IP 的地址，内部网关只允许部署白名单中的 HTTP 或 HTTPS 主机。

#### Scenario: 从官方Anthropic URL发现模型
- **WHEN** 管理员提交 `https://api.deepseek.com/anthropic` 和有效 Credential
- **THEN** 系统请求同一官方服务的 `https://api.deepseek.com/models`
- **AND** 返回去重、受限且不含 Credential 的模型 ID 列表

#### Scenario: 从内部Anthropic-compatible网关发现并测试模型
- **WHEN** 管理员提交部署白名单中的 `部署白名单网关的 `/api`` 和有效 Credential
- **THEN** 系统请求 `部署白名单网关的 `/api/v1/models`` 发现模型
- **AND** Claude Agent SDK 使用同一 Base URL 请求 `同一网关的 `/api/v1/messages`` 完成真实配置测试

#### Scenario: 接受同源永久尾斜杠规范化
- **WHEN** Base URL 无凭据 `HEAD` 预检对 `部署白名单网关的 `/api`` 返回 `301` 或 `308`，且 `Location` 仅为同源 `部署白名单网关的 `/api/``
- **THEN** Python API 接受该预检结果并继续使用原始 `/api` Base URL 执行后续受限模型测试
- **AND** 不跟随跳转、不改写保存值，也不允许 `302`、`307`、跨源或其它路径重定向

#### Scenario: 拒绝未批准或路径不兼容的网关
- **WHEN** 管理员提交未在部署白名单中的第三方 host、自定义模型列表 URL、内部网关 `/api/v1` Base URL 或其它不符合规则的地址
- **THEN** 系统在外部请求前以稳定字段错误拒绝
- **AND** 不尝试猜测其它第三方模型发现或消息路径

#### Scenario: 模型列表响应不安全
- **WHEN** DeepSeek 模型列表为空、格式错误、超出响应大小或模型数量上限
- **THEN** 系统返回稳定安全的模型发现错误
- **AND** 不返回上游响应正文或内部解析异常

### Requirement: 模型发现和草稿测试必须无持久化副作用
系统 SHALL 允许使用本次提交的 API Key 或当前有效 encrypted DB Credential 执行模型发现与草稿配置测试。发现和测试动作 MUST NOT 创建或更新 Secret、Secret version、模型连接 revision、Agent 草稿或 Publication，且 MUST NOT 把 API Key 写入日志、审计 payload、查询缓存或响应。

#### Scenario: 使用新Key发现失败
- **WHEN** 管理员提交新 API Key 但 DeepSeek 拒绝鉴权或请求超时
- **THEN** 系统返回脱敏错误并保持数据库不变
- **AND** 不创建孤立 Secret 或 rotation-required revision

#### Scenario: 沿用已有Credential执行发现
- **WHEN** 当前模型连接绑定可用 Credential 且管理员选择沿用
- **THEN** 服务端内部解析 active Secret 完成发现
- **AND** 前端仍只看到 configured 状态、脱敏摘要和模型列表

#### Scenario: 关闭向导清除明文
- **WHEN** 管理员关闭、离开或成功完成配置向导
- **THEN** 前端立即清空 API Key input state 和 mutation variables
- **AND** 不把该值写入 URL、local storage、session storage 或 TanStack Query data

### Requirement: 模型映射必须由当前发现结果驱动
系统 SHALL 要求主模型选择自当前发现结果，并 SHALL 允许 Opus、Sonnet、Haiku 和 Subagent 映射选择发现模型或继承主模型。最终保存前系统 MUST 把继承项规范化为显式主模型，并 MUST 重新确认所有模型仍在最新发现列表中。

#### Scenario: 配置不同模型映射
- **WHEN** 管理员从发现列表分别选择主模型、Opus、Sonnet、Haiku 和 Subagent 模型
- **THEN** 页面显示每个映射的明确选择
- **AND** 草稿测试与最终连接 revision 使用同一组规范化模型

#### Scenario: 默认映射继承主模型
- **WHEN** 管理员把任一默认模型或 Subagent 模型设为“继承主模型”
- **THEN** 系统在测试和保存前使用主模型补齐
- **AND** 保存的非敏感 config 包含补齐后的显式值

#### Scenario: 旧模型不再可用
- **WHEN** 当前历史 revision 的模型不在最新发现列表中
- **THEN** 页面显示旧值和不可用警告但不修改历史 revision
- **AND** 管理员必须重新选择可用模型后才能保存新 revision

### Requirement: 保存前必须通过真实Claude Agent SDK配置测试
系统 SHALL 使用临时非敏感配置和本次 Credential 来源，通过与生产 Job 相同的 Claude Agent SDK 兼容路径执行无 Tool、无 MCP、单轮、短超时测试。测试 MUST 使用所选主模型，MUST NOT 接受任意 Prompt，并 MUST NOT 返回模型响应正文、SDK stderr、Credential 或请求 header。

#### Scenario: 草稿配置测试成功
- **WHEN** 规范化 URL、Credential 和所选主模型可以通过 Claude Agent SDK 完成最小探测
- **THEN** 系统返回 provider host、模型、耗时和成功状态
- **AND** 页面允许进入最终保存步骤

#### Scenario: 发现成功但模型调用失败
- **WHEN** `/models` 返回所选模型但 Claude Agent SDK 认证、模型调用或协议兼容测试失败
- **THEN** 系统返回稳定安全错误并禁止最终保存
- **AND** 数据库与 active Secret 保持不变

### Requirement: 最终配置必须原子保存Secret和连接revision
系统 SHALL 提供一个带 `expected_revision` 的原子配置动作。该动作 MUST 在数据库事务外重新执行模型发现与真实配置测试，在提交前再次校验 revision，并 MUST 在同一数据库 unit of work 中创建或轮换 encrypted DB Secret、追加一个 ready 模型连接 revision、更新 current revision/status 和写入脱敏审计。任一步失败时 MUST 不产生部分写入。

#### Scenario: 首次原子配置成功
- **WHEN** 未绑定 Credential 的连接提交有效 URL、API Key、模型映射和当前 expected revision
- **THEN** 系统创建 encrypted DB Secret 并追加绑定该 Secret 的 ready revision
- **AND** 响应只返回公共连接状态和脱敏 Credential 摘要

#### Scenario: 最终验证失败
- **WHEN** 最终保存时重新发现的模型列表不再包含所选模型或 SDK 测试失败
- **THEN** 系统不创建 Secret、Secret version 或连接 revision
- **AND** 当前连接状态和 revision 保持不变

#### Scenario: 保存期间发生并发修改
- **WHEN** 外部测试完成后连接 revision 已不再等于 expected revision
- **THEN** 系统返回包含当前 revision 的 409
- **AND** Secret 与连接 revision 均不发生部分更新

### Requirement: 原子配置必须支持Credential沿用、轮换和缺失恢复
系统 SHALL 允许新 revision 沿用当前可用 Credential，或在管理员提交新 API Key 时轮换同一受管 Credential。当前绑定缺失、停用、不可解析或处于 rotation-required 状态时，系统 MUST 要求新 API Key。确定性 Secret code 已存在但未绑定时，系统 MUST 仅在其所有权 metadata 明确属于同一 model connection 时允许轮换并重新绑定。

#### Scenario: 沿用当前有效Credential
- **WHEN** 管理员只修改模型映射并选择沿用当前有效 Credential
- **THEN** 新 revision 继续绑定同一 Secret 身份
- **AND** 系统不创建新的 Secret version

#### Scenario: 轮换当前Credential
- **WHEN** 管理员提交新的 API Key 并完成最终配置
- **THEN** 系统创建新的 active Secret version并让新 revision 保持稳定 Credential 身份
- **AND** 旧明文和旧 active version不再解析

#### Scenario: 恢复未绑定连接
- **WHEN** 当前连接为 rotation-required 且没有 Secret 绑定，管理员提交新 API Key
- **THEN** 系统创建或安全重新绑定属于该连接的受管 Secret
- **AND** 连接在同一事务中进入 ready

#### Scenario: 拒绝Secret所有权冲突
- **WHEN** 确定性 Secret code 已由其他资源或其他 model connection 管理
- **THEN** 系统失败关闭并返回 Credential 所有权冲突
- **AND** 不轮换、不覆盖且不重新绑定该 Secret

### Requirement: 模型连接配置操作必须授权、限流、审计和脱敏
系统 SHALL 要求 Agent 编辑权限与 Secret 管理权限才能执行 discover、test-draft 和 configure，并 MUST 对外部探测动作实施用户与连接维度限流。系统 MUST 使用稳定中文错误区分 URL、鉴权、发现、空模型、模型不可用、SDK 测试、超时、并发和所有权冲突；审计和运行输出 MUST 不包含 API Key、Authorization header、Secret ref、模型响应正文或完整上游错误。

#### Scenario: 无Secret权限执行模型发现
- **WHEN** 只有 Agent 编辑权限的用户提交 discover、test-draft 或 configure
- **THEN** 系统在任何 Secret 解析或外部网络请求前拒绝
- **AND** 不产生模型调用费用或配置写入

#### Scenario: 探测请求超过限额
- **WHEN** 同一用户或连接在限流窗口内超过允许的发现或测试次数
- **THEN** 系统返回稳定限流错误且不访问 DeepSeek
- **AND** 审计只记录 actor、连接 code、动作和安全结果

#### Scenario: 安全错误投影
- **WHEN** DeepSeek 或 Claude Agent SDK 返回包含请求 header、Key、响应正文或内部异常的失败
- **THEN** API 只返回稳定错误码和中文安全摘要
- **AND** 日志、审计和前端状态不包含敏感原文

### Requirement: Agent 定义按多 Agent 模型持久化
系统 SHALL 持久化多个 Agent 定义，每个定义具有稳定 code、名称、说明、项目范围、状态、当前发布指针和创建后不可变的 `runtime_kind`。系统 MUST 在 deployment bootstrap 中仅幂等初始化固定 `python-v1` 的默认诊断 Agent，并 SHALL 只允许受权管理员创建 `python-v1` 业务 Agent。Definition、Publication 与 Job 的 runtime kind MUST 由数据库约束限定为 `python-v1`；系统不得新建、编辑、发布、回滚或执行其它 runtime kind 的 Agent，也不得通过修改同一 Agent 的 runtime kind 完成 Runtime 切换。

#### Scenario: 默认Python Agent初始化
- **WHEN** 系统完成 migration 和 Agent bootstrap
- **THEN** 系统存在稳定 code 为 `default-diagnostic-agent` 且 runtime kind 为 `python-v1` 的 Agent
- **AND** 系统不创建任何其它 runtime kind 的 Agent

#### Scenario: 创建Python Agent
- **WHEN** 具备权限的管理员提交唯一合法 code、名称、项目编码和 `python-v1`
- **THEN** 系统创建 classification 为 `business`、status 为 `enabled` 的 Agent Definition
- **AND** Definition 的 runtime kind 固定为 `python-v1`

#### Scenario: 客户端创建非Python Agent
- **WHEN** 客户端提交任何非 `python-v1` runtime kind
- **THEN** 系统拒绝请求且不创建 Definition 或 Draft

#### Scenario: 重复运行Agent bootstrap
- **WHEN** 已存在固定 Agent、用户 Draft 或 Publication 后再次运行 Agent bootstrap
- **THEN** 系统不覆盖既有名称、配置、版本、Publication 或业务应用引用
- **AND** 固定 code 对应的 runtime kind 不一致时 bootstrap 失败关闭

### Requirement: Agent 草稿与发布快照分离
系统 SHALL 为 Python Agent 保存可编辑草稿 revision，并 MUST 在发布时创建包含完整有效配置、不可变 `python-v1` runtime kind、schema version 和 config hash 的不可变 publication snapshot。草稿不得覆盖 Definition 的 runtime kind。

#### Scenario: 编辑已发布Python Agent草稿
- **WHEN** 管理员修改已发布 Python Agent 的业务指令或工具分配
- **THEN** 系统只创建或更新该 Agent 的新草稿 revision，现有 publication 与 runtime kind 保持不变

#### Scenario: 发布合法Python草稿
- **WHEN** 具备发布权限的管理员发布通过校验的 Python Agent 草稿
- **THEN** 系统创建包含 `python-v1` 的新不可变 publication，并更新该 Agent 的当前发布指针

#### Scenario: 草稿伪造Runtime
- **WHEN** 草稿 payload 的 runtime kind 不是 `python-v1` 或与 Agent Definition 不一致
- **THEN** 系统拒绝校验和发布且不创建 publication

### Requirement: Agent 发布配置区分可编辑业务层和强制安全层
Agent 草稿 SHALL 只接受代码定义的 business role/instructions、模型策略、执行上限、Skill、项目、渠道绑定和 MCP Tool identifier。系统 MUST 拒绝平台安全字段、凭据、任意执行入口和未注册 Tool；已注册的受治理 mutation 可进入 Tool Envelope，并冻结 effect 与逐次确认策略。沙盒内 Write/Edit 由文件能力和 Runtime 决定，不是 Agent 草稿可自行开启的任意写权限。

#### Scenario: 保存业务指令
- **WHEN** 管理员修改业务目标或报告偏好
- **THEN** 业务指令与平台强制安全层分开，不能覆盖服务端授权和执行预算。

#### Scenario: 选择受治理外部写工具
- **WHEN** 草稿选择代码 Manifest 中合法的 mutation Tool
- **THEN** 发布必须验证并冻结 schema/effect/confirmation policy；具体参数仍需独立 Action Intent 确认。

#### Scenario: 尝试自定义执行能力
- **WHEN** 草稿包含 Bash、Shell、自定义Write/Edit权限、凭据或未注册 Tool
- **THEN** 形状或安全校验拒绝，不生成可执行 Publication。

### Requirement: Agent job 固定发布版本
系统 SHALL 在创建 Job 的数据库事务中保存 Agent definition、publication ID、revision、config hash、runtime kind 和 Runtime 协议版本。Worker 和 retry MUST 使用 Job 固定的 publication 与 Runtime，不得重新读取当前发布指针、草稿或迁移门禁，也不得在故障时跨 Runtime fallback。

#### Scenario: 发布后创建Job
- **WHEN** Application 选择的 Agent Publication 有效且用户提交请求
- **THEN** Job 在发布队列前固定该 publication ID、revision、hash、runtime kind 和协议版本

#### Scenario: Job排队期间发布新版本
- **WHEN** Job 已固定版本后管理员发布新的 Agent revision
- **THEN** 已排队 Job 继续使用原版本和 Runtime，新 Job 才使用新 Publication

#### Scenario: Job重试
- **WHEN** Job 因瞬时错误进入 retry
- **THEN** 重试仍使用原 publication snapshot、runtime kind、协议版本和 invocation 规则

#### Scenario: 固定Runtime不可用
- **WHEN** Job 固定的 Runtime 暂时不可连接
- **THEN** Worker 按固定错误分类重试或终止，不自动调用另一 Runtime

### Requirement: Agent 发布支持校验和回滚
系统 SHALL 在发布前校验引用的模型策略、工具、Skill、connector、项目和安全边界，并 MUST 通过切换当前发布指针回滚到执行兼容状态为 current 的历史 publication，不修改历史快照。

#### Scenario: 发布引用禁用工具
- **WHEN** 草稿分配未注册、禁用或执行策略不兼容的工具
- **THEN** 系统拒绝发布并返回字段级校验错误

#### Scenario: 回滚默认 Agent
- **WHEN** 具备发布权限的管理员选择一个历史有效 publication 回滚
- **THEN** 系统把它设为新 job 的当前版本、记录审计，并保持历史 publication 不变

### Requirement: 未发布或无效 Agent 必须 fail closed
系统 SHALL 在目标 Agent 没有启用的有效 publication、publication hash 不一致或 snapshot schema 不受支持时拒绝创建或执行新 job。

#### Scenario: 默认 Agent 尚未发布
- **WHEN** Channel 请求选择默认 Agent但它没有有效 publication
- **THEN** 系统返回安全配置错误且不发布 Agent job

### Requirement: Workflow 草稿图必须只有一个可变事实源
系统 SHALL 只以 `agent_workflow_node` 与 `agent_workflow_edge` 的规范化记录读取、编辑、校验和发布 Workflow 草稿，模板只保存元数据。系统 MUST NOT 重新引入模板 `graph_json` 的可变影子副本或双写。

#### Scenario: 编辑草稿图
- **WHEN** 管理员修改节点、位置或连线
- **THEN** 服务更新规范化记录与相应模板 revision，后续读取和发布使用同一事实源。

### Requirement: Workflow 发布快照必须从规范化草稿原子生成
系统 MUST 在一个一致的数据库读取边界内，从模板元数据和规范化 node/edge 草稿生成确定性 graph snapshot、schema version 与 config hash，并 SHALL 将该 snapshot 保存为不可变的已发布运行事实。发布后编辑草稿不得改变历史 snapshot。

#### Scenario: 发布规范化 Workflow 草稿
- **WHEN** 管理端发布通过校验的 Workflow 草稿
- **THEN** 系统从规范化 node/edge 记录生成一个确定排序的不可变 snapshot 和 hash
- **AND** 业务应用引用固定 publication snapshot；当前没有因发布而执行Workflow的运行引擎

#### Scenario: 发布期间草稿并发变化
- **WHEN** 生成 publication snapshot 时草稿 revision 已被并发更新
- **THEN** 系统拒绝本次发布或基于同一已锁定 revision 完整发布
- **AND** 不得产生混合两个 revision 的 snapshot

### Requirement: Agent创建必须原子生成初始草稿
系统 MUST 在同一数据库事务中创建 `python-v1` Agent Definition 与 r1 Draft。初始 Draft SHALL 使用平台固定的非敏感默认配置和所选项目范围，MUST NOT 接受客户端指定 Publication、状态、classification、created_by、任意模型凭据或 Runtime 覆盖，并 MUST NOT 自动发布或改变运行路由。

#### Scenario: 成功创建Agent
- **WHEN** 受权管理员提交合法、唯一且 runtime kind 为 `python-v1` 的 Agent 创建请求
- **THEN** 系统原子创建 Definition 和归属该 Definition 的 r1 Draft
- **AND** `current_publication_id` 为空且不存在因本次创建产生的业务应用引用

#### Scenario: Agent code重复
- **WHEN** 两个请求串行或并发提交同一 Agent code
- **THEN** 至多一个请求创建 Definition 与 r1 Draft
- **AND** 其他请求返回稳定 `agent_code_conflict`，不产生孤立 Definition 或 Draft

#### Scenario: 创建请求包含平台控制字段
- **WHEN** 客户端提交 status、classification、current publication、created_by、Draft config 或其他未声明字段
- **THEN** API 拒绝请求且不写入任何 Agent 记录

#### Scenario: 创建请求使用非法Runtime
- **WHEN** 客户端提交任何非 `python-v1` runtime kind
- **THEN** API 返回字段级校验错误且不创建 Definition 或 Draft

### Requirement: Workflow 管理必须使用 Agent 权限矩阵
系统 SHALL 将 Workflow 模板、节点、边和发布记录视为 Agent 管理资产。读取 MUST 要求 `agent/read`，草稿新增、修改、启停 MUST 要求 `agent/edit`，发布 MUST 要求 `agent/publish`；Workflow API MUST NOT 复用平台配置 manage 作为通用管理员权限。

#### Scenario: 只有 Agent 读取权限
- **WHEN** 已登录用户只有 `agents.read`
- **THEN** 用户可以读取 Workflow 模板、节点、边和最新 Publication，但修改和发布返回 403

#### Scenario: 具有 Agent 编辑权限
- **WHEN** 已登录用户具有 `agents.edit` 但没有 `agents.publish`
- **THEN** 用户可以保存草稿和修改图，但发布返回 403

#### Scenario: 具有 Agent 发布权限
- **WHEN** 已登录用户具有 `agents.publish` 且发布内容通过校验
- **THEN** 系统创建不可变 Workflow Publication 并记录当前 principal actor

### Requirement: Agent必须通过ONES查询Skill编排复杂只读查询
系统 SHALL 提供可选择的 `ones-query` Skill，指导 Agent 把复杂 ONES 请求拆为实时项目、迭代、事项类型和人员发现，受管状态或自定义选项解析，以及对应的只读工作项查询。Skill MUST NOT 内嵌真实 Team、项目、人员、状态、字段或选项 UUID，不得指导 Agent 读取字典文件、提交 Provider 筛选键或执行任意 GraphQL/REST。

#### Scenario: 查询某项目最新迭代已完成任务
- **WHEN** 用户用中文项目名和“最新迭代”“已完成”等语义提出查询
- **THEN** Agent 先使用实时 Tool 解析项目与迭代，再按稳定完成类别或有证据的精确状态查询工作项
- **AND** 项目或迭代存在多个合理候选时不猜测 UUID

#### Scenario: 查询自定义选项
- **WHEN** 用户用中文字段名和选项名描述自定义筛选
- **THEN** Agent 调用 `ones_resolve_query_conditions` 获取有界候选，再把确认后的字段 UUID 与选项 UUID 传给 `ones_query_work_items_with_custom_options`
- **AND** Agent 不读取受管字典文件、不构造 Provider 筛选键，也不自动选择同名候选的第一项

#### Scenario: 用户提出可变统计需求
- **WHEN** 用户要求统计完成量、响应时间或其他指标
- **THEN** Agent 仅按本次用户明确的统计口径选择数据和计算方式
- **AND** 完成定义、首次响应、工作时段、排除项、分组或月份边界缺失且会显著改变结果时，Agent 先请求澄清

#### Scenario: Skill未进入当前Publication
- **WHEN** 已冻结 Agent Publication 或 Job snapshot 未选择 `ones-query`
- **THEN** 运行时不加载该 Skill
- **AND** 新 Skill 只能通过新的 Agent Publication 以及后续显式 Business Application 发布与激活生效

### Requirement: Agent Runtime 协议升级后必须可由管理面恢复
系统 SHALL 将 Agent Publication 的管理读取兼容性与新执行准入兼容性分离。结构、哈希、Runtime kind 和快照对应的冻结工具事实完整，但 Runtime 协议或 MCP 工具执行策略不再兼容当前平台的 Publication MUST 在 Agent 管理详情与发布历史中以历史只读状态返回，不得使整个管理请求失败；新发布、回滚和新 Job 创建 MUST 继续只接受综合执行兼容状态为当前的 Publication，已经固定 Publication 与协议的既有 Job MUST NOT 被改写。

#### Scenario: 管理员查看包含旧协议的发布历史
- **WHEN** Agent 发布历史中同时存在当前协议 Publication 和一个或多个格式合法的旧协议 Publication
- **THEN** 管理 API 返回完整有序列表，并分别标记 `current` 与 `historical_read_only`
- **AND** Web 展示旧协议版本的原始 revision、hash、runtime 和只读状态，不显示可用回滚动作

#### Scenario: 管理员查看工具策略已变化的发布版本
- **WHEN** Publication 快照与冻结工具行一致，但其工具已退役或执行策略不再匹配当前代码 Manifest
- **THEN** 管理 API 返回该 Publication 并标记 `historical_read_only` 和 `mcp_tool_policy` 原因
- **AND** Web 显示“工具策略已变化、只读”，不允许回滚或用于新 Job

#### Scenario: 管理员为历史只读当前版本创建恢复草稿
- **WHEN** 当前 Agent Publication 使用格式合法的旧协议或历史工具策略，且管理员具备 Agent 编辑与发布权限
- **THEN** Web 允许管理员从当前可编辑配置创建新的恢复草稿
- **AND** 恢复草稿仍须完成正常校验和显式发布，发布后生成使用当前协议的新不可变 Publication

#### Scenario: 新执行或回滚选择旧协议版本
- **WHEN** 新 Job 创建或 Agent 回滚选择历史协议 Publication
- **THEN** 系统以稳定错误失败关闭，且不切换当前执行版本、不创建 Job

#### Scenario: 已有 Job 固定旧协议版本
- **WHEN** Runtime 协议升级前创建的 Job 已固定旧协议 Publication 与协议版本
- **THEN** Worker 和 retry 继续使用该 Job 的固定事实完成或失败
- **AND** 系统不把该 Job 静默改写到新 Publication 或新协议

#### Scenario: 恢复发布后业务应用保持固定版本
- **WHEN** 管理员完成 Agent 恢复草稿的校验和发布
- **THEN** 系统只更新 Agent Definition 的当前 Publication 指针
- **AND** 已激活业务应用继续使用其固定的 Agent Publication，直到管理员显式更新并重新发布该应用

#### Scenario: 历史协议事实格式损坏
- **WHEN** Publication 的协议事实为空、不是数组、包含重复项或包含非版本字符串
- **THEN** 系统继续判定发布事实完整性失败
- **AND** 不把损坏事实标记为可恢复的历史只读协议

#### Scenario: 冻结工具事实与快照不一致
- **WHEN** Publication 快照中的工具标识、server 或 schema hash 与其冻结工具行不一致
- **THEN** 系统继续判定发布事实完整性失败
- **AND** 不把被篡改或不完整的冻结事实降级为可恢复的历史工具策略

### Requirement: Web必须提供多个Python Agent的真实管理入口
系统 SHALL 通过真实管理 API 展示 Agent 列表、详情、草稿、校验、当前 Publication、发布历史与应用引用。创建要求全局 Agent 编辑权限，已有 Python Agent 的读取、草稿保存、校验、发布和回滚分别受目标资源权限控制；`default-diagnostic-agent` 是幂等初始化的默认定义，不是唯一可编辑 Agent。code 与 runtime kind 创建后不可修改，创建不自动发布。

#### Scenario: 编辑业务Agent
- **WHEN** 有目标 Agent 编辑权限的管理员打开非默认 Python Agent
- **THEN** 页面和服务允许其保存目标草稿；发布仍须独立的发布权限。

#### Scenario: 列表为空
- **WHEN** 用户读取到空列表
- **THEN** 页面展示空状态；仅具备全局创建权限的用户可新建。

#### Scenario: 缺少全局权限
- **WHEN** 用户只有一个 Agent 的编辑权限并尝试创建另一 Agent
- **THEN** 服务拒绝且不创建 Definition 或 Draft。

### Requirement: Agent管理界面只管理Python Runtime
当前 Agent 创建、草稿、发布、回滚与执行 SHALL 只支持 `python-v1`，管理界面 MUST NOT 提供 Runtime 选择项。合法 Python 历史协议或工具策略版本可由管理读取标记为只读。当前 Publication 完整性校验 MUST 拒绝不受支持或与 Definition 不一致的 runtime kind，且不得通过改写标签进入当前执行链。

#### Scenario: 创建Python Agent
- **WHEN** 管理员具备权限并提交合法创建请求
- **THEN** Definition 和初始 Draft 使用 python-v1；页面不提供 Runtime 选择项。

#### Scenario: Runtime不受支持
- **WHEN** Publication 的 runtime kind 非 python-v1 或与 Definition 不一致
- **THEN** 完整性校验失败关闭，不能通过改标签进入当前执行链。
