## ADDED Requirements

### Requirement: 管理API受统一身份和应用级权限保护
系统 SHALL 复用现有Web Session、RBAC和CSRF保护Business Application管理API，并 MUST 使用`business_application`资源及read、create、edit、publish、activate动作进行授权。

#### Scenario: 有权用户读取应用
- **WHEN** 已认证内部用户具有目标项目或应用的read权限
- **THEN** API返回其可见的业务应用列表和详情
- **AND** 不返回无权访问应用的摘要

#### Scenario: 未授权用户访问具体应用
- **WHEN** 用户无权读取指定应用
- **THEN** API返回404或等效防枚举结果
- **AND** 审计记录拒绝原因但不泄露应用内容

#### Scenario: 缺少CSRF执行写操作
- **WHEN** 已登录用户创建、编辑、发布、激活或停用应用但请求缺少有效CSRF
- **THEN** 系统拒绝请求且不产生控制面变更

### Requirement: 管理API覆盖业务应用完整控制面生命周期
系统 SHALL 提供应用列表、详情、创建、元数据更新、草稿保存、校验、发布、发布历史、环境激活、环境停用和effective配置查询接口。

#### Scenario: 创建并发布应用
- **WHEN** 有权限用户依次创建应用、保存合法草稿、校验并发布
- **THEN** 每个接口返回明确的应用、revision、validation或publication资源
- **AND** 响应包含下一步所需的revision与完整性摘要

#### Scenario: 查询应用详情
- **WHEN** 用户读取业务应用详情
- **THEN** API返回稳定定义、最新草稿、校验结果、publication历史、各环境deployment和`runtime_wired`状态
- **AND** 不返回组件内部Secret或底层连接信息

#### Scenario: 请求包含未知字段
- **WHEN** 创建或编辑请求包含协议未定义字段
- **THEN** API返回422并拒绝整个请求

### Requirement: 管理API提供稳定的并发与错误契约
系统 MUST 使用expected revision处理所有可变资源，并 SHALL 区分validation、conflict、forbidden、not found和integrity错误。

#### Scenario: 草稿revision冲突
- **WHEN** 客户端使用过期expected revision保存草稿
- **THEN** API返回409和当前revision的非敏感摘要
- **AND** 客户端能够刷新后人工合并而不是静默覆盖

#### Scenario: 发布校验失败
- **WHEN** 用户发布存在多个组件或策略错误的草稿
- **THEN** API返回可定位到字段、binding或组件的全部安全错误
- **AND** 不只返回首个错误或内部堆栈

### Requirement: Web提供真实的业务应用列表与详情工作区
系统 SHALL 将“业务应用”导航连接到真实列表和详情页面，并 MUST 使用管理API数据替换该区域的静态应用fixture。

#### Scenario: 查看业务应用列表
- **WHEN** 已有管理会话的用户进入业务应用
- **THEN** 页面展示真实应用名称、编码、项目、状态、最新revision、publication和环境激活摘要
- **AND** 提供清晰的加载、空数据和错误状态

#### Scenario: 查看业务应用详情
- **WHEN** 用户选择一个可见应用
- **THEN** 页面展示概览、组成配置、校验结果、发布历史和环境状态
- **AND** 流程设计只展示被引用Workflow Publication及尚未提供画布的说明

#### Scenario: 前端未登录
- **WHEN** 管理API返回401
- **THEN** 页面显示需要现有管理会话的明确状态
- **AND** 不显示虚构业务应用、模拟成功数据或本变更内的登录表单

### Requirement: Web支持受控的应用编辑、校验和发布
系统 SHALL 为有权限用户提供严格表单来创建应用、编辑草稿、请求校验、发布和管理环境激活，并 MUST 根据权限、revision和校验结果控制动作可用性。

#### Scenario: 保存应用草稿
- **WHEN** 用户选择合法Agent Publication、Workflow Publication、Trigger、Delivery和策略并提交
- **THEN** 页面发送当前expected revision并展示服务器返回的新revision
- **AND** 页面不会将Secret、底层URL或任意工具配置提交给API

#### Scenario: 校验失败后修正
- **WHEN** API返回字段和组件校验错误
- **THEN** 页面在对应配置区域展示错误并保留用户可安全重试的输入
- **AND** 发布和激活动作保持禁用

#### Scenario: 发布但尚未运行时接线
- **WHEN** 用户成功发布或激活应用
- **THEN** 页面更新publication与deployment状态
- **AND** 明确提示该基础版本尚未接管钉钉或Webhook运行时

### Requirement: Capability和数据源安全边界在真实页面中保持有效
系统 MUST 只展示受目录治理的API Capability引用，第一版在目录未接入时 MUST 禁止录入任意Capability、HTTP、SQL、Redis命令、LogQL、Shell和底层连接配置。

#### Scenario: 查看Capability组成区域
- **WHEN** 用户查看或编辑应用组成
- **THEN** 页面显示Capability目录尚未接入和当前列表为空的状态
- **AND** 不提供自由文本URL、SQL、Redis、Loki或工具名输入框

#### Scenario: 查看Channel和Delivery引用
- **WHEN** 页面展示需要凭据的connector
- **THEN** 只显示connector名称、ID、方向和配置状态
- **AND** 不显示Secret URI解析结果、Token、密码或完整Webhook URL

### Requirement: 业务应用工作区满足响应式和可访问性要求
系统 SHALL 在桌面和窄屏下保持列表、详情、表单、校验错误、版本历史和环境状态可读，并 MUST 为状态、禁用原因和异步操作提供文本语义。

#### Scenario: 窄屏编辑应用
- **WHEN** 用户在窄屏查看详情或表单
- **THEN** 页面使用单列或可滚动局部区域保持字段和操作可访问
- **AND** 不出现阻止整体阅读的横向页面溢出

#### Scenario: 键盘和辅助技术操作
- **WHEN** 用户通过键盘或辅助技术浏览、提交或查看错误
- **THEN** 表单标签、状态、错误摘要、按钮和禁用原因具有可理解名称
- **AND** 关键状态不只通过颜色表达
