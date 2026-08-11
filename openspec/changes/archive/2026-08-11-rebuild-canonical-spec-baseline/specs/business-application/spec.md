## ADDED Requirements

<!-- Migrated from canonical source capability: `api-capability-publication-composition` -->

### Requirement: ACTIVE Release 进入 Agent 和 Application 配置目录
系统 SHALL 把可供新配置使用的 `ACTIVE` Capability Release 投影到 Agent 和 Application 管理目录，并 MUST 展示名称、稳定 Identifier、业务 `description`、Release Revision 和运维状态；管理端 MAY 展示 `release_note`，模型上下文 MUST NOT 包含该字段。

#### Scenario: 管理员配置 Agent
- **WHEN** 目录存在多个 `ACTIVE` Release
- **THEN** 界面默认推荐最新 Release，并允许管理员展开选择仍为 ACTIVE 的旧 Release

#### Scenario: 目录包含 DEPRECATED Release
- **WHEN** 某 Release 已软废弃且已有配置仍引用它
- **THEN** 历史引用处显示警告和可用替代信息，但新配置候选列表不得允许选择它

### Requirement: Agent Publication 冻结精确 Capability Envelope
Agent Draft SHALL 对同一 Capability Identifier 至多选择一个精确 `ACTIVE` Release；Agent Publish MUST 将 Identifier、Release ID、Capability/Handler Revision、公开 Schema hash 和业务描述冻结为不可变 Agent Capability Envelope。

#### Scenario: Agent 选择一个 Capability Release
- **WHEN** 管理员保存并发布选择了 `cap__ones__work_item__search` 某一 ACTIVE Release 的 Agent
- **THEN** Agent Publication 冻结该精确 Release而不跟随后续新版本

#### Scenario: Agent 对同一 Identifier 选择两个 Release
- **WHEN** Agent Draft 包含同一 Identifier 的多个 Release
- **THEN** 系统拒绝保存或发布并指出冲突项

#### Scenario: 发布时 Release 已不再 ACTIVE
- **WHEN** Draft 保存后目标 Release 被废弃、禁用或归档
- **THEN** Agent Publish 重新校验并失败关闭

### Requirement: Application Capability Allowlist 只能是 Agent Envelope 子集
Application Draft MUST 引用精确 Agent Publication，并 SHALL 只允许从该 Publication 的 Agent Capability Envelope 中显式选择 Capability Release 子集；后端 MUST 拒绝任何越过 Agent 上限、替换 Release ID 或自行指定版本的请求。

#### Scenario: 应用选择 Agent 已有能力
- **WHEN** 管理员勾选所选 Agent Publication 中的一部分 Capability
- **THEN** Application Publication 冻结精确子集为 Application Capability Allowlist

#### Scenario: Agent 未选择 Capability
- **WHEN** 应用请求配置 Agent Envelope 中不存在的 Identifier
- **THEN** 系统拒绝保存或发布，应用界面也不得提供该候选

#### Scenario: 应用未选择 Capability
- **WHEN** Agent Envelope 包含某 Release但 Application Allowlist 未包含它
- **THEN** 该 Capability 不得进入该应用的模型 Tool Catalog或执行路径

### Requirement: Application 不独立选择 Capability 版本
Application 配置界面 MUST 直接展示所选 Agent Publication 冻结的精确 Capability Release，且 MUST NOT 提供独立版本选择器或自动解析“最新版本”。

#### Scenario: 应用查看 Agent Capability
- **WHEN** 管理员选择一个精确 Agent Publication
- **THEN** 每个应用候选显示 Agent 已冻结的 Release Revision，管理员只能勾选或取消

#### Scenario: 新 Capability Release 发布
- **WHEN** 相同 Identifier 发布更高 Release Revision
- **THEN** 既有 Agent/Application Draft 与 Publication 均不自动切换

### Requirement: Agent 升级时重新验证应用能力子集
应用切换到新的 Agent Publication 时 MUST 重新校验原 Application Capability Allowlist；若新 Agent 缺少原 Capability、只含 DEPRECATED Release 或公开 Schema 不兼容，系统 MUST 阻止应用发布并要求管理员显式替换或移除。

#### Scenario: 新 Agent 保留兼容 Release
- **WHEN** 应用升级 Agent 且原能力子集在新 Envelope 中存在兼容 ACTIVE Release，并由管理员明确选择
- **THEN** 系统允许创建新的 Application Publication

#### Scenario: 新 Agent 移除原能力
- **WHEN** 新 Agent Envelope 不再包含应用原来选择的 Identifier
- **THEN** 系统阻止发布，不静默删除 Application Allowlist 项

#### Scenario: 新 Agent 只有软废弃版本
- **WHEN** 新 Agent 引用路径只能提供 DEPRECATED Release
- **THEN** 系统阻止新的应用升级并显示替换或移除要求

### Requirement: 既有 Publication 不跟随配置变化
Agent、Application 和 Capability 新发布、软废弃或替代关系 MUST NOT 自动改写既有 Agent/Application Publication；只有管理员显式创建并发布新版本才能升级绑定。

#### Scenario: Agent 发布新版本
- **WHEN** 现有应用仍引用旧 Agent Publication
- **THEN** 应用继续使用旧 Agent Capability Envelope 和 Allowlist

#### Scenario: Capability 设置 replacement
- **WHEN** DEPRECATED Release 指向新的 replacement_release_id
- **THEN** 既有应用不自动替换，管理员必须显式升级并重新发布

### Requirement: 钉钉应用访问不新增 Capability 用户角色 Grant
第一版钉钉 Application Access SHALL 来自消息路由命中绑定活动 Application Publication 的连接器以及实际发送人解析为启用内部用户；该访问资格同时给出 Application Capability Allowlist 的运行资格，系统 MUST NOT 再要求逐用户或逐角色 Capability Code `use` Grant。

#### Scenario: 启用用户命中活动应用
- **WHEN** 钉钉消息由已绑定且启用的内部用户发送，并命中活动应用路由
- **THEN** 用户取得该应用 Allowlist 的候选调用资格，仍须通过 Release、身份、Team 和 Token 校验

#### Scenario: 用户没有 Capability 角色 Grant
- **WHEN** 用户满足钉钉应用访问条件但系统不存在 Capability `use` Grant
- **THEN** 系统不得仅因缺少该 Grant 拒绝已允许的 Capability

#### Scenario: 其他 Trigger 类型访问
- **WHEN** 请求来自非钉钉 Trigger
- **THEN** 系统继续使用该 Trigger 已定义的访问策略，不把钉钉规则扩展为全局规则

### Requirement: 发布链替代全局功能开关
受治理 Capability 只有依次完成 Connection、Capability Release、Agent Publication 和 Application Publication 的显式发布后才能进入运行时；系统 MUST NOT 为该功能新增全局 Feature Flag 或功能开关页面。

#### Scenario: Capability 已发布但应用未选择
- **WHEN** Release 为 ACTIVE 但没有活动 Application Publication允许它
- **THEN** 现有运行时行为不变，模型无法看到或调用该 Capability

#### Scenario: 需要紧急停止
- **WHEN** 运维人员需要阻止某 Capability 的新调用
- **THEN** 使用具体 Release 的 `DISABLED` 状态失败关闭，不删除历史或切换全局开关

### Requirement: Release 状态对选择和历史运行具有确定语义
`DEPRECATED` Release SHALL 允许既有 Application Publication继续执行但阻止新 Agent/Application 选择与升级；`DISABLED` 和 `ARCHIVED` Release MUST 阻止所有新调用；系统 MUST NOT 按日期自动禁用或自动升级。

#### Scenario: 既有应用调用 DEPRECATED Release
- **WHEN** 历史 Application Publication 已冻结一个后来 DEPRECATED 的 Release
- **THEN** 运行时仍可暴露和执行，并在管理端显示废弃警告

#### Scenario: 既有应用调用 DISABLED Release
- **WHEN** 历史 Application Publication 冻结的 Release 已被 DISABLED
- **THEN** Tool 构建或执行失败关闭并记录安全状态原因


<!-- Migrated from canonical source capability: `application-tool-resource-composition` -->

### Requirement: Agent Publication 必须冻结精确内置工具 Envelope
Agent Draft SHALL 对同一稳定 Tool Identifier 至多选择一个 `ACTIVE` Built-in Tool Release；Agent Publish MUST 冻结 Tool Release ID、Handler Version、Implementation Digest、公开 Schema Hash 和模型描述，不得保存名称级或 `latest` 引用。

#### Scenario: Agent 发布精确工具版本
- **WHEN** 管理员发布选择了一个 ACTIVE Tool Release 的 Agent Draft
- **THEN** 新 Agent Publication 包含该精确 Tool Envelope，后续新 Release 不会自动替换它

#### Scenario: 同一 Identifier 选择多个版本
- **WHEN** Agent Draft 对同一稳定 Identifier 选择两个 Tool Release
- **THEN** 系统拒绝保存或发布并指出冲突项

#### Scenario: 发布时 Release 已失效
- **WHEN** Draft 保存后目标 Release 变为 DEPRECATED、DISABLED、ARCHIVED 或精确实现不再 INSTALLED
- **THEN** Agent Publish 重新校验并失败关闭

### Requirement: Application Publication 只能冻结 Agent Tool Envelope 的显式子集
Application Draft MUST 引用精确 Agent Publication，并 SHALL 只允许显式选择该 Publication 中的 Built-in Tool Release 子集；Application Publish MUST 冻结该子集且不得自动继承、替换或独立选择版本。

#### Scenario: 应用选择 Agent 已有工具
- **WHEN** 管理员勾选 Agent Tool Envelope 中的一部分 Tool Release
- **THEN** Application Publication 冻结精确 Application Tool Allowlist

#### Scenario: 应用请求 Agent 未包含工具
- **WHEN** 请求包含 Agent Tool Envelope 中不存在的 Identifier 或不同 Release ID
- **THEN** 后端拒绝保存或发布，前端也不得提供该候选

#### Scenario: Agent 发布新版本
- **WHEN** 同一 Agent 后续发布了新的 Tool Envelope
- **THEN** 既有 Application Draft 和 Publication 不自动切换，必须显式升级并重新校验

### Requirement: 一个逻辑资源槽必须支持 1..N 条精确资源映射
Application Publication SHALL 为每个被选工具的必需逻辑资源槽冻结一条或多条 Mapping；每条 Mapping MUST 包含业务目标 scope、可选 placement、精确 Resource Revision，以及适用时的 Partition Policy Revision 或 Loki Scope Policy Revision。

#### Scenario: 基地数据库服务多个车间
- **WHEN** 一个基地级数据库 Resource Revision 绑定到包含 GL001、GL002、GL003 的应用目标
- **THEN** 同一资源映射可由三个车间继承，但每个车间必须冻结自己的 Partition Policy Revision

#### Scenario: 同一基地同时有云边资源
- **WHEN** 应用为同一数据库 slot 和基地配置 cloud 与 edge 两个 Resource Revision
- **THEN** Publication 保存两条 placement 不同的精确 Mapping，不创建伪基地或伪车间

#### Scenario: 环境没有 placement
- **WHEN** 目标资源没有云边区分
- **THEN** Mapping 的 placement 必须缺省，提交 `none`、`default` 或其它占位值时发布失败

### Requirement: Application Draft 必须显式声明有限叶子目标
Application Draft SHALL 显式保存允许执行的真实叶子 `target_paths`，每条路径 MUST 是当前启用的 Environment leaf、Base leaf 或 Workshop leaf；系统 MUST NOT 从 Resource Mapping、角色 Grant 或当前 topology 全量反向推导应用目标。

#### Scenario: 显式选择 GL001 和 GL002
- **WHEN** 管理员把 `sanjiu/guanlan/GL001` 与 `sanjiu/guanlan/GL002` 保存为应用目标
- **THEN** Draft 冻结两个精确 topology 目标，发布器只为这两个目标展开资源矩阵

#### Scenario: 选择仍有 Workshop 的 Base
- **WHEN** 管理员把仍包含启用 Workshop 的 Base 作为叶子目标提交
- **THEN** 系统拒绝保存并要求选择实际 Workshop 叶子

#### Scenario: Mapping 指向清单外目标
- **WHEN** Resource Mapping 不覆盖任何显式 `target_paths` 或试图隐式增加目标
- **THEN** Application Publish 拒绝且不扩大应用目标范围

#### Scenario: Topology 后续新增叶子
- **WHEN** Application Publication 发布后同一 Base 新增 Workshop
- **THEN** 新 Workshop 不自动进入既有 Publication，必须显式更新 Draft 目标并重新发布

### Requirement: Application Publish 必须证明每个有效组合唯一可解析
发布器 MUST 展开所有已选工具、必需资源槽、Application Draft 显式声明的有限叶子目标和已配置 placement，并验证每个有效组合恰好命中一个 Mapping；零命中、多个命中、范围重叠、策略不匹配或非 Published 依赖均 MUST 阻止发布。

#### Scenario: 必需资源缺失
- **WHEN** 某 Workshop 的数据库 slot 没有可继承的 Published Resource Revision
- **THEN** Application Publish 拒绝并返回缺失的工具、slot 和目标摘要

#### Scenario: 环境与基地映射重叠
- **WHEN** 同一 slot 和 placement 的环境级与基地级 Mapping 会同时覆盖同一个有效叶子目标
- **THEN** Application Publish 以歧义拒绝，不采用最近父级或优先级规则

#### Scenario: Loki global 与 environment 重叠
- **WHEN** 同一应用的一个环境同时命中 global Loki 和 environment Loki Mapping
- **THEN** Application Publish 拒绝该组合

### Requirement: Application Publication 必须冻结完整解析表
系统 SHALL 在发布时持久化规范化且不可变的目标解析表及内容 Hash，包含 Tool Release、slot、目标、placement、Resource Revision 和策略 revision；运行时 MUST 读取该表而不得查询 Resource Identity 的最新版本。

#### Scenario: Resource 发布新 revision
- **WHEN** Resource Identity 后续发布新 revision，但应用没有重新发布
- **THEN** 既有应用和新建 Job 继续使用 Application Publication 冻结的旧 revision

#### Scenario: Policy 发布新 revision
- **WHEN** Workshop Partition Policy 或 Loki Scope Policy 发布新 revision
- **THEN** 既有 Application Publication 不自动切换

### Requirement: Job 必须复制不可变 Tool Execution Snapshot
Job 创建时 MUST 从活动 Application Publication 复制 Agent Publication ID、Tool Release ID、Handler Version、Implementation Digest、目标路径、可用 placements、全部 Resource Mapping、Partition Policy 与 Loki Scope Policy 的 ID/revision/hash，以及授权事实摘要。

#### Scenario: 新 Job 创建成功
- **WHEN** 入站请求命中一个可执行的 Application Publication 和合法业务目标
- **THEN** 系统在分发前持久化完整 Tool Execution Snapshot

#### Scenario: Job 重试期间配置改变
- **WHEN** Job 首次执行后 Tool Release、Resource 或 Policy 发布了新版本
- **THEN** 重试仍使用原 Snapshot，不能浮动到新版本

#### Scenario: 冻结 Release 被禁用
- **WHEN** Job 重试前其冻结 Tool Release 变为 DISABLED 或 ARCHIVED
- **THEN** 重试按生命周期失败关闭，不得替换为其他 ACTIVE Release

### Requirement: 每次 Tool Call 必须解析一个明确 placement
当 Job Snapshot 为目标保存多个 placement 时，每次 Tool Call MUST 通过受控调用参数或确定性系统路由选择恰好一个 placement，并记录选择；Agent 不得借此改变业务目标或权限范围。

#### Scenario: 目标只有一个 placement
- **WHEN** 某 slot 对 Job 目标仅有 cloud Mapping
- **THEN** 运行时选择 cloud 并记录实际 Resource Revision

#### Scenario: 目标有 cloud 和 edge
- **WHEN** 某 slot 对同一目标同时有 cloud 和 edge Mapping 且调用明确请求其中一个允许值
- **THEN** 运行时只使用该 placement 的精确 Resource Revision

#### Scenario: 多 placement 未明确选择
- **WHEN** 候选包含 cloud 和 edge 但调用与系统路由无法唯一确定一个
- **THEN** 运行时在访问上游前失败关闭，不默认选择 cloud、edge 或第一条

### Requirement: 可调用工具必须满足完整治理交集
运行时 MUST 只暴露并执行同时满足精确实现已安装、Release 可调用、Agent Envelope、Application Allowlist、稳定工具使用授权、业务目标授权、精确资源映射和有效策略的工具。

#### Scenario: 任一交集条件缺失
- **WHEN** Tool Release 已发布但用户没有目标 Workshop 权限或资源映射无效
- **THEN** 模型不得获得该可调用 Tool 定义，直接调用也必须被 Internal API Platform 拒绝

#### Scenario: Agent 伪造资源事实
- **WHEN** Tool 请求尝试覆盖 Resource Revision、tenant、table prefix、Redis prefix 或强制 Loki selector
- **THEN** Internal API Platform 使用 Job Snapshot 中的事实并拒绝冲突输入

### Requirement: Tool Call 审计必须记录精确事实且不含 Secret
系统 SHALL 记录 Job、Application Publication、Tool Release、Handler Version、Implementation Digest、业务目标、实际 placement、Resource Revision、Policy Revision、有效范围 Hash、判定结果和 correlation id；MUST NOT 记录凭据、连接明文或无界业务响应。

#### Scenario: 工具调用成功
- **WHEN** 一个 DB、Redis 或 Loki Tool Call 成功完成
- **THEN** 审计能够还原所用精确版本和范围，同时结果正文只保留有界脱敏摘要

#### Scenario: 资源解析歧义
- **WHEN** 运行时检测到零个或多个候选 Mapping
- **THEN** 系统记录安全的解析原因和候选数量，不记录 endpoint、username 或 Secret 值


<!-- Migrated from canonical source capability: `business-application-admin-workbench` -->

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


<!-- Migrated from canonical source capability: `business-application-control-plane` -->

### Requirement: 系统持久化稳定的业务应用聚合
系统 SHALL 为每个 Business Application 持久化唯一编码、名称、描述、项目范围、负责人、生命周期状态和当前修订信息，并 MUST 将业务应用作为 Agent、Workflow、Channel 和未来 API Capability 的装配边界。

#### Scenario: 创建业务应用
- **WHEN** 有创建权限的内部用户提交合法且未被占用的应用编码、名称和项目范围
- **THEN** 系统创建稳定的业务应用定义和初始草稿修订
- **AND** 创建操作不会启动 Agent Job 或修改任何入口路由

#### Scenario: 重复应用编码
- **WHEN** 用户创建的应用编码已经存在
- **THEN** 系统拒绝创建并返回可识别的冲突错误
- **AND** 已存在应用及其草稿保持不变

### Requirement: 业务应用通过草稿修订装配版本化组件
系统 SHALL 使用草稿修订保存一个 Agent Publication、零个或一个 Workflow Publication、Trigger Binding、Delivery Binding、会话策略、执行策略和 API Capability 引用，并 MUST NOT 直接引用可变的 Agent 或 Workflow 草稿。

#### Scenario: 保存完整应用草稿
- **WHEN** 用户为业务应用选择已发布 Agent、已发布 Workflow、合法 Trigger 和 Delivery，并保存策略
- **THEN** 系统创建新的应用草稿 revision 并保存各组件的稳定引用
- **AND** 先前 revision 的内容保持不变

#### Scenario: 尝试引用组件草稿
- **WHEN** 用户提交 Agent Revision 或 Workflow 草稿而不是 Publication
- **THEN** 系统拒绝该引用并返回对应字段错误

#### Scenario: Capability目录尚未接入
- **WHEN** 应用草稿包含非空 API Capability 编码而当前没有可解析的 Capability Catalog
- **THEN** 系统可以保存该草稿引用用于后续补全
- **AND** 系统 MUST 在发布校验中将其标记为未解析并阻止发布

### Requirement: 应用策略采用严格的受控结构
系统 SHALL 对 Trigger、Actor、Session、Execution 和 Delivery 策略执行严格 schema 校验，MUST 拒绝未知字段、未知枚举、越界限制、任意 URL、底层查询语言和敏感凭据。

#### Scenario: 保存钉钉当前发送人策略
- **WHEN** 钉钉 Trigger 使用 `CURRENT_SENDER` actor policy 并引用允许入口的 connector
- **THEN** 系统接受该受控策略并保存非敏感 connector 与路由标识

#### Scenario: 保存Webhook服务身份策略
- **WHEN** Webhook Trigger 使用 `SERVICE_ACCOUNT` actor policy
- **THEN** 系统要求引用一个已启用的内部服务主体
- **AND** 不允许在策略中直接提交外部系统用户名、密码或 Token

#### Scenario: 提交不安全配置
- **WHEN** 草稿包含数据库连接、Redis地址、Loki地址、SQL、LogQL、Shell、任意HTTP URL、Password、Secret或Token字段
- **THEN** 系统拒绝保存并返回安全的字段级校验错误
- **AND** 错误、日志和审计中不回显敏感值

### Requirement: 应用写入使用乐观并发控制
系统 MUST 要求应用元数据和草稿写请求携带预期 revision，并 SHALL 在预期 revision 与当前值不一致时拒绝覆盖。

#### Scenario: 更新最新草稿
- **WHEN** 用户提交的 expected revision 等于当前应用 revision
- **THEN** 系统原子创建下一草稿 revision 并返回新的 revision

#### Scenario: 两个管理员并发编辑
- **WHEN** 第二个管理员基于已经过期的 revision 保存应用
- **THEN** 系统返回冲突错误并包含当前 revision 的非敏感摘要
- **AND** 不覆盖第一个管理员已经保存的修改

### Requirement: 应用生命周期不删除历史事实
系统 SHALL 支持 enabled、disabled 和 archived 生命周期状态，MUST 保留草稿、发布快照、部署和审计历史，并 MUST 阻止 disabled 或 archived 应用的新发布和激活。

#### Scenario: 停用业务应用
- **WHEN** 有管理权限的用户将应用从 enabled 改为 disabled
- **THEN** 系统保留全部历史数据并拒绝后续发布或激活
- **AND** 已有环境 deployment 必须由显式停用操作处理，不进行隐式数据删除

#### Scenario: 归档业务应用
- **WHEN** 用户归档一个不存在活动 deployment 的业务应用
- **THEN** 系统将应用标记为 archived 并从默认可编辑列表中隐藏
- **AND** 历史查询仍可读取其 publication 和 audit

### Requirement: 控制面变更不自动改变现有数据面
系统 MUST 将业务应用草稿、发布和激活作为控制面配置管理，第一版 MUST NOT 自动修改钉钉入口、Webhook入口、Agent Job创建、RabbitMQ消费或Delivery路径。

#### Scenario: 发布并激活应用
- **WHEN** 管理员发布业务应用并在测试环境激活
- **THEN** 系统更新业务应用控制面数据和解析读模型
- **AND** 现有钉钉和Webhook消息仍沿用原默认Agent执行链路

#### Scenario: 查询应用运行时接线状态
- **WHEN** 管理端读取应用详情或激活结果
- **THEN** 响应明确返回当前 `runtime_wired=false` 或等效状态
- **AND** 不暗示该应用已经接管生产入口


<!-- Migrated from canonical source capability: `business-application-execution-policy` -->

### Requirement: 业务应用执行策略必须固定到Agent Job
系统 MUST 在业务应用路由命中且创建 Agent Job 前，从命中的 Business Application Publication 读取 `max_turns`、`timeout_seconds` 和 `max_tool_calls`，计算有效执行策略并把请求值、有效值、策略版本及来源 Publication 一并持久化到 Job。迁移后的每个新 Agent Job MUST 具有合法 v1 Execution Policy 快照；Worker MUST 只使用 Job 固定的策略，MUST NOT 在消费、重试或执行时重新解析当前活动 Deployment。

#### Scenario: 命中业务应用并创建Job
- **WHEN** 钉钉消息命中一个活动 Business Application Publication
- **THEN** Job 在发布到 RabbitMQ 前保存不可变的业务应用 Execution Policy 快照
- **AND** 快照记录 Business Application Publication、Agent Publication 和配置 hash 来源

#### Scenario: Job入队后激活新版本
- **WHEN** Job 已入队后管理员发布或激活了不同的业务应用策略
- **THEN** 已入队 Job 及其后续重试继续使用原固定策略
- **AND** 只有新创建的 Job 使用新策略

#### Scenario: 非业务应用入口创建Job
- **WHEN** 调试入口、普通 Agent 入口或其他非 Business Application 入口创建新 Job
- **THEN** Job 创建服务从固定 Agent Publication 或运行时默认值生成合法 v1 Execution Policy 快照
- **AND** 不允许持久化空策略 Job

#### Scenario: Worker遇到缺失策略的Job
- **WHEN** Worker 读取到缺少 v1 Execution Policy 快照或快照无法通过 schema 校验的 Job
- **THEN** 系统以不可重试的 Job 完整性错误停止执行
- **AND** 不使用 Agent Publication 或全局默认值在 Worker 阶段补齐策略

### Requirement: 有效执行策略必须确定且不能扩大Agent限制
系统 SHALL 以固定 Agent Publication 的执行限制为基础，对 `max_turns` 和 `timeout_seconds` 取业务应用请求值与 Agent 限制中的更严格值；Agent Publication 缺少对应值时 SHALL 使用现有运行时默认值。`max_tool_calls` SHALL 使用业务应用快照中的规范化值，并遵守现有字段范围。管理 API 和运行记录 MUST 同时区分请求值与有效值。

#### Scenario: 业务应用策略比Agent更严格
- **WHEN** Agent Publication 允许 `max_turns=20` 且业务应用请求 `max_turns=8`
- **THEN** Job 的有效 `max_turns` 为 `8`

#### Scenario: 业务应用策略比Agent更宽松
- **WHEN** Agent Publication 允许 `timeout_seconds=180` 且业务应用请求 `timeout_seconds=300`
- **THEN** Job 的有效 `timeout_seconds` 为 `180`
- **AND** 管理端能够看到请求值 `300` 和有效值 `180`

#### Scenario: 禁止所有工具调用
- **WHEN** 业务应用配置 `max_tool_calls=0`
- **THEN** Agent 可以生成不调用工具的答复
- **AND** 第一次内部工具调用在进入 ToolRegistry 前被策略拒绝

### Requirement: Worker必须强制执行三个策略字段
系统 MUST 对每次 Agent 执行 attempt 强制执行有效 `max_turns`、`timeout_seconds` 和 `max_tool_calls`。工具调用次数 SHALL 统计该 attempt 内所有进入内部 MCP 工具桥的成功或失败调用尝试，超过上限的调用 MUST NOT 进入 ToolRegistry 或任何下游数据源。

#### Scenario: 达到最大轮次
- **WHEN** Agent 执行达到固定的 `max_turns` 且未产生有效最终结果
- **THEN** 系统以稳定的最大轮次耗尽错误结束该 attempt
- **AND** 保留耗尽前已产生的安全工具事件

#### Scenario: 达到墙钟超时
- **WHEN** Agent attempt 超过固定的 `timeout_seconds`
- **THEN** 系统取消当前 SDK 执行并记录安全超时原因
- **AND** 后续是否重试继续遵守现有 timeout retry 策略及同一固定执行策略

#### Scenario: 超过最大工具调用数
- **WHEN** 当前 attempt 已使用完 `max_tool_calls`
- **THEN** 下一次工具调用以 `execution_policy_max_tool_calls_exhausted` 或等价稳定错误码终止
- **AND** 系统不调用 ToolRegistry、不访问数据库、Redis、Loki 或其他下游
- **AND** 该策略耗尽不得作为普通瞬时传输错误重试

### Requirement: 策略耗尽必须可审计并安全通知
系统 MUST 保存策略来源、有效值、实际工具调用次数、耗尽字段、Job 状态和安全错误码，并 SHALL 复用现有失败投递链把不含内部配置或敏感数据的提示回复到原钉钉会话。

#### Scenario: 工具调用预算耗尽
- **WHEN** Job 因 `max_tool_calls` 耗尽失败
- **THEN** 运行记录显示固定有效上限、已使用次数和稳定错误码
- **AND** 原钉钉会话收到安全失败提示
- **AND** 审计不包含 Secret、Token、完整工具响应或私有模型推理

#### Scenario: 查询成功Job的策略来源
- **WHEN** 管理员查看一个由业务应用创建并成功完成的 Job
- **THEN** 运行记录展示 Business Application Publication、Agent Publication、请求策略和有效策略

### Requirement: 接管状态必须区分同步关键路径和后台治理缺口
系统 SHALL 仅使用影响消息同步执行关键路径的组件计算 `runtime_status`，并 MUST 继续逐字段报告不在关键路径上的治理能力。Trigger routing、Agent Publication、会话上下文策略、Execution Policy、声明的 Workflow 以及 Delivery 属于同步关键路径；未实现的 `retention_days` 清理属于非阻塞后台治理缺口。

#### Scenario: 执行策略全部接线但retention未接线
- **WHEN** Trigger、Agent Publication、会话上下文、三个 Execution Policy 字段和 Delivery 均已执行，未配置 Workflow 或其他未支持的同步能力，但 `retention_days` 仍为 `stored_only`
- **THEN** `runtime_wired` 为 `true` 且整体 `runtime_status` 为 `wired`
- **AND** `retention_days` 继续显示 `stored_only` 和稳定 reason code
- **AND** 管理端显示非阻塞数据治理提示，不宣称已执行历史消息清理

#### Scenario: Execution Policy仍有字段未执行
- **WHEN** 任一已配置 Execution Policy 字段未被 Worker 强制执行
- **THEN** 整体 `runtime_status` 为 `partially_wired`
- **AND** 未执行字段明确显示 `stored_only`

#### Scenario: 已配置Workflow但没有执行引擎
- **WHEN** Publication 声明了 Workflow Publication 但运行时仍不执行 Workflow
- **THEN** Workflow 保持 `stored_only`
- **AND** 整体 `runtime_status` 保持 `partially_wired`

### Requirement: 本变更不得实现retention清理
系统 MUST NOT 因本变更新增按 `retention_days` 删除或归档会话、消息、摘要、附件、Job、工具调用或审计事件的 Worker、定时任务或队列。

#### Scenario: retention_days已经到期
- **WHEN** 某会话年龄超过其保存的 `retention_days`
- **THEN** 本变更不自动删除或归档该会话数据
- **AND** 管理端继续把该字段标记为尚未接线的治理能力

### Requirement: 迁移必须删除不兼容旧Job及关联运行数据
系统 MUST 在维护窗口中删除迁移前没有 v1 Execution Policy 快照的旧 Agent Job，并 MUST 同步清理依赖这些 Job 的 session、message、step、tool call、artifact、delivery、attachment、关联 Webhook 运行事件和 Job 级 audit 数据。系统 MUST 保留用户、外部身份、RBAC、Agent、Business Application、Publication、Deployment、Connector、Secret 和其他控制面配置。

#### Scenario: 测试数据库包含旧Job
- **WHEN** 执行本变更数据库迁移且现有 Agent Job 没有 v1 Execution Policy 快照
- **THEN** 系统按外键安全顺序删除旧 Job 及其关联运行数据
- **AND** 迁移结束后 `agent_job` 不存在缺少合法策略快照的记录

#### Scenario: 旧Job包含附件对象
- **WHEN** 被删除的旧 Job 关联 MinIO 中的附件或运行产物对象
- **THEN** 一次性维护清理流程删除对应对象和数据库元数据
- **AND** 不留下能够被新会话继续引用的孤儿附件

#### Scenario: 保留控制面配置
- **WHEN** 旧运行数据清理完成
- **THEN** 已配置用户、身份绑定、Agent Publication、Business Application Publication、local Deployment 和 Connector 仍然存在
- **AND** 管理员无需重新建立控制面配置


<!-- Migrated from canonical source capability: `business-application-publication` -->

### Requirement: 发布前执行跨组件完整校验
系统 MUST 在创建 Business Application Publication 前校验应用状态、草稿完整性、Agent Publication、Workflow Publication、Channel Connector、Trigger、Actor、Delivery、Capability、项目范围和策略约束。

#### Scenario: 发布合法草稿
- **WHEN** enabled应用的草稿引用有效且范围兼容的已发布组件，并且所有策略通过校验
- **THEN** 系统将该 revision 标记为校验通过并允许创建 publication

#### Scenario: 引用已禁用或不存在的组件
- **WHEN** 草稿引用不存在、已禁用、完整性校验失败或项目范围冲突的组件
- **THEN** 系统拒绝发布并返回按字段和组件分类的校验结果
- **AND** 不创建部分 publication

#### Scenario: 未解析Capability
- **WHEN** 草稿包含当前 Capability Catalog 无法解析的编码或版本
- **THEN** 系统拒绝发布并指出未解析的 Capability
- **AND** 不把该编码映射为现有数据库、Redis或Loki内部工具

### Requirement: 发布创建不可变且可验证的应用快照
系统 SHALL 为每次成功发布创建不可变 snapshot，冻结应用元数据、组件 Publication ID、组件 revision/version、组件 hash、Trigger、Delivery、Capability引用和策略，并 MUST 保存 snapshot schema version 与 canonical SHA-256。

#### Scenario: 创建应用发布快照
- **WHEN** 合法 revision 首次发布
- **THEN** 系统在单一事务中创建 publication、保存 snapshot 与 hash 并记录发布审计
- **AND** publication 关联其来源 revision 和发布主体

#### Scenario: 组件后续产生新版本
- **WHEN** 被引用 Agent 或 Workflow 后续发布新版本
- **THEN** 已有应用 publication 仍引用原 Publication ID、revision 和 hash
- **AND** 只有新的应用 revision 和 publication 才能采用新组件

#### Scenario: 检测快照篡改
- **WHEN** 读取 publication 时重新计算的 canonical hash 与保存值不一致或 schema version 不受支持
- **THEN** 系统拒绝解析、激活或返回其作为有效配置
- **AND** 记录不包含快照敏感内容的完整性失败审计

### Requirement: 发布与环境激活相互分离
系统 SHALL 允许 publication 在不影响任何环境的情况下创建，并 MUST 通过显式 deployment 操作将一个有效 publication 激活到指定环境。

#### Scenario: 仅发布不激活
- **WHEN** 管理员成功发布一个应用 revision
- **THEN** publication 出现在历史中但所有环境 deployment 保持原值
- **AND** Resolver 不会因为发布本身自动选择该版本

#### Scenario: 激活到测试环境
- **WHEN** 有 activate 权限的用户将有效 publication 激活到 test 环境并携带正确 expected revision
- **THEN** 系统原子更新该应用 test deployment
- **AND** production环境 deployment 不受影响

### Requirement: 环境激活拒绝Trigger路由冲突
系统 MUST 在激活时使用 environment、trigger type、connector ID 和规范化 routing key 检查所有活动 deployment，并 SHALL 拒绝导致非确定性路由的冲突。

#### Scenario: 激活唯一Trigger
- **WHEN** publication 的每个 Trigger 在目标环境都没有被其他活动应用占用
- **THEN** 系统允许激活并建立唯一解析投影

#### Scenario: 两个应用争用同一路由键
- **WHEN** 另一个已激活应用已经占用相同 environment、trigger type、connector ID 和 routing key
- **THEN** 系统拒绝激活并返回冲突应用的安全标识
- **AND** 目标环境现有 deployment 保持不变

### Requirement: Resolver确定性读取活动应用
系统 SHALL 提供按 application code 与 environment，以及按规范化Trigger键解析活动 publication 的只读端口，并 MUST 对停用、未激活、冲突和完整性失败返回明确配置错误。

#### Scenario: 按应用解析活动发布
- **WHEN** 调用方查询一个enabled应用在test环境的有效配置
- **THEN** Resolver返回唯一publication、Agent/Workflow引用、Trigger、Delivery、Capability引用、策略和完整性摘要
- **AND** 响应不包含Secret或外部系统凭据

#### Scenario: 按Trigger解析活动应用
- **WHEN** 调用方使用唯一的environment、trigger type、connector ID和routing key查询
- **THEN** Resolver返回唯一业务应用及其活动publication

#### Scenario: 没有有效部署
- **WHEN** 应用在目标环境未激活、已停用或publication完整性失败
- **THEN** Resolver返回非重试配置错误
- **AND** 不回退到任意其他业务应用

### Requirement: 历史publication可以显式重新激活
系统 SHALL 允许有权限的用户把仍然有效的历史 publication 重新激活到环境以实现回退，并 MUST 支持显式停用环境 deployment。

#### Scenario: 回退到历史版本
- **WHEN** 用户选择一个通过当前完整性和依赖校验的历史 publication 并激活
- **THEN** deployment原子指向该历史 publication
- **AND** 系统记录旧、新publication ID和操作人

#### Scenario: 停用环境部署
- **WHEN** 用户对当前deployment执行deactivate并提供正确expected revision
- **THEN** 系统将该环境标记为未激活并移除活动路由投影
- **AND** publication历史保持不变

### Requirement: 发布和解析过程不得保存或暴露凭据
系统 MUST 只在应用 snapshot、deployment、Resolver结果和审计中保存非敏感组件标识与Secret引用，MUST NOT 保存或返回真实密码、Token、Webhook Secret、完整敏感URL或底层数据源连接。

#### Scenario: 发布包含connector引用的应用
- **WHEN** 应用引用需要凭据的钉钉、Webhook或未来API平台connector
- **THEN** snapshot只保存connector ID和非敏感策略
- **AND** 凭据继续由connector或Credential边界解析

#### Scenario: 查看发布历史
- **WHEN** 管理员读取publication列表或详情
- **THEN** API返回版本、hash、组件引用、环境和审计摘要
- **AND** 不返回任何Secret值或可直接访问外部系统的认证材料


<!-- Migrated from canonical source capability: `business-application-role-access` -->

### Requirement: 业务应用是用户运行授权的入口对象
系统 SHALL 允许角色对具体业务应用授予 `invoke` 或等价使用能力。业务应用路由下命中的应用授权 MUST 封装该应用固定的项目和 Agent 运行入口许可，普通管理员不得再为同一路径手工组合项目和 Agent 使用权限。

#### Scenario: 用户通过角色获得应用访问
- **WHEN** 已绑定且启用的用户通过有效角色获得当前激活业务应用的使用权限
- **THEN** 系统允许继续检查该应用的能力和数据范围，而不要求额外配置底层项目和 Agent 使用策略

#### Scenario: 用户未获得应用访问
- **WHEN** 已绑定用户没有任何有效角色允许当前业务应用
- **THEN** 系统在创建 Agent job 前拒绝请求并返回“当前用户无权使用该业务应用”

### Requirement: 每个业务应用独立配置能力和数据范围
系统 SHALL 让角色在每个业务应用授权项下独立选择只读业务能力和环境、基地、车间范围。同一角色绑定多个业务应用时，一个应用的数据范围 MUST NOT 自动用于另一个应用。

#### Scenario: 同一角色的两个应用使用不同范围
- **WHEN** 角色为生产应用选择生产一号基地、为测试应用选择测试基地
- **THEN** 两个应用分别使用自己的能力和范围进行授权，不发生跨应用继承

### Requirement: 业务能力选择受多层安全上限约束
系统 SHALL 只允许角色选择同时满足“业务应用已装配、Agent publication 已允许、平台工具已启用、工具已注册且只读”的业务能力。任一上限后续收紧时 MUST 立即从有效能力集合中排除对应能力。

#### Scenario: 角色勾选未装配能力
- **WHEN** 客户端提交不属于目标业务应用装配集合的能力
- **THEN** 后端拒绝整个授权区提交

#### Scenario: Agent 移除已授权工具
- **WHEN** 新 Agent publication 不再允许角色曾经选择的工具
- **THEN** 该工具不再暴露给运行时，授权中心显示“被 Agent 安全上限阻止”

### Requirement: 当前全部保存明确资源集合
系统 SHALL 将管理员选择的“当前全部”展开为保存时存在的明确环境、基地或车间标识集合，不得创建包含未来新增资源的动态通配授权。

#### Scenario: 授权后新增基地
- **WHEN** 角色保存“当前全部基地”后平台新增一个基地
- **THEN** 新基地默认不属于该角色范围，管理员必须重新编辑角色才能授权

### Requirement: 多角色业务访问按应用合并
系统 SHALL 按当前业务应用合并用户全部有效角色的允许能力和明确数据范围，并 MUST 让高级拒绝优先。系统 MUST 保留每项有效访问的角色来源用于预览和审计。

#### Scenario: 多角色合并同一应用能力
- **WHEN** 一个角色允许日志能力，另一个角色允许数据库能力，且二者都允许同一应用
- **THEN** 用户在各自数据范围内获得两个能力，除非命中高级拒绝或其它安全上限

### Requirement: 平台管理员不隐式获得业务访问
系统 MUST 将管理后台全权限与业务应用使用权限分离。`platform-admin` 只有在另一个显式业务授权项允许时才能运行应用、调用能力或访问数据。

#### Scenario: 平台管理员仅管理授权
- **WHEN** `platform-admin` 未加入任何业务访问角色
- **THEN** 该用户可以创建和配置角色，但不能直接运行受保护业务应用

### Requirement: 旧原始策略仅作为受控兼容和高级例外
系统 SHALL 在独立身份授权重置 change 完成前保留现有用户/角色原始策略的安全兼容读取，不得删除或静默扩大旧策略。命中的应用级显式拒绝 MUST 阻止旧策略回退；新角色配置不得要求普通管理员理解旧策略。

#### Scenario: 旧用户尚未重新配置
- **WHEN** 用户尚无新业务应用授权但仍命中既有项目和 Agent 允许策略
- **THEN** 兼容模式可以保持其原有授权效果，并在授权解释中标记“旧策略兼容”

#### Scenario: 应用级拒绝存在
- **WHEN** 用户命中目标业务应用的高级拒绝
- **THEN** 系统拒绝访问，不得用旧项目或 Agent 允许策略绕过

### Requirement: 服务账号仅通过业务授权参与非交互式入口
系统 SHALL 允许服务账号通过业务访问角色获得 Webhook 等非交互式业务应用权限，但 MUST NOT 因该角色获得管理后台登录或功能权限。

#### Scenario: Webhook 服务账号有业务角色
- **WHEN** Webhook 触发器的启用服务账号获得目标业务应用、能力和数据范围授权
- **THEN** 系统按该服务账号的角色执行应用授权和工具范围检查


<!-- Migrated from canonical source capability: `business-application-runtime-routing` -->

### Requirement: 应用部署只使用local且与业务数据环境相互独立
系统 MUST 只允许创建、激活、回退、查询或停用 `local` Business Application Deployment，并 MUST NOT 使用 Channel event 的业务数据 `routing.environment` 选择应用版本。

#### Scenario: 本地运行时处理三九数据范围
- **WHEN** 服务运行于 `APP_ENV=local` 且钉钉事件的 `routing.environment` 为 `sanjiu`
- **THEN** 系统只查询该应用的 `local` Deployment
- **AND** `sanjiu` 原样保留在 Agent Job 的业务 routing context 中

#### Scenario: 管理端请求非local部署
- **WHEN** 管理端请求 `test`、`staging`、`production` 或其他非 `local` Deployment
- **THEN** 管理 API 拒绝请求并返回 `environment` 字段错误
- **AND** 系统不创建 Deployment 或 route 投影

### Requirement: 系统返回统一且真实的运行时接线状态
系统 SHALL 由单一运行时就绪评估器计算 `runtime_wired`、整体 `runtime_status` 和逐组件状态，并 MUST 在应用列表、详情、Publication、Deployment、effective 查询、激活响应和审计中使用同一结果。

#### Scenario: 当前环境存在可执行钉钉路由
- **WHEN** 数据面闸门开启，当前部署环境存在完整且受支持的活动钉钉 route
- **THEN** `runtime_wired` 为 `true`
- **AND** Trigger routing、Agent Publication、Session Policy 和 Delivery 分别返回其真实组件状态

#### Scenario: 只有部分配置已接线
- **WHEN** 钉钉路由可以执行但 Workflow 或 Execution Policy 字段仍只被存储
- **THEN** 整体状态为 `partially_wired`
- **AND** 未执行字段返回 `stored_only` 及稳定 reason code

#### Scenario: 活动路由完整性失败
- **WHEN** 当前环境的活动 route 指向 hash 不一致、schema 不支持或依赖缺失的 Publication
- **THEN** 整体状态为 `blocked`
- **AND** 系统不得把该应用显示为已完整接管

#### Scenario: 数据面闸门关闭
- **WHEN** `FEATURE_PUBLISHED_AGENT_RUNTIME` 关闭
- **THEN** `runtime_wired` 为 `false` 且整体状态为 `not_wired`
- **AND** 响应明确指出数据面闸门未开启

### Requirement: 第一阶段运行时只接管受支持的钉钉Trigger
系统 MUST 只将 `dingtalk_private + CURRENT_SENDER` 和 `dingtalk_group + CURRENT_SENDER` 标记为第一阶段可执行 Trigger，并 SHALL 将 Webhook、Workflow 和 API Capability 等未接线路径明确标记为 `stored_only` 或 `unsupported`。

#### Scenario: 评估钉钉私聊应用
- **WHEN** Publication 包含合法 `dingtalk_private` Trigger 和当前发送人 actor policy
- **THEN** 运行时就绪评估器按钉钉私聊支持矩阵校验该 Trigger

#### Scenario: 评估Webhook Trigger
- **WHEN** Publication 包含 Webhook Trigger
- **THEN** 本变更不让 Business Application Resolver 接管该 Webhook
- **AND** 管理端状态明确为 `stored_only` 而不是已生效

#### Scenario: Publication包含非空Capability
- **WHEN** 应用引用尚未接入目录的 API Capability
- **THEN** 现有发布校验继续阻止发布
- **AND** 系统不得将其映射为数据库、Redis、Loki 或其他内部工具

### Requirement: 活动路由解析是确定性的三态结果
系统 SHALL 将运行时路由解析结果建模为 `matched`、`not_matched` 或 `blocked`，并 MUST 使用部署环境、Trigger type、受信 connector ID 和规范化 routing key 唯一解析活动应用。

#### Scenario: 唯一路由命中
- **WHEN** 当前环境存在唯一且完整的活动 route 与事件规范化路由键相同
- **THEN** Resolver 返回 `matched`、应用、Publication、Deployment、route 和逐组件状态

#### Scenario: 没有活动路由
- **WHEN** 当前环境不存在与事件匹配的活动 route
- **THEN** Resolver 返回 `not_matched`
- **AND** 不把“没有匹配”表示为完整性异常

#### Scenario: 命中路由但Publication损坏
- **WHEN** route 投影存在但关联 Publication 无法通过 schema、hash 或引用完整性校验
- **THEN** Resolver 返回 `blocked` 和安全 reason code
- **AND** 不返回其他业务应用或默认 Agent 作为匹配结果

### Requirement: 未命中和命中后异常均失败关闭
系统 MUST 对 `not_matched` 和 `blocked` 的钉钉事件停止 Job 创建与 MQ 发布、记录审计并触发安全失败通知，MUST NOT 使用默认 Agent 兼容路径。

#### Scenario: 未配置业务应用路由
- **WHEN** 合法钉钉消息的路由结果为 `not_matched`
- **THEN** 系统不创建 Agent Job 或发布 RabbitMQ 消息
- **AND** 记录 `business_application.route.not_matched`
- **AND** 钉钉用户收到“当前机器人未配置可用的业务应用，请联系管理员”

#### Scenario: 已匹配应用配置无效
- **WHEN** 合法钉钉消息命中 route 但运行时结果为 `blocked`
- **THEN** 系统不创建 Agent Job
- **AND** 不静默回退到默认 Agent 或其他应用
- **AND** 钉钉用户收到不含敏感细节的错误通知

### Requirement: 命中应用后固定不可变运行版本
系统 MUST 以命中的 Business Application Publication 固定 Agent Publication 和所有已支持策略，MUST NOT 允许 Channel event、后续激活或 Worker 重新解析覆盖已经固定的版本。

#### Scenario: 入口携带相同Agent Publication
- **WHEN** 命中应用且事件携带的 Agent Publication 与应用快照完全一致
- **THEN** 系统使用应用快照版本创建 Job并记录一致性来源

#### Scenario: 入口尝试覆盖Agent Publication
- **WHEN** 命中应用但事件携带不同 Agent Publication、revision 或 hash
- **THEN** 系统将路由标记为 `blocked/agent_override_conflict`
- **AND** 不创建使用任一冲突版本的 Job

#### Scenario: Job入队后激活新版本
- **WHEN** Job 已固定 Publication 并入队，管理员随后激活新应用 Publication
- **THEN** 已入队 Job 继续使用原固定版本
- **AND** 后续新事件才解析到新版本

### Requirement: 激活回退和停用具有明确运行影响
系统 SHALL 在激活历史或最新 Publication 前执行运行时预检，并 MUST 在激活、回退和停用响应中返回受影响 route、固定的 `local` 部署、接线状态与未命中失败说明。

#### Scenario: 激活到当前运行环境
- **WHEN** 管理员把通过预检的 Publication 激活到当前 `APP_ENV`
- **THEN** 系统原子更新 Deployment 与 route 投影
- **AND** 下一条匹配的新事件使用该 Publication

#### Scenario: 激活已知不可执行的路由
- **WHEN** 当前环境 Publication 的受支持钉钉 Trigger 缺少 bot/conversation identity、有效 Agent 或 reply-original Delivery
- **THEN** 系统拒绝激活并返回字段级或组件级错误
- **AND** 现有 Deployment 保持不变

#### Scenario: 回退到历史Publication
- **WHEN** 管理员重新激活一个仍通过当前运行时预检的历史 Publication
- **THEN** 后续新事件使用历史 Publication
- **AND** 审计记录旧、新 Publication ID 和操作主体

#### Scenario: 停用当前Deployment
- **WHEN** 管理员显式停用当前环境 Deployment
- **THEN** 系统移除对应活动 route 投影
- **AND** 后续无匹配事件失败关闭且不创建 Job
- **AND** 已入队 Job 不受影响

### Requirement: 路由决策可审计且不泄露敏感信息
系统 MUST 以 correlation ID 串联路由、Job、Agent 和 Delivery 阶段，并 SHALL 记录应用、Publication、Deployment、route、结果和安全 reason code，MUST NOT 在运行状态或审计中记录 Secret、Token、完整 session webhook 或敏感原始 payload。

#### Scenario: 应用路由成功创建Job
- **WHEN** 匹配事件成功创建 Agent Job
- **THEN** 审计包含 `matched`、application code、Publication ID、Deployment ID、route ID、job ID 和 correlation ID
- **AND** 不包含可直接调用钉钉的临时凭据

#### Scenario: 路由被阻止
- **WHEN** route 因完整性或策略错误被阻止
- **THEN** 审计记录稳定 reason code 和安全摘要
- **AND** 管理员可以从运行记录定位到对应应用版本


<!-- Migrated from canonical source capability: `business-application-ui-prototype` -->

### Requirement: 原型展示一个Runtime多个业务应用的产品模型
系统 SHALL 展示一个共享Agent Runtime、多个Agent Profile和多个Business Application之间的关系，业务应用 MUST 作为前端主要管理对象，而不是把Channel、Workflow、Profile和Capability展示为缺少装配关系的平行资源。

#### Scenario: 查看业务应用组成
- **WHEN** 用户查看任一业务应用卡片或关系摘要
- **THEN** 页面展示该应用引用的Agent Profile、Workflow、触发方式、API Capability数量、输出渠道和发布状态
- **AND** 不暗示每个应用需要部署独立Agent Runtime

### Requirement: 原型展示三个代表性业务应用
系统 SHALL 展示钉钉私聊诊断助手、钉钉群聊诊断助手和Webhook告警分析助手，三个示例 MUST 体现不同的会话主体、触发身份和流程形态。

#### Scenario: 查看钉钉私聊应用
- **WHEN** 用户查看钉钉私聊诊断助手
- **THEN** 页面展示按应用、租户和钉钉用户构成的人员会话语义
- **AND** API调用主体来自当前消息发送人的内部身份

#### Scenario: 查看钉钉群聊应用
- **WHEN** 用户查看钉钉群聊诊断助手
- **THEN** 页面展示群会话上下文和必须@机器人等触发条件
- **AND** 明确API权限仍按当前消息发送人判断而不是按群共享

#### Scenario: 查看Webhook告警应用
- **WHEN** 用户查看Webhook告警分析助手
- **THEN** 页面展示签名与幂等、服务账号、固定API节点、Agent分析和钉钉投递的静态流程
- **AND** 不把Webhook请求伪装成真实人员身份

### Requirement: 原型展示应用工作区目标页签
系统 SHALL 以静态页签或关系卡形式展示应用概览、流程设计、渠道与触发器、能力授权和发布管理的目标结构，但 MUST NOT 实现真实路由和编辑行为。

#### Scenario: 评审应用工作区
- **WHEN** 用户查看业务应用区域
- **THEN** 页面能够识别五个目标工作区及各自职责
- **AND** 编辑、测试、保存、发布和回滚入口处于不可操作状态

### Requirement: 原型区分确定性API节点与Agent自主能力
系统 SHALL 在Workflow预览中区分显式API Capability节点和Agent自主决策节点，并展示两种模式可以在同一流程内组合。

#### Scenario: 查看Webhook混合流程
- **WHEN** 用户查看Webhook告警分析流程
- **THEN** 固定告警查询和日志查询以显式API节点展示
- **AND** Agent节点展示其可继续自主选择的只读Capability集合

### Requirement: 原型展示API Capability而非底层数据源工具
系统 SHALL 使用业务能力编码、名称、描述、风险、环境和可用状态展示Capability，并 MUST NOT 提供数据库、Redis、Loki连接或任意查询语言的配置入口。

#### Scenario: 查看能力目录预览
- **WHEN** 用户查看API能力区域
- **THEN** 页面展示类似`log.query.application`、`order.query.detail`和`cache.query.status`的业务能力
- **AND** 不展示DSN、数据库方言、Redis地址、Loki地址、SQL、Redis命令、LogQL、Shell或任意HTTP URL

### Requirement: 原型展示能力授权交集和版本冻结
系统 SHALL 展示有效能力由平台发布、应用授权、Workflow节点授权、Agent Profile授权和当前主体数据权限取交集，并展示应用发布冻结所引用的Profile、Workflow、Capability、Channel和策略版本。

#### Scenario: 评审应用有效能力
- **WHEN** 用户查看应用的能力授权摘要
- **THEN** 页面展示权限交集而不是“允许全部API”的单一开关
- **AND** 高风险写能力显示为未授权或MVP不可用

#### Scenario: 评审发布快照
- **WHEN** 用户查看发布管理摘要
- **THEN** 页面展示发布版本引用的Profile Revision、Workflow Revision、Capability Version和Channel Binding
- **AND** 不提供真实发布或回滚操作
