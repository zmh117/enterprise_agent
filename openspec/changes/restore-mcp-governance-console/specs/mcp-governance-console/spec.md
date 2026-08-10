## ADDED Requirements

### Requirement: 控制台提供受信 MCP 配置工作区
系统 SHALL 在认证后的管理 Shell 中提供“MCP 配置”工作区，并 SHALL 按权限提供 Server、Tool Publication、Resource 和 Credential 页面。工作区 MUST NOT 出现 API Capability、Handler、Connection 或 Resource Mapping 页面、路由和兼容入口。

#### Scenario: 有权限管理员进入 MCP 配置
- **WHEN** 当前用户具有至少一个 MCP 配置读取权限
- **THEN** 页面只展示其有权读取的 MCP 配置子页面并从真实管理 API 加载数据

#### Scenario: 访问已退役旧平台路由
- **WHEN** 用户访问 API Capability、Handler、Connection 或 Resource Mapping 的旧路由或别名
- **THEN** 系统返回不存在或已退役结果，且不得加载备份页面或旧 API

### Requirement: MCP Server 只能来自服务端受信注册表
系统 SHALL 只展示由代码、部署清单或 Compose 注册的受信 MCP Server，并 MUST 将 Server 创建、编辑、删除、任意 URL、Transport、认证 Header 和动态配置排除在浏览器 API 之外。

#### Scenario: 查看受信 Server
- **WHEN** 有权限管理员打开 Server 列表
- **THEN** 页面显示服务端标识、名称、来源、Transport 摘要、健康状态、最近检查时间和脱敏错误，不显示 Token 或 Header

#### Scenario: 客户端提交任意 MCP 地址
- **WHEN** 客户端尝试创建 Server 或提交任意 URL、Transport、Header 或认证参数
- **THEN** 后端拒绝请求且不修改注册表或运行配置

### Requirement: MCP Tool 目录和 Publication 使用服务端事实
系统 SHALL 从受信 Server 发现快照读取 Tool 目录，并 SHALL 允许有权管理员在当前 Agent/Application Publication 边界内启用或停用 Tool Publication。客户端 MUST NOT 定义 Tool 名、Schema、Server 归属或任意工具编码。

#### Scenario: 管理员启用已发现 Tool
- **WHEN** 管理员对当前受信快照中的 Tool 提交合法目标、expected revision 和幂等键
- **THEN** 后端重新解析 Tool 事实、验证 Publication 边界并保存新的受治理版本

#### Scenario: 客户端伪造 Tool Schema
- **WHEN** 客户端提交不属于服务端快照的 Tool、Schema 或 Server 归属
- **THEN** 后端拒绝整个变更且不创建动态 Tool

### Requirement: Data MCP Tool 只绑定精确 Resource Deployment
系统 SHALL 允许声明需要数据资源的 Tool Publication 绑定零个或一个兼容的精确 Resource Deployment，并 MUST 将该引用冻结到 Publication/运行快照。系统 MUST NOT 提供字段映射、规则表达式、自由查询模板或 Application Resource Mapping。

#### Scenario: 绑定兼容且启用的资源
- **WHEN** 管理员为 Data MCP Tool 选择范围一致、验证通过且已启用的 Resource Deployment
- **THEN** 系统保存精确 Deployment 引用并在新运行快照中解析对应 Generation

#### Scenario: 绑定不兼容或停用资源
- **WHEN** Tool kind 与 Resource kind 不兼容、资源未启用或范围不一致
- **THEN** 系统拒绝绑定并返回不含连接信息和 Secret 的字段级错误

#### Scenario: 尝试保存映射规则
- **WHEN** 客户端提交字段映射、转换规则、SQL、查询模板或通配 Resource 条件
- **THEN** 系统拒绝这些字段且不得将其持久化

### Requirement: Resource 页面使用两态安全投影
系统 SHALL 为 Database、Redis 和 Loki Resource 提供列表、详情、新建、编辑、启用和停用入口，页面主状态 MUST 只显示“启用”或“停用”。后端 MUST 继续通过 Draft、验证、不可变 Revision、Deployment、Generation 和 Last Known Good 完成操作。

#### Scenario: 编辑已启用资源成功
- **WHEN** 管理员提交合法编辑且新候选验证和装载成功
- **THEN** 系统创建新不可变版本并原子切换有效 Generation，页面仍显示“启用”和新的有效版本摘要

#### Scenario: 编辑已启用资源失败
- **WHEN** 新候选连接、Secret 或只读验证失败
- **THEN** 系统不替换 Last Known Good，页面显示启用状态、旧有效版本和脱敏失败摘要

#### Scenario: 停用资源
- **WHEN** 管理员确认停用一个启用资源
- **THEN** 系统阻止新 Job 和新 Tool Publication 解析该资源，同时保留历史版本、运行引用和审计

### Requirement: Resource 表单由服务端约束字段
系统 SHALL 按受信 Resource kind 提供固定安全字段和 Credential 选择项，并 MUST 在服务端校验 host、port、database/index、TLS、只读限制和 Resource kind。页面和 API MUST NOT 接受任意驱动、任意连接参数、密码明文或通用查询执行配置。

#### Scenario: 新建数据库 Resource
- **WHEN** 管理员选择受支持数据库类型、填写允许字段并选择可用 Credential
- **THEN** 系统只保存受控配置和内部 Credential 引用，验证通过前资源保持停用

#### Scenario: 提交未允许的连接参数
- **WHEN** 客户端提交任意驱动选项、连接字符串中的明文密码或通用 SQL 配置
- **THEN** 系统拒绝整个请求并记录不含敏感值的安全审计

### Requirement: Credential 页面永不回显敏感材料
系统 SHALL 提供 Credential 创建、轮换、停用和用途查看，并 MUST 只返回稳定标识、名称、kind、版本、状态、更新时间和用途摘要。页面及浏览器 API MUST NOT 返回明文、密文、nonce、认证标签、Master Key 或可复制的内部 Secret Ref。

#### Scenario: 创建 Credential
- **WHEN** 有权限管理员通过受保护请求提交 Credential 明文
- **THEN** 后端在持久化前加密，响应只返回安全元数据且页面不提供再次查看明文的入口

#### Scenario: 停用在用 Credential
- **WHEN** Credential 仍被启用 Resource 或活动 Publication 使用
- **THEN** 系统拒绝直接停用并返回受影响对象摘要，不泄露内部 Secret Ref

### Requirement: MCP 配置写操作必须统一治理
所有 MCP Tool、Resource 和 Credential 写操作 SHALL 要求有效 Session、CSRF、对应代码拥有权限、expected revision 或版本、幂等键和安全审计。健康检查和失败响应 MUST 脱敏，并 MUST NOT 改写当前有效运行快照。

#### Scenario: 过期 revision 修改 MCP 配置
- **WHEN** 管理员使用过期 revision 编辑 Tool Publication 或 Resource
- **THEN** 系统返回冲突、保持当前事实不变并要求页面刷新

#### Scenario: 健康检查失败
- **WHEN** 管理员触发受控 Server 或 Resource 健康检查且检查失败
- **THEN** 系统只更新脱敏健康事实，不自动删除、停用或替换 Last Known Good

