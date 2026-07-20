## ADDED Requirements

### Requirement: MVP 管理一个默认诊断 Agent 且保留多 Agent 模型
系统 SHALL 基于多 Agent 后端模型提供 Agent 列表和详情，但 MVP 写入界面 MUST 只开放默认诊断 Agent 的草稿、校验、发布、回滚以及工具、Skill、Channel 分配。

#### Scenario: 编辑默认诊断 Agent
- **WHEN** 授权管理员修改默认诊断 Agent 草稿并通过校验
- **THEN** 系统允许发布新 revision 并保留发布审计和回滚能力

#### Scenario: 查看其他 Agent
- **WHEN** 后端存在非默认 Agent
- **THEN** MVP 可以展示其只读摘要或将其标记为未开放管理
- **AND** 不提供绕过范围限制的写入口

### Requirement: Skill Catalog 只读展示并支持受控分配
系统 SHALL 从受控 Skill Loader/Catalog 返回 Skill 编码、名称、描述、来源、加载状态和安全错误；MVP MUST 不允许通过 Web 上传、编辑或删除 Skill 文件，但 SHALL 允许把已加载 Skill 分配给默认 Agent。

#### Scenario: 分配可用 Skill
- **WHEN** 管理员将已成功加载的 Skill 分配给默认 Agent 草稿
- **THEN** 系统保存绑定并在 Agent 发布校验中验证该 Skill 仍然可用

#### Scenario: Skill 加载失败
- **WHEN** 某个 Skill 文件无效或不可读
- **THEN** 页面展示安全的失败状态且禁止将其新增到 Agent 发布版本

### Requirement: API 工具页面管理类型化只读资源
系统 SHALL 支持管理数据库、Redis 和 Loki 类型化资源、作用域、启停状态、只读工具绑定、Secret 引用和连接测试；系统 MUST 拒绝任意脚本、Shell、未受控 HTTP 目标和写操作能力。

#### Scenario: 创建数据库资源
- **WHEN** 管理员提交合法的数据库类型、endpoint 元数据、作用域和 Secret 引用
- **THEN** 系统保存类型化资源并仅返回脱敏配置

#### Scenario: 创建任意 HTTP 执行工具
- **WHEN** 用户尝试通过 MVP API 工具页面提交任意 URL、脚本或写操作定义
- **THEN** 系统拒绝请求并记录安全审计

### Requirement: 连接测试是显式、受限且可审计的操作
系统 SHALL 仅在授权管理员显式触发时执行数据库、Redis 或 Loki 连接测试，测试 SHALL 使用短超时和只读探测，并记录操作者、资源、结果和 correlation id，MUST NOT 返回凭据或原始响应正文。

#### Scenario: 数据库连接测试成功
- **WHEN** 管理员对合法数据库资源执行连接测试
- **THEN** 系统使用只读身份和短超时完成探测，并返回资源类型、耗时和成功摘要

#### Scenario: 连接测试失败
- **WHEN** 上游连接失败或超时
- **THEN** 系统返回脱敏错误分类和 correlation id，不返回连接串、密码或未受限异常正文

### Requirement: Channel 页面只开放已实现的钉钉能力
系统 SHALL 管理钉钉 Stream、Callback 和 Delivery Connector 的方向、状态、Secret 引用、endpoint 安全策略和 Agent 绑定；邮件、企业微信等未来 Provider SHALL 仅体现在可扩展领域模型中，不得在 MVP 显示为可保存配置。

#### Scenario: 配置钉钉 Stream 入口
- **WHEN** 管理员保存启用 ingress 的钉钉 Stream Connector
- **THEN** 系统校验所需凭据引用、方向和租户绑定，并写入审计

#### Scenario: 查看未来 Provider
- **WHEN** 用户打开 Channel 创建页面
- **THEN** 页面只提供当前后端声明为 available 的 Provider，不展示不可用的邮件或企业微信表单

### Requirement: 用户和授权页面复用统一主体
系统 SHALL 通过统一管理 Shell 提供内部用户、钉钉身份绑定、角色、权限策略、访问授权和会话撤销入口，所有授权最终 SHALL 绑定内部 `app_user` 主体而非外部钉钉 ID。

#### Scenario: 给钉钉用户授权
- **WHEN** 管理员为绑定钉钉身份的用户分配角色或资源授权
- **THEN** 权限保存到对应内部用户主体并同时适用于 Web 与钉钉入口
