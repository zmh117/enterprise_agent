# identity-access Specification

## Purpose
定义内部用户、外部身份、认证、角色、授权及其管理入口的统一领域契约，确保身份、个人凭据、管理权限、应用访问和数据范围彼此独立。

## Requirements

<!-- Reconciled from mcp_new capability: `admin-capability-catalog` -->

### Requirement: 管理能力由后端注册目录定义
系统 SHALL 在后端维护唯一的管理能力目录，每项能力 MUST 包含稳定编码、中文名称、模块、业务动作、风险等级、依赖能力和支持的资源范围类型。管理员不得通过 UI 或通用 API 创建任意能力编码。

#### Scenario: 前端加载管理能力目录
- **WHEN** 有权查看角色授权的管理员打开角色详情
- **THEN** 前端从后端目录加载分组、中文名称、风险和依赖并生成勾选界面

#### Scenario: 提交未知能力
- **WHEN** 客户端提交未在后端目录注册的能力编码
- **THEN** 后端拒绝整个授权区修改并返回中文校验错误

### Requirement: 管理能力按模块和业务动作表达
系统 SHALL 使用“管理模块 + 业务动作 + 可选资源选择器”表达权限，不得把 React 组件、按钮文本或路由路径作为权限事实。导航、页面动作和后端 API MUST 映射到同一能力定义。

#### Scenario: 页面结构重构
- **WHEN** 前端调整按钮或路由但对应业务动作不变
- **THEN** 已有角色授权保持有效且无需迁移权限编码

#### Scenario: 无后端权限时直接调用 API
- **WHEN** 用户绕过前端隐藏按钮直接调用管理 API
- **THEN** 后端根据目录映射的资源和动作拒绝请求

### Requirement: 高级动作自动依赖查看能力
系统 SHALL 让编辑、发布、激活、分配等高级动作自动包含对应查看能力，但 MUST 保持编辑、发布、激活等职责彼此独立。取消基础查看能力时 MUST 同时取消所有依赖项。

#### Scenario: 勾选发布能力
- **WHEN** 管理员为角色勾选业务应用发布能力
- **THEN** 系统自动包含对应查看能力，但不自动包含编辑或激活能力

#### Scenario: 取消查看能力
- **WHEN** 管理员取消一个仍被高级动作依赖的查看能力
- **THEN** 页面要求同时移除依赖动作，后端也拒绝不完整的能力集合

### Requirement: 管理能力支持具体资源范围
系统 SHALL 允许目录声明某项能力是全局能力或可限定到具体业务应用、Agent、渠道及其它受管资源。自定义角色默认 MUST 使用明确资源范围，只有目录允许且操作者具有全局可授权范围时才能选择全局范围。

#### Scenario: 仅编辑指定业务应用
- **WHEN** 角色只被授予某一业务应用的编辑能力
- **THEN** 其成员可以编辑该应用但不能编辑其它业务应用

### Requirement: 自定义角色不得一键获得全部高风险能力
系统 MUST NOT 为自定义角色提供跨模块全选管理能力。模块内可以批量选择只读能力，但编辑、发布、激活、密钥和授权管理等高风险能力 MUST 单独选择和确认。

#### Scenario: 管理员选择模块只读权限
- **WHEN** 管理员点击某模块的“选择全部只读权限”
- **THEN** 系统只选择该模块的查看类能力，不选择任何写入或高风险能力

### Requirement: 新能力默认不授予自定义角色
系统 SHALL 在版本新增管理能力时自动让 `platform-admin` 获得该能力，但 MUST 让所有其它系统角色和自定义角色保持未授权，并在授权中心展示“新增未配置权限”提示。

#### Scenario: 新版本增加密钥轮换能力
- **WHEN** 系统注册新的密钥轮换管理能力
- **THEN** 只有 `platform-admin` 自动获得，其他角色需要管理员显式评估和勾选


<!-- Reconciled from mcp_new capability: `admin-user-directory` -->

### Requirement: 管理员使用真实用户目录

系统 SHALL 为具备 `user:manage` 权限的已认证管理员提供真实用户目录，并 SHALL 从后端用户数据读取列表与详情，不得使用前端静态数据或演示数据代替。

#### Scenario: 有权限的管理员查看用户列表

- **WHEN** 已认证且具备 `user:manage` 权限的管理员打开用户管理页面
- **THEN** 系统 SHALL 返回真实用户列表，并展示用户名、显示名称、账号类型、状态和更新时间

#### Scenario: 未认证访问用户目录

- **WHEN** 未认证请求访问用户目录接口或页面
- **THEN** 系统 SHALL 拒绝访问并要求认证

#### Scenario: 无权限访问用户目录

- **WHEN** 已认证但不具备 `user:manage` 权限的用户访问用户目录
- **THEN** 系统 SHALL 返回权限不足，且不得泄露用户目录数据

### Requirement: 查询和查看用户详情

系统 SHALL 支持按用户名、显示名称或已绑定外部身份的展示名称查询用户，并 SHALL 在用户详情中返回基本资料、账号状态和外部身份摘要。

#### Scenario: 查询匹配的用户

- **WHEN** 管理员输入用户名或显示名称关键字
- **THEN** 系统 SHALL 返回匹配用户，并保持稳定分页和排序

#### Scenario: 查看用户详情

- **WHEN** 管理员打开一个存在的用户详情
- **THEN** 系统 SHALL 展示该用户的基本资料、账号状态、账号类型、版本号以及钉钉和 ONES 身份摘要

#### Scenario: 用户不存在

- **WHEN** 管理员请求不存在的用户
- **THEN** 系统 SHALL 返回明确的未找到结果，不得创建占位用户

#### Scenario: 敏感字段不出现在响应中

- **WHEN** 系统返回用户列表或详情
- **THEN** 响应 MUST NOT 包含密码、密码哈希、会话令牌、CSRF 令牌或外部系统令牌

### Requirement: 创建系统用户

系统 SHALL 允许具备 `user:manage` 权限的管理员创建人类用户，并 SHALL 校验用户名唯一性和必填资料。

#### Scenario: 创建有效用户

- **WHEN** 管理员提交唯一用户名、显示名称和有效的初始状态
- **THEN** 系统 SHALL 创建人类用户并返回其非敏感资料

#### Scenario: 用户名重复

- **WHEN** 管理员提交已存在的用户名
- **THEN** 系统 SHALL 拒绝创建并返回可识别的冲突错误

#### Scenario: 创建请求包含密码

- **WHEN** 管理员为用户设置初始密码
- **THEN** 系统 SHALL 仅保存安全密码哈希，并 MUST NOT 在响应、审计详情或应用日志中记录明文密码

### Requirement: 编辑用户基本资料

系统 SHALL 允许管理员编辑用户显示名称等受支持的基本资料，并 SHALL 使用版本号防止覆盖并发修改。

#### Scenario: 使用当前版本更新用户

- **WHEN** 管理员提交有效资料和当前 `expected_revision`
- **THEN** 系统 SHALL 保存更新、递增版本号并返回最新资料

#### Scenario: 使用过期版本更新用户

- **WHEN** 管理员提交的 `expected_revision` 已过期
- **THEN** 系统 SHALL 返回冲突错误，且不得覆盖较新的修改

### Requirement: 启用和停用用户

系统 SHALL 支持启用和停用用户，且状态变更 SHALL 立即影响管理端会话和外部身份解析。

#### Scenario: 停用用户

- **WHEN** 管理员停用一个已启用的人类用户
- **THEN** 系统 SHALL 将用户标记为停用、使其现有管理端会话失效，并拒绝通过其外部身份创建新的 Agent 请求

#### Scenario: 重新启用用户

- **WHEN** 管理员重新启用一个已停用用户
- **THEN** 系统 SHALL 允许该用户重新认证，并仅允许解析仍处于启用状态的外部身份

#### Scenario: 重新启用用户不改变身份状态

- **WHEN** 用户被重新启用但其某个外部身份仍为停用状态
- **THEN** 系统 MUST NOT 自动启用该外部身份

### Requirement: 服务账号与人类用户分离

系统 SHALL 在用户目录中明确区分服务账号和人类用户，并 SHALL 禁止为服务账号绑定个人钉钉或 ONES 身份。

#### Scenario: 查看服务账号

- **WHEN** 管理员在用户目录中查看服务账号
- **THEN** 系统 SHALL 明确显示其账号类型为服务账号

#### Scenario: 尝试为服务账号绑定个人身份

- **WHEN** 管理员尝试为服务账号绑定钉钉或 ONES 用户身份
- **THEN** 系统 SHALL 拒绝请求，且不得创建身份记录

### Requirement: 用户管理写操作受统一安全控制

所有用户创建、编辑和状态变更接口 SHALL 复用现有管理端认证、CSRF、RBAC 和审计机制，不得增加绕过这些机制的专用入口。

#### Scenario: 缺少 CSRF 保护的写请求

- **WHEN** 浏览器会话发起用户管理写请求但缺少有效 CSRF 凭据
- **THEN** 系统 SHALL 拒绝请求且不得修改数据

#### Scenario: 成功修改用户

- **WHEN** 管理员成功创建、编辑、启用或停用用户
- **THEN** 系统 SHALL 写入包含操作者、目标用户、动作和结果的审计事件

### Requirement: MVP 用户界面范围受限

第一版管理界面 SHALL 仅开放用户列表、创建用户和用户详情编辑入口；角色管理、权限策略编辑、会话管理和其他系统管理功能不得因本变更而启用。

#### Scenario: 管理员进入用户管理

- **WHEN** 管理员从导航进入用户管理
- **THEN** 系统 SHALL 提供用户列表以及进入创建和详情页面的入口

#### Scenario: 查看本变更之外的系统管理入口

- **WHEN** 管理员查看角色、授权、会话或其他未实现模块
- **THEN** 这些入口 SHALL 保持禁用、隐藏或明确标记为未开放，不得展示伪功能


<!-- Reconciled from mcp_new capability: `admin-web-session-integration` -->

### Requirement: 管理Web连接现有服务端Session认证
系统 SHALL 提供真实登录页并使用现有登录和当前用户API建立管理端认证状态，MUST 通过HttpOnly Cookie承载Session且不得在Local Storage、Session Storage、URL或前端持久化状态保存Session Token。

#### Scenario: 正确账号登录
- **WHEN** 启用的内部自然人提交正确用户名和密码
- **THEN** 后端创建服务端Session并设置安全Cookie
- **AND** 前端加载当前用户、角色和能力后进入原目标管理页面

#### Scenario: 登录失败
- **WHEN** 用户提交未知用户名、错误密码、停用账号或服务账号凭据
- **THEN** 页面显示统一登录失败信息
- **AND** 不泄露账号是否存在、具体失败字段或服务端异常

#### Scenario: 浏览器重新打开已有会话
- **WHEN** 浏览器携带有效Session Cookie重新加载管理Web
- **THEN** 前端通过`/api/auth/me`恢复用户和权限
- **AND** 不要求用户重复登录或从浏览器存储恢复Token

### Requirement: 未认证和已认证路由被明确隔离
系统 SHALL 使用认证路由保护管理页面，并 MUST 在认证状态尚未确定时阻止受保护页面读取和短暂显示管理数据。

#### Scenario: 未登录访问受保护页面
- **WHEN** 浏览器没有有效Session访问用户或外部身份页面
- **THEN** 前端跳转登录页并保留安全的站内return path
- **AND** 后端API返回未认证错误

#### Scenario: 恶意外部return path
- **WHEN** 登录页收到绝对URL、协议相对URL或其它站外return path
- **THEN** 系统忽略该值并在登录成功后进入默认站内页面

#### Scenario: 已登录访问登录页
- **WHEN** 已认证用户访问`/login`
- **THEN** 前端将其送回有权访问的默认管理页面

### Requirement: 前端API Client统一处理Cookie和CSRF
系统 SHALL 为所有管理端请求使用同源`credentials: include`，并 MUST 为状态变更请求从受控CSRF Cookie读取值并发送`X-CSRF-Token`。

#### Scenario: 合法写请求
- **WHEN** 已登录页面发送带允许Origin和有效CSRF的修改请求
- **THEN** 后端继续执行RBAC、revision和业务校验

#### Scenario: 缺少CSRF
- **WHEN** Cookie认证的写请求没有有效CSRF Header
- **THEN** API拒绝请求且前端展示安全错误
- **AND** 不把请求自动降级为无CSRF重试

#### Scenario: 服务端使用自定义Cookie名称
- **WHEN** 部署配置修改CSRF Cookie名称
- **THEN** 前端从安全公开认证配置读取名称
- **AND** 不需要修改每个业务模块或暴露Session Token

### Requirement: Session失效在整个管理Web一致处理
系统 SHALL 在Session过期、撤销、用户停用或密码修改后使所有受保护查询失效，并 MUST 将用户返回未认证状态。

#### Scenario: API返回401
- **WHEN** 任一受保护查询因为Session过期返回401
- **THEN** 前端清理认证Query缓存并进入登录页
- **AND** 不继续展示过期用户和敏感页面数据

#### Scenario: API返回403
- **WHEN** Session有效但用户没有目标资源权限
- **THEN** 前端保持登录状态并展示无权限页面
- **AND** 不把403误判为Session失效

### Requirement: 用户可以安全退出修改密码和管理自己的Session
系统 SHALL 连接退出、修改密码、Session列表和撤销接口，并 MUST 在这些操作后同步更新认证状态。

#### Scenario: 用户退出
- **WHEN** 用户确认退出
- **THEN** 系统撤销当前Session、清除Cookie和前端用户缓存并返回登录页

#### Scenario: 用户修改密码
- **WHEN** 用户提交正确当前密码和合规新密码
- **THEN** 后端更新密码并撤销该用户全部Session
- **AND** 前端清空密码字段并要求重新登录

#### Scenario: 用户撤销其它Session
- **WHEN** 用户在安全设置中撤销属于自己的其它Session
- **THEN** 系统将目标Session标记为撤销并刷新Session列表
- **AND** 用户不能查看完整Token或撤销他人Session

### Requirement: 导航展示与后端能力保持一致
系统 SHALL 根据当前用户能力展示用户、外部身份、Connection和其它管理入口，但 MUST NOT 把前端隐藏导航作为授权机制。

#### Scenario: 身份管理员登录
- **WHEN** 用户具有identity管理权限但没有其它平台管理权限
- **THEN** 前端显示允许的用户与外部身份入口并隐藏无权限命令
- **AND** 后端仍对每个请求执行对象级RBAC

#### Scenario: 普通用户登录
- **WHEN** 用户只有自己的安全设置和外部身份自助验证权限
- **THEN** 前端只显示个人安全与“我的外部身份”
- **AND** 不显示其它用户、Connection和冲突治理数据

### Requirement: 认证页面满足安全可用性要求
系统 SHALL 为登录、Session恢复、无权限、过期、限流和后端不可用提供明确状态，并 MUST 满足桌面、窄屏、键盘和辅助技术使用要求。

#### Scenario: 登录请求处理中
- **WHEN** 登录请求尚未完成
- **THEN** 页面禁用重复提交并提供可识别的忙碌状态
- **AND** 密码不出现在页面日志、URL、Toast详情或错误遥测中

#### Scenario: 键盘完成登录
- **WHEN** 用户只使用键盘或辅助技术完成登录
- **THEN** 用户名、密码、错误摘要和提交按钮具有正确标签与焦点顺序
- **AND** 错误状态不只依赖颜色表达


<!-- Reconciled from mcp_new capability: `agent-audit-permission` -->

### Requirement: Users must be authorized before Agent job creation
The system SHALL check connector ingress authorization and the access policy applicable to the resolved Trigger before creating an Agent job from any Channel message. For DingTalk messages resolved to an active Business Application Publication, the system SHALL authorize application access when the actual sender maps to an enabled internal user and MUST NOT require an additional application user allowlist, role, or Capability `use` grant; other Trigger types SHALL retain their defined requester, service-account, service, project, or role policies.

#### Scenario: Authorized user submits request
- **WHEN** a verified Channel requester satisfies the access policy for the resolved Trigger and the source connector allows ingress
- **THEN** the system creates the Agent job and records the permission decision

#### Scenario: Unauthorized user submits request
- **WHEN** a verified Channel requester does not satisfy the access policy for the resolved Trigger or target service or project
- **THEN** the system rejects the request, records the permission denial, and does not publish an Agent job

#### Scenario: Connector is not authorized for ingress
- **WHEN** a request uses a connector that is disabled or not allowed for ingress
- **THEN** the system rejects the request, records the connector authorization failure, and does not publish an Agent job

#### Scenario: DingTalk sender resolves to an enabled user
- **WHEN** a DingTalk message hits a connector bound to an active Application Publication and the actual sender maps to an enabled internal user
- **THEN** the system authorizes access to that application without requiring a separate application user allowlist, role, or Capability grant

#### Scenario: DingTalk sender is unbound or disabled
- **WHEN** the actual DingTalk sender has no enabled internal identity or the internal user is disabled
- **THEN** the system rejects job creation, records a safe reason, and returns an understandable binding or account-status prompt

### Requirement: Tool access is policy checked
The system SHALL check tool allowlists, source access, read-only risk policy and the governance policy applicable to each Tool before execution. For a governed API Capability, the system MUST check the frozen Agent Capability Envelope, Application Capability Allowlist, exact Release status, current user Provider availability, External Execution Subject Snapshot and current personal credential; it MUST NOT require a separate per-user or per-role Capability Code `use` grant.

#### Scenario: Allowed read-only tool call
- **WHEN** Agent requests an enabled internal read-only tool within the user's allowed scope
- **THEN** the system executes the tool call and records the policy decision

#### Scenario: Disallowed tool call
- **WHEN** Agent requests a disabled tool, out-of-scope source, non-read-only operation, or Tool outside the current publication snapshot
- **THEN** the system rejects the tool call and records the policy decision

#### Scenario: Governed Capability is fully allowed
- **WHEN** the exact Capability Release belongs to both the frozen Agent Envelope and Application Allowlist, remains runnable, and the current user binding, Team and Token are valid
- **THEN** the system executes the call and records each governance dimension without checking a separate Capability role grant

#### Scenario: Application did not allow Capability
- **WHEN** the Agent Envelope includes the Release but the Application Allowlist does not
- **THEN** the system rejects the call before external network access and records the missing application authorization dimension

### Requirement: Audit events are persisted across the execution chain
系统 SHALL 持久化覆盖 Channel receipt、身份解析、connector/RBAC 决策、Job 创建、队列发布确认、Worker claim、工具调用、Claude 安全错误分类、retry 调度、retry 回流、显式恢复、终态结果、delivery attempt/chunk 和最终投递状态的审计事件，并使用 Job 与 correlation ID 串联全链路。

#### Scenario: Job completes successfully without retry
- **WHEN** Agent Job 被接受、首次执行成功并沿 reply route 投递
- **THEN** 审计链包含入口、身份/RBAC、Job、主队列发布、Worker、工具、最终报告和 delivery 结果

#### Scenario: Job succeeds after retry
- **WHEN** Job 首次发生可重试错误，延迟回流后再次执行成功
- **THEN** 审计链包含安全错误码、retry count、`next_retry_at`、retry publish confirm、回流后的再次 claim、最终报告和 delivery 结果

#### Scenario: Job fails after retries are exhausted
- **WHEN** Job 达到最大重试次数并进入 `FAILED`
- **THEN** 审计链包含每次安全错误分类、retry 调度/回流、终态 dead-letter 决策和一次失败通知 delivery 结果

#### Scenario: Retry dispatch is stranded
- **WHEN** Job 已持久化为等待重试但 RabbitMQ publish confirm 失败或超过预期时间没有回流
- **THEN** 审计记录 dispatch/recovery 状态，使运维能区分模型失败、队列滞留和 Worker 未消费

#### Scenario: Administrator recovers a stranded job
- **WHEN** 管理员通过显式 apply 恢复一个滞留 Job
- **THEN** 审计记录管理员内部身份、目标 Job、恢复前后状态、所用队列版本和 publish 结果，不记录完整外部 payload 或 webhook

#### Scenario: Job fails before execution
- **WHEN** Job 在 Agent runtime 开始前被拒绝
- **THEN** 审计链包含拒绝原因且没有工具执行或模型调用记录

#### Scenario: Grafana event is ignored
- **WHEN** Grafana 事件因为不是 `firing` 被忽略
- **THEN** 审计记录 connector、external event ID、忽略原因和安全 payload 摘要

### Requirement: Tool calls are recorded with safe summaries
The system SHALL persist tool call records with sanitized request payload summaries, bounded normalized response summaries, status, duration, risk level, audit linkage, and platform or Capability Release outcome details when available. For governed external APIs, the system MUST record Release and attempt metadata but MUST NOT persist authentication material, raw HTTP request/response bodies or unbounded external content.

#### Scenario: Database tool succeeds
- **WHEN** `query_database` returns evidence through the Internal API Platform
- **THEN** the system records the tool name, sanitized request summary, bounded response summary, duration, status, risk level, related audit event, and platform request metadata if provided

#### Scenario: Tool call returns sensitive or large data
- **WHEN** a tool response contains sensitive fields or exceeds inline storage limits
- **THEN** the system stores a masked or summarized response in PostgreSQL and avoids persisting raw sensitive payloads in the tool call row

#### Scenario: Internal platform rejects a tool call
- **WHEN** the Internal API Platform rejects a tool call because of authorization, data-source policy, query policy, or malformed parameters
- **THEN** the system records a failed tool call with a safe rejection reason, duration, risk level, and audit event without exposing platform secrets

#### Scenario: Governed external API call succeeds after retry
- **WHEN** a QUERY Capability succeeds after one or more HTTP attempts
- **THEN** the system records one linked Tool Call and separate safe attempt metadata containing identifiers, classification, duration, size and status, without raw body, Token, Cookie or authentication Header

#### Scenario: Governed external output is INTERNAL
- **WHEN** a Capability returns bounded normalized INTERNAL data
- **THEN** the Tool Call summary preserves user, Application Publication, Capability Release and classification provenance and remains subject to the existing Job access boundary

### Requirement: Agent artifacts are persisted
The system SHALL persist final reports and other approved Agent artifacts with job linkage and artifact type.

#### Scenario: Final report is generated
- **WHEN** the Agent produces the final diagnostic answer
- **THEN** the system persists a report artifact linked to the Agent job

### Requirement: Configuration is persisted for future web management
The system SHALL store permission policies, tool enablement, connector metadata, connector direction flags, delivery metadata, and data source registry entries in PostgreSQL so a later web service can manage them without redesigning core persistence.

#### Scenario: Administrator later changes tool access
- **WHEN** a future web service updates tool enablement or permission policy
- **THEN** the Agent runtime can read the updated PostgreSQL-backed configuration without requiring a code change

#### Scenario: Administrator later changes connector direction
- **WHEN** a future web service disables delivery on a connector
- **THEN** new jobs cannot select that connector as a delivery route until it is enabled again

### Requirement: Platform configuration authorization is policy checked
系统 SHALL 在平台配置 API 执行新增、修改、启停、导入和发布动作前检查操作者是否具有对应配置管理权限。

#### Scenario: Authorized admin updates topology
- **WHEN** 具备平台配置管理权限的操作者更新基地或车间配置
- **THEN** 系统允许更新并记录授权决策

#### Scenario: Unauthorized user updates topology
- **WHEN** 不具备平台配置管理权限的用户尝试修改资源绑定
- **THEN** 系统拒绝请求，记录拒绝原因，并且不写入配置变更

### Requirement: Platform configuration audit is linked to runtime audit model
系统 SHALL 将平台配置变更审计与现有 Agent 审计模型保持一致的 actor、entity、action、before、after 和 correlation 信息。

#### Scenario: Admin changes access grant
- **WHEN** 管理员修改某用户的车间访问授权
- **THEN** 系统记录配置审计，包含操作者、被修改实体、修改前摘要、修改后摘要和 correlation id

#### Scenario: YAML import updates resource binding
- **WHEN** YAML import 更新已有资源绑定
- **THEN** 系统记录该资源绑定的配置审计，并能关联到本次 import 操作

### Requirement: Runtime tool authorization can consume platform access grants
系统 SHALL 允许运行时工具授权从平台访问授权配置生成访问策略，且 MUST 保持只读工具风险边界。

#### Scenario: User has workshop grant
- **WHEN** Agent job 用户命中某车间的 read-only access grant
- **THEN** 运行时工具授权允许该用户访问该车间允许的只读资源

#### Scenario: User lacks grant
- **WHEN** Agent job 用户没有目标车间或资源的访问授权
- **THEN** 运行时工具授权拒绝工具调用并记录权限拒绝

### Requirement: DingTalk delivery credentials are never exposed in audit records
系统 SHALL 在钉钉企业 App 和 webhook 群机器人投递过程中屏蔽 Client Secret、access token、webhook token、签名密钥、完整 webhook URL 和敏感接收人信息。

#### Scenario: Delivery attempt is recorded
- **WHEN** 系统记录 DingTalk delivery attempt
- **THEN** target summary 和 audit payload 只包含 connector ID、route type、目标安全摘要和分片数量，不包含任何密钥或完整 URL

#### Scenario: DingTalk provider returns an error
- **WHEN** 钉钉 API 或 webhook 返回错误
- **THEN** 系统保存安全错误摘要，不保存 access token、签名串、完整请求体中的敏感字段或完整 webhook URL

### Requirement: DingTalk delivery connector authorization is enforced
系统 SHALL 在钉钉企业 App 和 webhook 群机器人投递前校验 connector 存在、启用、允许 delivery，并记录授权决策。

#### Scenario: Delivery connector is allowed
- **WHEN** Agent job 使用允许 delivery 的 DingTalk connector
- **THEN** 系统记录 connector delivery 授权成功并继续投递

#### Scenario: Delivery connector is not allowed
- **WHEN** Agent job 使用未启用或不允许 delivery 的 DingTalk connector
- **THEN** 系统阻止投递、记录授权失败，并不发起外部钉钉请求

### Requirement: DingTalk webhook robot ingress attempts are audited
系统 SHALL 对 webhook 群机器人被误用为入口的请求记录审计事件，说明该 connector 只允许 delivery。

#### Scenario: Webhook robot ingress is rejected
- **WHEN** 请求尝试通过 webhook 群机器人 connector 创建 Agent job
- **THEN** 系统记录入口拒绝审计事件，并且不持久化 Agent session、Agent job 或 queue message

### Requirement: DingTalk Stream connection lifecycle is audited
The system SHALL persist audit events for DingTalk Stream connector startup, successful connection, disconnect, reconnect attempt, reconnect success, configuration failure, and permanent connector failure.

#### Scenario: Stream connector reconnects
- **WHEN** DingTalk Stream ingress loses connection and reconnects successfully
- **THEN** the audit trail records disconnect, reconnect attempt, reconnect success, connector ID, and timestamps

### Requirement: DingTalk Stream ingress permission is checked before job creation
The system SHALL check connector enablement, user allowlists, and project or service allowlists before creating an Agent job from a DingTalk Stream message.

#### Scenario: Authorized Stream user submits request
- **WHEN** a DingTalk Stream user is allowed to use the Agent for the requested project or service
- **THEN** the system creates the Agent job and records the permission decision with Stream event linkage

#### Scenario: Unauthorized Stream user submits request
- **WHEN** a DingTalk Stream user is not allowed to use the Agent or requested project or service
- **THEN** the system rejects the Stream message, records the permission denial, and does not publish an Agent job

### Requirement: DingTalk Stream message handling is audited end to end
The system SHALL persist audit events linking the Stream event receipt, identity parsing, idempotency decision, permission decision, job creation, queue dispatch, worker execution, final artifact, and DingTalk delivery result.

#### Scenario: Stream job completes successfully
- **WHEN** an Agent job created from DingTalk Stream completes and is delivered to DingTalk
- **THEN** the audit trail links the original Stream event, Agent job, tool calls, final report, and delivery result

#### Scenario: Stream message fails before execution
- **WHEN** a DingTalk Stream message is rejected before Agent runtime starts
- **THEN** the audit trail includes the rejection reason and no tool execution records

### Requirement: Identity and RBAC lifecycle changes are audited
The system SHALL audit user creation and disablement, password/session security events, role and membership changes, external identity binding lifecycle, Agent configuration validation/publication/rollback, and permission denials using internal actor IDs and secret-safe summaries.

#### Scenario: Administrator binds DingTalk identity
- **WHEN** an authenticated administrator binds a DingTalk identity to an internal user
- **THEN** the audit records actor, target user, external identity record, tenant/connector summary, action, before/after state and correlation ID without storing credentials or full provider payload

#### Scenario: Role permission is changed
- **WHEN** an administrator adds or removes a role policy
- **THEN** the audit records the role, safe policy summary, revision and actor

### Requirement: 模型与重试审计不得泄漏敏感运行数据
系统 SHALL 对 Claude/DeepSeek 错误、RabbitMQ retry payload、恢复输出和失败通知执行统一脱敏与有界摘要；API key、认证 token、完整 session webhook、完整敏感 URL、原始外部消息、未受限工具结果和模型私有推理 MUST 不进入审计。

#### Scenario: Claude CLI emits sensitive stderr
- **WHEN** CLI 错误包含 authorization、token、key、完整 URL 或请求内容
- **THEN** 审计仅保存屏蔽后的错误分类和有界摘要

#### Scenario: Retry message is audited
- **WHEN** 系统发布或回流 retry 消息
- **THEN** 审计只记录 Job ID、correlation ID、retry count、delay/due time、队列版本和确认结果，不复制用户问题、reply route secret 或模型上下文

### Requirement: Webhook 服务账号必须完成统一授权链
系统 SHALL 在 Webhook event 接收/分发和每次工具调用时，以 Trigger 服务账号执行 Connector ingress、Agent use、project、tool 和平台数据范围授权，MUST 采用显式 deny 优先。

#### Scenario: 服务账号权限完整
- **WHEN** 服务账号、角色和 grant 共同允许固定 Agent、项目、工具和目标数据范围
- **THEN** 系统允许创建 job并在决策 trace 中记录匹配策略和 grant

#### Scenario: 服务账号没有 Agent use 权限
- **WHEN** Trigger publication 有效但服务账号未被允许使用对应 Agent
- **THEN** dispatcher 拒绝创建 job、将 event 标记为安全失败并记录 deny trace

#### Scenario: 工具调用超出数据范围
- **WHEN** Webhook Agent 试图使用允许的工具访问服务账号未授权的基地或车间
- **THEN** 工具层拒绝调用并记录范围拒绝，Agent 不得绕过该决定

### Requirement: Webhook 配置和运行审计不得泄漏凭证或原始报文
系统 SHALL 审计 Trigger 创建、修改、发布、回滚、public ID 轮换、服务账号授权、事件认证/过滤/分发和 Delivery 结果，MUST 只保存安全摘要。

#### Scenario: HMAC 认证失败
- **WHEN** 请求签名不匹配
- **THEN** 审计记录 Trigger、错误码、payload hash、请求大小和 correlation ID，不记录 secret、签名原文或 body

#### Scenario: 管理员修改 Trigger
- **WHEN** 管理员保存或发布 revision
- **THEN** 审计记录 actor、Trigger、before/after config hash、revision 和结果，不记录 secret value

### Requirement: 授权决策记录业务应用和来源摘要
系统 SHALL 为 job 创建、Worker 执行前、每次业务能力调用和结果投递前的授权决策生成安全 trace，至少包含内部用户或服务账号、目标业务应用、能力、明确数据范围、来源角色 ID、兼容策略标记、最终结果和拒绝阶段。trace MUST NOT 包含密码、Token、Secret、模型 API Key 或原始敏感策略条件。

#### Scenario: Worker 因角色到期拒绝
- **WHEN** Worker 执行前发现创建任务时有效的角色成员关系已经到期
- **THEN** 系统记录执行前授权拒绝、角色来源摘要和 job 关联，不记录消息正文或敏感数据

### Requirement: 角色授权配置变更被审计
系统 SHALL 记录角色基本信息、成员、管理后台能力、业务应用、只读能力、数据范围、角色分配委派和高级例外的变更前后安全摘要。高风险变更 MUST 同时记录管理员填写的变更原因。

#### Scenario: 扩大生产数据范围
- **WHEN** 管理员为角色增加生产基地范围
- **THEN** 系统记录操作者、角色、业务应用、增加的明确范围、受影响成员数和变更原因

#### Scenario: 延长成员有效期
- **WHEN** 管理员延长角色成员有效期
- **THEN** 系统通过普通成员更新审计记录原时间、新时间和操作者，不要求独立审批记录


<!-- Reconciled from mcp_new capability: `dingtalk-enterprise-governance` -->

### Requirement: 钉钉企业以真实 Corp ID 建立命名空间
系统 SHALL 将钉钉企业作为独立治理资源，使用内部 ID 建立关系，并在验证成功后以非空真实 Corp ID 作为不可变外部稳定标识；管理员维护的企业名称 MUST NOT 代替 Corp ID 参与身份唯一性判断。

#### Scenario: 创建首个企业草稿
- **WHEN** 具备渠道管理权限的管理员输入企业名称创建钉钉企业
- **THEN** 系统创建 `PENDING_VERIFICATION` 企业且 Corp ID 为空，不要求管理员手工填写 Corp ID

#### Scenario: 另一个企业已使用相同 Corp ID
- **WHEN** 待验证企业取得的 Corp ID 已属于另一个企业记录
- **THEN** 系统拒绝验证、保留待验证状态并记录不含消息正文的治理冲突

### Requirement: 首个应用通过同一条受信消息验证企业
首个钉钉应用连接建立后，系统 MUST 只使用同一条通过 SDK 认证的测试消息中非空且相等的 `senderCorpId` 与 `chatbotCorpId` 固化企业 Corp ID；该消息 MUST 只形成安全验证证据，不得创建业务 Job、身份、候选、观察记录或应用访问。

#### Scenario: 首个应用完成企业验证
- **WHEN** 待验证企业的首个连接收到受信测试消息，且 `senderCorpId` 与 `chatbotCorpId` 非空并相等
- **THEN** 系统在事务中固化 Corp ID、验证时间和安全审计证据，将企业转为 `ACTIVE`，且不处理该消息的业务内容

#### Scenario: 测试消息的企业字段不一致
- **WHEN** 同一条测试消息缺少 Corp ID 或 `senderCorpId` 与 `chatbotCorpId` 不一致
- **THEN** 系统拒绝企业验证、保持 `PENDING_VERIFICATION`，不创建身份或 Job，并返回安全配置提示

### Requirement: 钉钉企业生命周期独立于连接运行态
系统 MUST 只允许钉钉企业使用 `PENDING_VERIFICATION`、`ACTIVE`、`DISABLED` 和 `ARCHIVED` 四种状态，并 MUST 将企业治理状态与应用连接的连接、心跳、重连和错误状态分别计算。

#### Scenario: 企业已启用但某个应用断线
- **WHEN** `ACTIVE` 企业下一个应用连接处于重连或错误状态
- **THEN** 企业仍保持 `ACTIVE`，页面分别展示企业状态和该应用运行状态，不把连接故障改写为企业待验证

#### Scenario: 停用企业
- **WHEN** 管理员确认停用一个 `ACTIVE` 企业
- **THEN** 系统将企业设为 `DISABLED`，停止该企业全部应用入口和身份解析，同时保留企业、身份、观察和审计数据

#### Scenario: 归档仍有启用应用的企业
- **WHEN** 管理员尝试归档仍存在启用应用连接的企业
- **THEN** 系统拒绝归档并列出需要先停用的应用连接

#### Scenario: 恢复停用或归档企业
- **WHEN** 管理员请求恢复 `DISABLED` 或 `ARCHIVED` 企业
- **THEN** 系统要求应用重新连接并再次验证同一 Corp ID，在验证完成前不得直接恢复业务处理

### Requirement: Corp ID 不可编辑而企业名称可审计修改
企业验证成功后系统 MUST NOT 提供直接修改 Corp ID 的接口；企业名称 SHALL 允许具备渠道管理权限的管理员修改，并 MUST 记录操作者、时间及修改前后名称。

#### Scenario: 修改企业名称
- **WHEN** 管理员使用当前 Revision 修改已验证企业名称
- **THEN** 系统更新名称、递增 Revision、写入名称变更审计，并在企业、应用连接和身份页面统一展示新名称

#### Scenario: 尝试修改已验证 Corp ID
- **WHEN** 客户端提交与已验证 Corp ID 不同的值
- **THEN** 系统拒绝请求且不修改企业、连接、身份或观察记录

### Requirement: 一个企业可被多个应用连接引用
系统 SHALL 允许多个钉钉应用连接引用同一个钉钉企业，每个钉钉应用连接 MUST 且只能引用一个企业；企业与应用关系不得解释为用户身份或用户授权。

#### Scenario: 为现有企业新增第二个应用
- **WHEN** 管理员为已验证企业创建另一个钉钉应用连接
- **THEN** 系统保存同一企业引用，并要求该应用的受信消息 Corp ID 与企业一致

#### Scenario: 应用试图跨企业运行
- **WHEN** 一个应用连接的受信消息证明其 Corp ID 与所选企业不同
- **THEN** 系统拒绝该应用的消息处理并产生治理告警，不得自动改绑企业或创建新企业

### Requirement: 钉钉测试数据重建必须显式受保护
系统 SHALL 提供仅限非生产环境的一次性钉钉测试数据重建命令；常规数据库迁移、应用启动和管理页面 MUST NOT 自动执行该清理。

#### Scenario: 只读预检重建范围
- **WHEN** 操作者运行重建命令的默认预检模式
- **THEN** 系统只读取并报告环境、数据库指纹、目标连接、各类待清记录数、受影响应用渠道绑定、Secret 撤销范围、明确保留项和计划 Hash，不删除或修改记录

#### Scenario: 使用匹配计划执行重建
- **WHEN** 非生产环境已停止钉钉写入，操作者提交固定确认文字、显式执行参数和仍与当前数据匹配的计划 Hash
- **THEN** 系统在单一事务中清理约定钉钉身份与渠道测试数据、停用旧连接并撤销其专属 Secret，成功后输出实际数量和保留数据复核

#### Scenario: 生产环境请求重建
- **WHEN** 生产环境以任何参数调用重建命令
- **THEN** 系统永久拒绝执行且不得开始删除事务

#### Scenario: 预检后数据发生变化
- **WHEN** 执行时数据库指纹、目标集合或记录数量与计划 Hash 不一致
- **THEN** 系统拒绝执行并要求重新预检，不得使用旧确认继续

#### Scenario: 重建事务中途失败
- **WHEN** 任一删除、Secret 撤销或引用处理步骤失败
- **THEN** 系统整体回滚并报告安全错误，不留下部分清理状态

### Requirement: 重建保留跨域运行历史
钉钉测试数据重建 MUST 保留平台人员、角色、登录会话、ONES 身份与个人凭据、API Capability、Agent、业务应用主体，以及全部 Agent Job、Tool 调用结果和投递记录；历史发布中的旧连接引用 SHALL 只标记为不可运行历史来源，不得被静默改写到新连接。

#### Scenario: 清理存在历史 Job 的旧连接
- **WHEN** 待清理钉钉连接已经产生 Agent Job、Tool 调用和投递记录
- **THEN** 系统保留这些运行记录，使其旧连接来源可审计但不可继续路由

#### Scenario: 清理后重新接入
- **WHEN** 重建成功后管理员创建企业和新应用连接
- **THEN** 既有业务应用主体仍存在，但必须显式选择新连接并重新发布，不得自动把历史发布改指新连接


<!-- Reconciled from mcp_new capability: `dingtalk-identity-governance` -->

### Requirement: 钉钉身份按企业和用户 ID 唯一
系统 MUST 以“钉钉企业 + `senderStaffId`”唯一识别钉钉外部身份，并 MUST 保证每个“内部用户 + 钉钉企业”至多存在一个 `enabled` 或 `disabled` 的当前身份；身份不得因通过不同钉钉应用出现而重复创建。

#### Scenario: 同一身份通过两个应用发消息
- **WHEN** 同一企业内相同 `senderStaffId` 先后通过两个已验证应用连接发送消息
- **THEN** 系统解析到同一外部身份和内部用户，不创建第二个身份

#### Scenario: 不同企业出现相同用户 ID
- **WHEN** 两个已验证企业出现相同 `senderStaffId`
- **THEN** 系统将其识别为两个隔离的外部身份，且可分别绑定到内部用户

#### Scenario: 用户在不同企业各有身份
- **WHEN** 同一内部用户分别绑定两个企业的受信候选
- **THEN** 系统允许每个企业各有一个当前身份，不将其合并为单一全局钉钉账号

### Requirement: 新钉钉身份只能从受信候选绑定
系统 MUST 只允许管理员使用已验证企业和可用应用连接产生的受信候选创建钉钉身份；客户端不得提交或覆盖 Corp ID、Staff ID、钉钉昵称、来源连接或企业归属。

#### Scenario: 管理员绑定受信候选
- **WHEN** 具备身份治理权限的管理员选择当前候选和已启用自然人用户并提交有效乐观锁版本
- **THEN** 系统从服务端重新读取候选事实并创建启用身份，不接受客户端控制可信字段

#### Scenario: 管理员手工填写钉钉用户 ID
- **WHEN** 客户端尝试绕过候选提交 Staff ID、Corp ID 或昵称
- **THEN** 系统拒绝请求且不得创建或修改身份

#### Scenario: 候选企业或来源应用已不可用
- **WHEN** 绑定时企业不再 `ACTIVE` 或候选来源应用已停用、删除或不再属于该企业
- **THEN** 系统失败关闭并要求管理员刷新或修复连接，不猜测其他来源

### Requirement: 同企业换绑必须显式且保留历史
当目标用户在同一企业已有不同当前身份时，系统 MUST 要求管理员显式确认换绑，并 MUST 在单一事务中将旧身份软解绑后创建或恢复新身份；系统不得静默并存两个当前身份。

#### Scenario: 用户换用同企业新 Staff ID
- **WHEN** 管理员确认把同一企业的新候选绑定给已有当前身份的用户
- **THEN** 系统软解绑旧身份、保留历史审计并启用新身份，其他企业身份不受影响

#### Scenario: 未确认同企业换绑
- **WHEN** 管理员选择的新候选与目标用户当前 Staff ID 不同但未提交显式换绑确认
- **THEN** 系统返回冲突且不修改任何身份

### Requirement: 历史钉钉身份只能恢复到原人员
系统 MUST 保留软解绑身份的原人员归属；相同企业和 Staff ID 再次形成候选时，只允许在原人员上恢复，不得转移到其他人员。

#### Scenario: 已解绑身份再次发送消息
- **WHEN** 软解绑身份通过任一同企业应用连接再次发送受信消息
- **THEN** 候选标记为需要恢复并指向原人员，不提供绑定其他人员的正常操作

#### Scenario: 尝试转移历史身份
- **WHEN** 客户端把存在原人员历史归属的候选提交给其他用户
- **THEN** 系统拒绝请求且不得覆盖、转移或复制历史身份

### Requirement: 应用观察记录只表达受信来源
系统 SHALL 以“外部身份 + 钉钉应用连接”幂等保存应用观察记录，只包含首次和最近受信时间；该记录 MUST NOT 表示用户绑定应用、获得应用访问或身份归属于应用。

#### Scenario: 首次通过某应用识别身份
- **WHEN** 启用身份通过一个已验证同企业应用发送受信业务消息
- **THEN** 系统创建一条观察记录并把首次和最近观察时间设为该次有效事件时间

#### Scenario: 同一事件重试
- **WHEN** 同一应用和稳定事件 ID 被重复处理
- **THEN** 系统不创建第二条观察记录，也不重复增加任何计数

#### Scenario: 身份经第二个应用出现
- **WHEN** 同一身份首次通过该企业的另一个应用发送受信消息
- **THEN** 系统新增第二条观察记录，原身份和人员关联保持不变

#### Scenario: 读取观察记录
- **WHEN** 管理员查看身份的应用观察摘要
- **THEN** 响应只返回应用名称、首次和最近观察时间，不返回消息正文、Webhook、Client ID、Client Secret、原始事件或内部 Connector ID

### Requirement: 钉钉昵称按事件游标单调刷新
系统 SHALL 把受信消息中的最新非空 `senderNick` 作为钉钉昵称，并 MUST 按“有效事件发生时间 + 稳定事件 ID”比较更新游标；空昵称、较旧事件和重试 MUST NOT 清除或回滚当前昵称。

#### Scenario: 收到更新昵称的新事件
- **WHEN** 启用身份收到非空昵称且事件游标晚于当前昵称游标
- **THEN** 系统更新当前昵称、观察时间、来源应用和事件 ID

#### Scenario: 旧消息晚到
- **WHEN** 较旧事件在新昵称已经保存后才完成处理
- **THEN** 系统保留新昵称且不新增昵称变化审计

#### Scenario: 相同时间的两个事件
- **WHEN** 两个非空昵称事件具有相同有效事件时间
- **THEN** 系统使用稳定事件 ID 确定唯一顺序，使重复执行得到相同结果

#### Scenario: 外部时间无效或偏差异常
- **WHEN** `createAt` 无法解析或超出允许时钟偏差
- **THEN** 系统使用服务端接收时间参与昵称游标比较，不允许异常外部时间永久冻结昵称

### Requirement: 昵称变化形成精简审计
每次钉钉昵称实际变化时，系统 MUST 保存旧昵称、新昵称、身份 ID、有效事件时间、来源应用连接和稳定事件 ID，并 MUST NOT 在该审计中复制消息正文或其他原始载荷。

#### Scenario: 昵称从旧值变为新值
- **WHEN** 新受信事件通过游标判断并改变当前昵称
- **THEN** 系统在同一事务中写入一条昵称变化审计，日常身份卡只显示新昵称

#### Scenario: 本人读取身份
- **WHEN** 当前用户通过本人接口查看钉钉身份
- **THEN** 系统不返回昵称历史或昵称审计标识

### Requirement: 身份治理范围覆盖企业全部应用
停用或解绑钉钉身份 MUST 对该身份所属企业的全部应用连接生效；系统不得通过修改身份记录表达单个应用的用户限制。

#### Scenario: 停用多应用可见身份
- **WHEN** 管理员停用一个已通过多个应用观察到的身份
- **THEN** 该用户从该企业任一应用发送的新消息均不能创建 Job，观察历史保持可见

#### Scenario: 只限制某个业务应用
- **WHEN** 管理员需要阻止用户访问某个应用但保留同企业其他应用访问
- **THEN** 系统要求使用独立应用访问策略，不允许拆分或复制钉钉身份

### Requirement: 身份事实必须先于 Agent Job 持久化
已绑定钉钉消息在创建 Agent Job 前 MUST 完成企业状态校验、身份与用户解析、最近使用、应用观察和符合条件的昵称审计写入；任一必要身份事实写入失败时 MUST NOT 创建或分发 Job。

#### Scenario: 身份事实更新成功
- **WHEN** 已绑定启用用户通过 `ACTIVE` 企业的可用应用发送受信消息
- **THEN** 系统先幂等更新身份事实，再计算应用访问并创建 Agent Job

#### Scenario: 观察记录写入失败
- **WHEN** 消息身份有效但应用观察事务失败
- **THEN** 系统拒绝该消息的业务分发、记录安全错误且不创建 Agent Job

#### Scenario: 未绑定用户发送消息
- **WHEN** `ACTIVE` 企业消息无法解析到当前启用身份
- **THEN** 系统进入受信候选分支且不写正式身份观察、不创建 Agent Job


<!-- Reconciled from mcp_new capability: `dingtalk-ones-identity-binding` -->

### Requirement: 外部身份提供方范围固定

系统 SHALL 在本阶段仅允许管理员为人类用户管理 `dingtalk` 和 `ones` 两类外部身份，并 SHALL 拒绝任意自定义提供方写入。

#### Scenario: 获取可用身份提供方

- **WHEN** 管理员打开用户的外部身份区域
- **THEN** 系统 SHALL 返回钉钉和 ONES 两个受支持提供方及其可配置字段

#### Scenario: 请求不支持的提供方

- **WHEN** 客户端尝试创建非 `dingtalk` 或 `ones` 的外部身份
- **THEN** 系统 SHALL 拒绝请求且不得写入身份记录

### Requirement: 管理员绑定钉钉身份

系统 SHALL 允许具备 `identity:manage` 权限的管理员使用受信任的钉钉连接器、租户和 `senderStaffId` 为人类用户绑定钉钉身份。

#### Scenario: 绑定有效钉钉身份

- **WHEN** 管理员选择已配置的钉钉连接器并提交租户和有效 `senderStaffId`
- **THEN** 系统 SHALL 创建启用的钉钉身份、记录验证来源，并在用户详情中显示绑定结果

#### Scenario: 连接器和租户不匹配

- **WHEN** 管理员提交的钉钉租户不属于所选受信任连接器
- **THEN** 系统 SHALL 拒绝绑定，且不得创建身份记录

#### Scenario: 同一用户重复提交相同钉钉身份

- **WHEN** 相同钉钉身份已绑定到目标用户
- **THEN** 系统 SHALL 幂等返回现有绑定，不得创建重复记录

#### Scenario: 钉钉身份已属于其他用户

- **WHEN** 相同租户和 `senderStaffId` 已绑定到另一个用户
- **THEN** 系统 SHALL 返回冲突错误，不得自动覆盖或迁移绑定

### Requirement: ONES 身份通过服务端登录验证
系统 SHALL 使用服务端固定且独立于 API Connection、Capability 与 MCP 的受信 ONES 身份配置，由当前用户本人提交邮箱与一次性密码完成验证，并使用响应中的用户 UUID 作为外部身份标识。管理员不得为其他用户输入邮箱密码或代为验证。

#### Scenario: ONES 凭据验证成功
- **WHEN** 当前用户提交有效邮箱与一次性密码
- **THEN** 系统调用固定登录端点，严格校验响应，并经无 Token Challenge 保存 User ID、显示名称、Team、默认 Team 和验证时间

#### Scenario: 管理员尝试代用户验证
- **WHEN** 管理员在人员管理上下文提交他人的邮箱密码
- **THEN** 系统拒绝且不访问 ONES 登录端点

### Requirement: ONES 验证网络边界受控

系统 SHALL 从服务端配置读取 ONES 实例地址，并 MUST 对网络目标、协议、重定向、超时、响应大小和响应结构实施限制。

#### Scenario: 生产环境使用非 HTTPS 地址

- **WHEN** 生产环境配置了非 HTTPS 的 ONES 身份地址
- **THEN** 系统 SHALL 拒绝启动或拒绝执行 ONES 身份验证

#### Scenario: 本地 Mock 使用 HTTP

- **WHEN** 开发测试环境明确启用本地非安全协议且目标属于允许主机
- **THEN** 系统 MAY 使用 HTTP 调用 ONES Mock

#### Scenario: ONES 返回重定向或超大响应

- **WHEN** ONES 登录端点返回重定向或超过配置上限的响应
- **THEN** 系统 SHALL 中止验证并返回安全错误，不得跟随重定向或继续解析超大响应

#### Scenario: ONES 响应结构不符合约定

- **WHEN** 登录响应缺少用户 UUID 或响应字段类型不正确
- **THEN** 系统 SHALL 视为验证失败且不得创建或更新身份

### Requirement: ONES 凭据和令牌不得持久化
系统 MUST NOT 将 ONES 邮箱、明文密码、登录 Token 或原始登录响应保存到数据库、缓存、日志、审计、API 响应或前端持久层；旧 External API Credential 不得作为身份绑定依赖恢复。

#### Scenario: ONES 登录成功并返回令牌
- **WHEN** ONES 登录响应包含用户令牌
- **THEN** 系统在当前请求内丢弃令牌，仅保留允许的身份与 Team 字段

### Requirement: 外部身份生命周期可管理
系统 SHALL 区分提供方治理动作：钉钉身份继续由管理员按受信候选进行启停和软解绑；ONES 身份由本人绑定、重新验证和软解绑，管理员只可查看、停用和审计，不得启用、代验证或代解绑 ONES。

#### Scenario: 管理员停用 ONES 身份
- **WHEN** 管理员使用当前 Revision 停用 ONES 身份
- **THEN** 系统停用并记录审计，重新启用必须由本人完成新一轮验证

#### Scenario: 管理员尝试解绑 ONES 身份
- **WHEN** 管理员调用通用身份解绑接口处理 ONES 身份
- **THEN** 系统拒绝且保持身份事实不变

### Requirement: 身份状态参与运行时身份解析

钉钉消息入口 SHALL 仅把启用用户的启用钉钉身份解析为系统用户；ONES 身份在本阶段 SHALL 仅作为账号关联信息，不得触发 ONES 业务调用。

#### Scenario: 启用用户通过启用钉钉身份发消息

- **WHEN** 钉钉消息来自已绑定且启用的身份，并且系统用户处于启用状态
- **THEN** 系统 SHALL 解析到该系统用户并继续执行现有授权和 Agent 流程

#### Scenario: 停用或解绑的钉钉身份发消息

- **WHEN** 钉钉消息来自停用或已解绑的身份
- **THEN** 系统 SHALL 按未映射身份拒绝处理，并通过现有安全错误投递路径返回可理解结果

#### Scenario: 已停用用户的钉钉身份发消息

- **WHEN** 钉钉身份本身启用但所属系统用户已停用
- **THEN** 系统 SHALL 拒绝创建 Agent 请求，不得绕过用户状态

#### Scenario: 保存 ONES 身份

- **WHEN** ONES 身份绑定完成
- **THEN** 系统 MUST NOT 因该绑定自动调用需求、任务、缺陷或其他 ONES 业务接口

### Requirement: 外部身份写操作受统一安全控制

所有外部身份绑定和状态变更接口 SHALL 复用现有管理端认证、CSRF、`identity:manage` 权限和安全审计机制。

#### Scenario: 无身份管理权限发起绑定

- **WHEN** 已认证用户不具备 `identity:manage` 权限却提交绑定请求
- **THEN** 系统 SHALL 拒绝请求且不得访问 ONES 登录端点或修改身份数据

#### Scenario: 成功或失败的身份管理操作

- **WHEN** 管理员执行钉钉或 ONES 绑定、启用、停用或解绑
- **THEN** 系统 SHALL 写入不含凭据和令牌的审计事件，记录操作者、目标用户、提供方、动作和结果

### Requirement: ONES Mock 支持身份绑定验证

开发测试环境 SHALL 提供独立 Docker Compose ONES Mock，用于验证成功登录、无效凭据和异常响应，不得依赖真实 ONES 凭据。

#### Scenario: 使用 Mock 完成 ONES 绑定

- **WHEN** 测试环境启动 ONES Mock 并使用约定测试账号发起绑定
- **THEN** 系统 SHALL 完成服务端验证并创建符合字段白名单的 ONES 身份

#### Scenario: Mock 返回无效凭据

- **WHEN** 测试使用错误密码调用 ONES Mock
- **THEN** 系统 SHALL 返回验证失败且数据库中不得出现该次失败产生的身份记录

### Requirement: 本阶段不接入 ONES 业务能力
ONES 身份绑定 SHALL 独立于工具运行时，不创建 API Capability、API Connection、业务调用 Token 或 MCP Tool 调用凭据。未来 ONES MCP 凭据必须由独立规格定义。

#### Scenario: 完成 ONES 身份绑定
- **WHEN** 用户完成绑定或重新验证
- **THEN** 系统只更新身份事实，不授予或触发任何 ONES 业务调用能力


<!-- Reconciled from mcp_new capability: `external-identity-presentation` -->

### Requirement: 本人和治理接口使用不同身份投影
系统 MUST 根据“我的外部身份”和“人员管理 → 用户详情”两个入口分别返回本人投影和治理投影，不得返回完整数据库行后仅依赖前端隐藏越权字段；即使管理员查看自己的人员记录，人员详情仍 MUST 使用治理投影。

#### Scenario: 用户查看我的外部身份
- **WHEN** 已认证用户打开“我的外部身份”
- **THEN** 系统只从认证会话确定本人并返回本人允许字段，不读取或返回其他用户、应用观察、治理 Revision 或原始错误码

#### Scenario: 管理员查看自己的人员详情
- **WHEN** 管理员从人员管理打开自己的用户记录
- **THEN** 系统按治理权限返回治理投影，不自动切换为本人自助模式

#### Scenario: 前端请求未授权技术字段
- **WHEN** 本人接口请求包含展开应用观察、凭据 Revision 或错误码的参数
- **THEN** 系统忽略或拒绝请求且响应中不包含这些字段

### Requirement: 钉钉本人摘要使用友好企业身份字段
钉钉本人摘要 SHALL 展示钉钉昵称、企业名称、身份状态和最近使用；本人只允许展开自己的钉钉用户 ID 与 Corp ID，不得返回应用观察、Connector ID、数据 Revision、昵称历史或治理动作。

#### Scenario: 本人钉钉昵称已获取
- **WHEN** 当前用户存在启用钉钉身份和非空受信昵称
- **THEN** 页面以昵称作为身份名称，并展示企业名称、状态和最近使用

#### Scenario: 本人钉钉昵称尚未获取
- **WHEN** 当前身份没有可验证的非空昵称
- **THEN** 页面显示“尚未从钉钉获取昵称”，不得使用平台人员姓名冒充钉钉昵称

#### Scenario: 本人展开钉钉账户详情
- **WHEN** 当前用户展开自己的钉钉账户详情
- **THEN** 页面只增加显示钉钉用户 ID 与 Corp ID，且仍不提供本人绑定、启停或解绑动作

### Requirement: 钉钉治理摘要分层展示来源事实
钉钉治理摘要 SHALL 默认展示昵称、企业名称、身份状态和最近使用；管理员技术详情 MAY 展示钉钉用户 ID、Corp ID、绑定确认时间、身份 Revision 以及按应用名称汇总的首次和最近观察时间，但 MUST NOT 把内部 Connector ID 作为身份卡日常信息。

#### Scenario: 管理员查看多应用观察身份
- **WHEN** 身份已经通过同企业多个应用被观察
- **THEN** 默认卡仍只显示一个身份，技术详情显示“经 N 个钉钉应用观察”及每个应用名称和时间

#### Scenario: 管理员需要 Connector ID 排障
- **WHEN** 管理员从身份卡查看应用观察
- **THEN** 身份响应不直接返回 Connector ID，并提供进入对应应用连接配置或审计页面的路径

### Requirement: ONES 用户名称只来自验证结果
系统 SHALL 将 ONES 登录验证接口返回的用户 `name` 保存并展示为“ONES 用户名称”，每次本人重新验证成功后刷新；管理员不得手工修改，系统不得以平台人员姓名、登录邮箱或其他内部字段代替。

#### Scenario: ONES 返回用户名称
- **WHEN** 本人验证成功且 ONES 响应包含有效用户名称
- **THEN** 系统保存最新名称并在本人和治理摘要中展示

#### Scenario: ONES 未返回用户名称
- **WHEN** 验证响应没有可用用户名称
- **THEN** 页面显示“ONES 未返回用户名称”，不回退到平台人员显示名称

#### Scenario: 查看 ONES 登录字段
- **WHEN** 本人或管理员查看 ONES 身份
- **THEN** 页面不展示登录邮箱或密码，也不暗示平台持久化了这些登录字段

### Requirement: ONES 保存并展示已验证 Team 名称和 ID
确认 ONES Verification Challenge 时，系统 MUST 保存本次响应的完整已验证 Team 候选 `[{id, name}]` 和单一默认 Team，并 MUST 以最新成功验证集合整体替换旧集合；不再返回的 Team 不得继续可选。

#### Scenario: 验证返回多个有名称 Team
- **WHEN** 用户从最新验证候选中选择一个默认 Team
- **THEN** 系统保存所有候选的名称与 ID，默认摘要显示“Team 名称（Team ID）”，其他候选进入“可用 Team”折叠区域

#### Scenario: Team 没有名称
- **WHEN** 某个验证候选只有 Team ID
- **THEN** 页面显示 Team ID 并标记“名称暂不可用”，不得生成虚假 Team 名称

#### Scenario: 重新验证后 Team 被撤销
- **WHEN** 最新验证响应不再包含旧候选 Team
- **THEN** 系统从当前候选集合移除该 Team，且不得允许继续选择

#### Scenario: 迁移旧 ONES Team ID
- **WHEN** 现有 ONES 身份只有 `team_uuids` 而没有名称
- **THEN** 系统非破坏转换为名称为空的结构化候选，保留默认 Team 和个人凭据，并在下次重新验证后刷新名称

### Requirement: ONES 身份与凭据状态分别治理
ONES 身份页面 MUST 只治理身份绑定状态；用于旧 API Capability 的个人业务调用凭据状态、Revision、最近调用事实和错误码 MUST 删除，且身份不得因 Credential 不存在而显示为不可用。

#### Scenario: 身份已启用且没有个人业务调用凭据
- **WHEN** 当前 ONES 身份已启用并具有已验证 Team
- **THEN** 本人摘要显示身份已绑定，不提示缺少 Credential 或要求为业务调用重新验证

### Requirement: ONES 默认摘要只展示业务字段
ONES 本人与治理摘要 SHALL 展示用户名称、身份状态、默认 Team、最近验证和适用操作；MUST NOT 展示 API Connection、个人 Credential、MCP 状态或调用错误。

#### Scenario: ONES 身份已绑定
- **WHEN** 页面加载具有默认 Team 的当前身份
- **THEN** 默认卡展示身份与 Team 事实，不展示 Connection/Credential Revision

### Requirement: ONES 账户详情按本人和管理员划分
系统 SHALL 允许本人展开自己的 ONES User ID 和全部已验证 Team；管理员治理详情 SHALL 只展示身份记录 ID、Revision、状态和验证时间，MUST NOT 显示邮箱密码表单、API Connection、个人 Credential 或代用户重新验证入口。

#### Scenario: 管理员展开 ONES 技术详情
- **WHEN** 具备身份治理权限的管理员查看他人 ONES 身份
- **THEN** 系统只返回允许的身份元数据和审计事实

### Requirement: 身份响应根本不包含认证材料
本人和治理外部身份接口 MUST NOT 返回 Token、密码、可逆密文、认证 Header、Client Secret、Session Webhook、Verification Challenge 内部 Token 或原始外部响应；前端不得通过日志或其他管理接口拼接这些材料。

#### Scenario: 管理员拥有凭据治理权限
- **WHEN** 管理员读取他人的 ONES 技术详情
- **THEN** 响应仍只包含状态与安全元数据，不返回 Token、密文或登录字段

#### Scenario: 身份接口序列化数据库记录
- **WHEN** 底层记录包含 Secret reference、密文或内部 Challenge 标识
- **THEN** 专用响应白名单排除这些字段，测试证明它们不出现在响应 JSON


<!-- Reconciled from mcp_new capability: `external-identity-ui-prototype` -->

### Requirement: 原型以内部联系人为统一权限主体
系统 SHALL 以内部联系人作为唯一平台用户和授权主体，并展示钉钉、ONES及未来其他系统账号作为该人员的外部身份映射；页面 MUST NOT 将外部账号直接展示为独立平台权限主体。

#### Scenario: 查看内部用户的多个外部身份
- **WHEN** 用户查看人员身份关系卡
- **THEN** 页面展示一个内部用户关联钉钉账号、ONES账号和其他系统扩展位
- **AND** 每个关联都显示Provider、外部主体、用途、租户或连接及验证状态

### Requirement: 原型展示外部身份的不同用途
系统 SHALL 区分消息来源、投递目标、业务主体和目录引用等身份用途，使钉钉账号和ONES账号在同一内部用户下承担不同职责。

#### Scenario: 对比钉钉和ONES身份
- **WHEN** 用户查看同一人员的钉钉与ONES关联
- **THEN** 钉钉身份展示消息来源或投递目标用途
- **AND** ONES身份展示需求、任务、缺陷等业务主体用途

### Requirement: 原型明确身份关联不等于授权
系统 MUST 展示外部身份关联只用于确定可信主体，最终权限仍由内部角色、业务应用、Capability、API平台和外部系统原生权限共同约束。

#### Scenario: 查看ONES已关联身份
- **WHEN** ONES账号显示为已验证关联
- **THEN** 页面同时说明关联不会授予全部ONES项目或缺陷权限
- **AND** 展示平台角色与ONES原生权限仍独立生效

### Requirement: 原型展示身份生命周期与冲突治理
系统 SHALL 展示已验证、待关联、冲突和停用等身份状态，并通过静态摘要表现管理员绑定、自助验证、目录匹配和迁移等可能来源；本变更 MUST NOT 实现真实绑定或自动匹配。

#### Scenario: 查看待关联账号
- **WHEN** 外部系统存在尚未对应内部人员的示例账号
- **THEN** 页面将其标记为待关联并展示非敏感匹配提示
- **AND** 不依据姓名、显示名或邮箱自动完成关联

#### Scenario: 查看身份冲突
- **WHEN** 示例外部账号可能对应多个内部人员或已经绑定其他人员
- **THEN** 页面显示冲突状态和需要人工处理的说明
- **AND** 不提供可以绕过唯一性约束的操作

### Requirement: 原型区分群会话身份和消息发送人身份
系统 SHALL 在钉钉群聊示例中展示Conversation用于会话上下文、当前发送人用于权限解析，二者 MUST NOT 合并为群共享业务身份。

#### Scenario: 群成员具有不同业务权限
- **WHEN** 原型展示两个群成员关联不同ONES账号或数据范围
- **THEN** 页面说明相同群会话中的API调用仍按各自内部用户和外部身份执行
- **AND** 不展示群级共享ONES身份

### Requirement: 原型不暴露外部系统凭据和真实身份数据
系统 MUST 使用虚构标识和脱敏状态展示外部账号关系，并 MUST NOT 展示钉钉AppSecret、ONES凭据、Webhook Secret、内部Secret URI或真实人员数据。

#### Scenario: 查看外部系统接入和人员关联
- **WHEN** 用户查看钉钉、ONES或Webhook相关区域
- **THEN** 页面只展示已配置、待更新、已验证等状态和虚构主体标识
- **AND** 不展示任何可用于访问外部系统的凭据值


<!-- Reconciled from mcp_new capability: `identity-authorization-bootstrap-reset` -->

### Requirement: 重置只能通过受控运维入口执行
系统 SHALL 仅允许具有主机和数据库运维权限的操作者通过专用命令执行身份与授权重置，MUST NOT 提供可由普通 Web 会话、Agent、Channel 或公开 API 直接触发的重置接口。执行前 MUST 确认角色授权控制中心所需迁移已全部应用。

#### Scenario: Web 管理员尝试触发重置
- **WHEN** 任意 Web 会话请求身份与授权重置
- **THEN** 系统拒绝请求，不创建重置操作，也不改变身份或授权数据

#### Scenario: 数据库版本不满足要求
- **WHEN** 运维命令发现角色授权控制中心迁移未完成或数据库版本不匹配
- **THEN** 预检失败并返回中文安全说明，不进入准备或执行阶段

### Requirement: 重置范围必须明确且完整
系统 SHALL 删除全部旧人员账号、服务账号、密码凭据、外部身份绑定、登录会话、角色、角色成员关系、角色管理能力、角色业务应用授权、角色业务能力与数据范围、旧 `permission_policy` 和旧 `platform_access_grant`。系统 MUST 保留业务应用、Agent Profile/Revision/Publication、渠道、Connector、运行与投递记录、钉钉未绑定候选消息和审计历史。

#### Scenario: 预检展示影响范围
- **WHEN** 操作者执行重置演练
- **THEN** 系统按实体类型输出待删除数量、待保留数量和依赖处置数量，不输出用户名以外的敏感身份信息、消息正文或任何凭据

#### Scenario: 重置成功后检查旧事实
- **WHEN** 重置操作完成
- **THEN** 除本次初始化产生的新主体和授权事实外，所有旧身份与授权表均不存在旧记录，受保护业务配置和历史记录仍可查询

### Requirement: 引用旧主体的依赖必须先安全改写
系统 SHALL 在删除旧主体前枚举所有数据库外键和逻辑引用。历史记录 MUST 固化不含敏感信息的主体快照并改为允许主体被删除；仍在使用旧服务账号的 Trigger Binding 或 Webhook Trigger MUST 原子改绑到新建的停用服务账号并保持入口停用，业务应用 owner 等可选引用 MUST 清空并进入待重配清单。系统 MUST NOT 使用匿名主体、平台管理员或旧主体 ID 作为隐式回退。

#### Scenario: Webhook 历史事件引用旧服务账号
- **WHEN** 历史 Webhook Event 引用即将删除的服务账号
- **THEN** 系统先保存不可变的安全主体摘要，再解除强外键引用，并保留事件、Job 和审计链路

#### Scenario: 启用的 Trigger 引用旧服务账号
- **WHEN** 现有 Trigger Binding 或 Webhook Trigger 使用即将删除的服务账号
- **THEN** 系统创建新的停用服务账号、改写运行配置引用、停用入口并在中文重配清单中标记原因

#### Scenario: 发现未知强依赖
- **WHEN** 预检发现没有处置规则的非空外键或逻辑主体引用
- **THEN** 系统阻止准备和执行，报告表名、字段和安全摘要，不进行部分删除

### Requirement: 执行前必须创建并验证可恢复备份
系统 SHALL 在准备阶段创建 PostgreSQL 自包含备份，记录数据库版本、迁移版本、文件大小和 SHA-256 摘要，并 MUST 使用恢复工具验证备份目录可读。备份路径和元数据可以记录，数据库密码、连接 Secret 和备份内容不得进入日志或审计。

#### Scenario: 备份验证成功
- **WHEN** 备份创建完成且恢复工具能够列出其目录
- **THEN** 重置操作进入 `PREPARED`，并固定本次影响清单摘要和备份摘要

#### Scenario: 备份失败或不可读
- **WHEN** 备份命令失败、文件为空、摘要不一致或恢复工具无法读取
- **THEN** 重置操作保持未执行，系统退出维护准备并显示中文失败说明

### Requirement: 重置采用两阶段确认和全局维护锁
系统 SHALL 将预检/准备与执行分为两个阶段。执行阶段 MUST 校验未过期的重置操作 ID、准备时影响清单摘要、操作者在交互式终端输入的指定确认短语，以及全局维护锁。维护锁生效后 MUST 阻止新登录、身份绑定、授权写入、Channel/Webhook 入站创建 Job 和结果投递，并等待或停止现有写入者。

#### Scenario: 数据在准备后发生变化
- **WHEN** 执行时重新计算的影响清单摘要与准备阶段不同
- **THEN** 系统拒绝执行并要求重新预检和准备

#### Scenario: 确认短语错误
- **WHEN** 操作者未在交互式终端输入与操作 ID 对应的确认短语
- **THEN** 系统不获取执行锁、不删除数据，并返回中文提示

#### Scenario: 存在未停止的写入者
- **WHEN** 维护锁生效后仍有 API、Worker 或 Runtime 持有写入租约
- **THEN** 系统在有界等待后中止执行，不开始删除事务

### Requirement: 身份与授权重置必须原子提交
系统 SHALL 在单个数据库事务中完成历史引用改写、旧身份与授权删除、替代服务账号创建与依赖停用、新平台管理员和系统角色创建、严格模式配置写入以及重置台账更新。任一步骤失败时 MUST 回滚整个事务，不得留下部分清理或多个平台管理员。

#### Scenario: 删除过程中发生外键错误
- **WHEN** 任一旧主体因未处理引用而无法删除
- **THEN** 整个事务回滚，原身份、授权、入口状态和模式保持不变，操作标记为失败

#### Scenario: 相同操作重复执行
- **WHEN** 已成功或正在执行的操作 ID 再次收到执行请求
- **THEN** 系统拒绝重复执行，不生成第二套管理员、服务账号或凭据

### Requirement: 初始化唯一的平台管理员
系统 SHALL 在重置事务中创建且仅创建一个启用的人员账号，用户名固定为 `platform-admin`，并创建或重建唯一的受保护系统角色 `platform-admin` 及其启用成员关系。该角色 MUST 获得全部当前及未来 Web 管理能力，但 MUST NOT 获得任何业务应用、工具、环境、基地或车间访问权限。

#### Scenario: 管理员初始化完成
- **WHEN** 重置事务提交
- **THEN** 系统恰有一个启用人员账号属于受保护 `platform-admin` 角色，且该账号的业务应用有效授权集合为空

#### Scenario: 初始化不变量不成立
- **WHEN** 事务内验证发现人员管理员数量不是一、系统角色不受保护或存在业务授权
- **THEN** 系统回滚重置事务并标记验证失败

### Requirement: 初始凭据必须一次性安全交付
系统 SHALL 使用密码学安全随机源生成满足当前强度策略的初始密码，只在进程内存和操作者指定的全新凭据文件中短暂出现。凭据文件 MUST 使用独占创建和 `0600` 权限、位于仓库外的明确绝对路径，并在数据库中仅保存 Argon2 哈希；明文 MUST NOT 出现在命令参数、标准输出、标准错误、日志、审计、API 响应、代码、测试快照或 OpenSpec 产物中。

#### Scenario: 凭据文件已存在或权限不安全
- **WHEN** 操作者指定的输出文件已存在、位于仓库内或无法保证仅属主可读写
- **THEN** 系统在生成密码前拒绝执行，不覆盖文件

#### Scenario: 数据库事务失败
- **WHEN** 凭据文件已安全写入但数据库事务未提交
- **THEN** 系统使该凭据不可用于登录并安全清理临时文件；若进程异常退出，恢复检查必须将未成功操作对应文件标记为无效

#### Scenario: 执行成功
- **WHEN** 重置事务和凭据文件持久化均成功
- **THEN** 命令只返回操作 ID、凭据文件路径和安全校验摘要，不返回初始密码

### Requirement: 首次登录必须修改初始密码
系统 SHALL 为新平台管理员密码凭据保存 `must_change_password` 或等价状态。使用一次性初始密码登录后，系统 MUST 只允许访问改密、退出和必要的会话校验接口；成功改密必须清除强制状态、撤销该账号全部会话并使凭据文件中的初始密码失效。

#### Scenario: 首次登录访问角色页面
- **WHEN** 新平台管理员尚未修改初始密码便访问角色与授权页面
- **THEN** 后端拒绝业务请求，前端跳转到中文首次改密页面

#### Scenario: 首次改密成功
- **WHEN** 用户提交正确初始密码和符合策略的新密码
- **THEN** 系统更新 Argon2 哈希、清除强制改密状态、撤销旧会话并要求用新密码重新登录

### Requirement: 重置完成后只允许严格角色授权
系统 SHALL 在事务提交后将业务应用授权模式切换为 `strict_application_role`，并 MUST 禁止旧用户、旧角色、直接用户策略、旧项目或 Agent allowlist 参与新的授权决定。替代服务账号在管理员重新启用并显式分配业务角色前不得触发应用。

#### Scenario: 旧钉钉身份再次发消息
- **WHEN** 已删除绑定的钉钉用户再次向机器人发送消息
- **THEN** 系统将其作为未绑定候选处理，不创建 Agent Job，并返回或记录中文绑定提示

#### Scenario: 新平台管理员尝试运行应用
- **WHEN** 仅有 `platform-admin` 角色的新管理员尝试运行任一业务应用
- **THEN** 系统以中文提示“当前用户无权使用该业务应用”，且不回退到旧授权

#### Scenario: 停用替代服务账号触发 Webhook
- **WHEN** 重置后尚未重新配置的 Webhook 入口收到请求
- **THEN** 系统拒绝入口且不创建 Agent Job，不使用平台管理员或匿名主体执行

### Requirement: 重置必须具有可验证台账和安全审计
系统 SHALL 为每次重置保存不可变操作台账，至少包含状态、阶段时间、数据库与迁移版本、影响清单摘要、备份摘要、替代主体数量、停用依赖数量、最终不变量和错误码。审计 MUST 使用系统运维主体快照，不依赖被删除用户，并 MUST NOT 保存密码、Token、Secret、模型 API Key、消息正文或完整外部身份标识。

#### Scenario: 重置成功
- **WHEN** 全部提交后验证通过
- **THEN** 操作台账标记 `SUCCEEDED`，审计记录删除计数、保留计数、唯一管理员和严格模式结果

#### Scenario: 重置失败
- **WHEN** 准备、执行或验证任一阶段失败
- **THEN** 操作台账记录失败阶段和安全错误码，日志与用户提示不暴露敏感内容

### Requirement: 成功后的恢复必须遵循显式手册
系统 SHALL 提供经过演练的恢复命令和检查清单。事务提交前的错误 MUST 自动回滚；提交后的恢复 MUST 进入维护模式、先导出重置后安全审计、校验备份摘要、恢复完整数据库、重建容器并重新验证身份和授权模式，MUST NOT 仅把系统切回兼容模式作为回滚。

#### Scenario: 操作者恢复已成功的重置
- **WHEN** 操作者使用匹配本次操作的已验证备份执行恢复
- **THEN** 系统恢复重置前数据库状态，并要求完成迁移、容器健康和授权链路验证后才退出维护模式

### Requirement: 所有运维与用户可见提示使用中文
系统 SHALL 对预检报告、危险确认、维护状态、首次改密、登录限制、授权拒绝、重配清单和恢复检查使用中文；稳定 ID、状态码、表名、字段名和安全 `error_code` 可以保留英文。

#### Scenario: 内部命令异常
- **WHEN** 重置命令遇到未预期异常
- **THEN** 操作者只看到中文安全说明和可关联的操作 ID，内部堆栈不得通过 Web 页面或 Channel 返回


<!-- Reconciled from mcp_new capability: `multi-provider-external-identity-management` -->

### Requirement: 外部身份Connection定义受信Provider实例
系统 SHALL 持久化外部身份Connection的稳定编码、Provider、tenant/instance、验证模式、状态和受控连接引用，并 MUST 区分DingTalk Channel Connector与ONES业务系统Connection。

#### Scenario: 注册钉钉Connection
- **WHEN** 管理员选择启用且允许ingress的钉钉企业Stream Connector
- **THEN** 系统创建或读取引用该Connector的DingTalk身份Connection
- **AND** 不复制AppSecret或Stream凭据

#### Scenario: 注册ONES Connection
- **WHEN** 有Connection管理权限的管理员提交受支持ONES Provider、唯一实例编码和通过allowlist校验的Base URL
- **THEN** 系统保存非敏感Connection配置与revision
- **AND** 不允许配置任意登录Path、Method、Header或请求模板

#### Scenario: 禁用Connection
- **WHEN** 管理员禁用一个Connection
- **THEN** 该Connection下的身份不能用于新的解析或验证
- **AND** 已有Identity、Claim和审计历史保持不变

### Requirement: 一个内部自然人可以关联多个Provider身份
系统 SHALL 允许同一启用自然人关联多个钉钉企业、ONES实例和未来Provider身份，并 MUST 禁止服务账号绑定个人外部身份。

#### Scenario: 用户同时关联钉钉和ONES
- **WHEN** 同一内部用户拥有已验证钉钉身份和已验证ONES身份
- **THEN** 两个外部身份都指向同一个内部用户ID
- **AND** 各自保留独立Provider、Connection、subject、状态和用途

#### Scenario: 用户关联两个ONES实例
- **WHEN** 用户分别验证两个不同Connection上的ONES账号
- **THEN** 系统创建两个独立身份映射
- **AND** 不因外部UUID文本相同而跨实例合并

#### Scenario: 服务账号尝试绑定
- **WHEN** 管理员或服务账号尝试为`account_type=service`创建外部身份或Claim
- **THEN** 系统拒绝操作并记录安全审计

### Requirement: 外部主体在受信范围内唯一绑定
系统 MUST 使用Provider、tenant/Connection范围和external subject ID唯一识别外部身份，MUST NOT依据姓名、昵称、邮箱或手机号自动关联。

#### Scenario: 唯一外部主体首次绑定
- **WHEN** 验证结果中的subject在该Provider和Connection范围内尚未绑定
- **THEN** 系统原子创建指向目标内部用户的身份

#### Scenario: 相同主体绑定同一用户
- **WHEN** 同一用户再次验证已经属于自己的外部主体
- **THEN** 系统幂等刷新验证时间和受控Provider上下文
- **AND** 不创建重复身份

#### Scenario: 相同主体属于另一个用户
- **WHEN** 验证结果中的subject已经绑定其它内部用户
- **THEN** 系统保留原身份并把当前Claim标记为conflict
- **AND** 不自动覆盖、合并或转移身份

### Requirement: 身份可用状态和验证状态分别治理
系统 SHALL 分别维护管理员enabled/disabled状态与pending/verified/conflict/revoked验证状态，只有启用用户、启用Connection、启用Identity和verified状态同时满足时身份才可信。

#### Scenario: pending身份
- **WHEN** 管理员只创建尚未完成Provider证明的关联Claim
- **THEN** 页面显示pending且系统不把它用于Channel或业务主体解析

#### Scenario: verified身份被禁用
- **WHEN** 管理员禁用一个verified身份
- **THEN** 该身份停止解析新请求
- **AND** 其它身份、内部用户和历史记录不受影响

#### Scenario: Connection重新启用
- **WHEN** 管理员重新启用Connection但Identity本身仍disabled
- **THEN** 该身份继续不可用直到显式启用

### Requirement: Claim承载待验证和冲突流程
系统 SHALL 使用带revision的Claim记录pending、verified、conflict、rejected、expired和cancelled流程，并 MUST 保留验证与冲突治理的安全历史。

#### Scenario: 管理员创建待验证Claim
- **WHEN** 管理员为启用自然人选择受信Connection并创建Claim
- **THEN** 系统保存pending Claim及创建人
- **AND** 不要求或保存外部系统密码

#### Scenario: 用户完成自己的Claim
- **WHEN** 当前登录用户对属于自己的pending Claim完成Provider验证
- **THEN** 系统事务创建或刷新Identity并把Claim标记为verified

#### Scenario: 管理员查看冲突
- **WHEN** Claim进入conflict
- **THEN** 有冲突治理权限的管理员能看到当前绑定和Claim的安全摘要
- **AND** 看不到验证密码、Provider Token或原始响应

#### Scenario: 并发处理Claim
- **WHEN** 两个操作者基于相同旧revision处理Claim
- **THEN** 系统只接受第一个更新并向第二个返回409

### Requirement: 冲突处理不得一键强制转移身份
系统 SHALL 允许管理员保留现有绑定、拒绝或取消冲突Claim，并 MUST 要求身份转移经过显式停用旧绑定和目标用户重新验证的多步流程。

#### Scenario: 保留现有绑定
- **WHEN** 管理员确认现有内部用户归属正确
- **THEN** 系统拒绝冲突Claim并保留原Identity

#### Scenario: 需要转移归属
- **WHEN** 管理员判断原Identity归属错误
- **THEN** 系统要求先使用expected revision撤销旧Identity，再让目标用户重新验证
- **AND** 不提供绕过唯一约束的强制覆盖命令

### Requirement: 现有钉钉绑定平滑迁移到通用模型
系统 SHALL 为既有启用钉钉Connector建立Connection，并 MUST 将现有钉钉身份标记为verified/admin_asserted而不改变其内部用户、tenant、subject、connector和enabled状态。

#### Scenario: 迁移既有钉钉用户
- **WHEN** 迁移发现可唯一对应启用Connector的现有钉钉身份
- **THEN** 系统关联Connection并保留当前解析语义

#### Scenario: 现有身份无法找到Connector
- **WHEN** 迁移无法唯一确定可信Connection
- **THEN** 系统不伪造verified映射并生成待人工处理报告
- **AND** 不把该身份错误关联到其它tenant

### Requirement: 身份管理API与Web使用真实数据和细粒度权限
系统 SHALL 提供Connection、Provider、用户Identity、Claim、Conflict以及个人Identity的管理API和页面，并 MUST 根据用户自身或identity管理权限限制范围。

#### Scenario: 管理员查看用户详情
- **WHEN** 有用户与身份管理权限的管理员查看内部用户
- **THEN** 页面显示角色摘要、Identity、Claim、验证方法、最近验证时间、团队/租户上下文和状态
- **AND** 不显示Secret或完整Provider响应

#### Scenario: 用户查看自己的身份
- **WHEN** 普通用户进入“我的外部身份”
- **THEN** 页面只返回当前用户的Identity与Claim
- **AND** 用户不能通过修改路径或请求体读取其它用户

#### Scenario: 前端发生revision冲突
- **WHEN** Identity、Claim或Connection写请求返回409
- **THEN** 页面要求刷新并展示数据已变化
- **AND** 不静默覆盖服务器状态

### Requirement: 身份关联不授予额外业务权限
系统 MUST 把外部身份映射仅作为可信主体解析，MUST NOT因为成功关联钉钉、ONES或其它Provider而自动创建角色、平台数据范围、Business Application或API Capability权限。

#### Scenario: ONES身份验证成功
- **WHEN** 用户成功关联ONES账号
- **THEN** 用户的内部角色和平台权限保持原样
- **AND** ONES原生项目权限仍由ONES或未来API平台判断

#### Scenario: 群聊成员身份不同
- **WHEN** 同一钉钉群中的两名发送人关联不同内部用户和ONES身份
- **THEN** 系统按每条消息的发送人解析主体
- **AND** 不创建群级共享ONES身份或权限

### Requirement: 外部身份管理不得暴露凭据和敏感载荷
系统 MUST 在数据库、API、页面、日志和审计中排除密码、Session Token、CSRF值、Provider Token、AppSecret、完整Webhook URL和原始外部响应。

#### Scenario: 查看身份与验证历史
- **WHEN** 用户或管理员查看Identity、Claim或Verification Attempt
- **THEN** 系统只返回Provider、Connection、subject、受控上下文、状态、方法和时间
- **AND** 不返回任何可重放的认证材料


<!-- Reconciled from mcp_new capability: `ones-identity-verification` -->

### Requirement: ONES验证只通过受信Connection发起
这里的受信 Connection SHALL 收敛为服务端固定的 ONES 身份提供方配置，而不是已退役的通用 API Connection。系统 MUST 使用固定 Base URL、代码内固定登录 Path 和主机白名单执行验证，不接受浏览器或请求体提供 URL、Method、Path、Header、代理、API Connection Revision 或 MCP Server。

#### Scenario: 身份提供方未配置
- **WHEN** 固定 ONES 身份配置不可用
- **THEN** 系统拒绝验证且不尝试旧 API Connection 或任意 MCP 地址

### Requirement: ONES验证材料只存在于单次请求内
系统 MUST 把ONES email和password作为短生命周期Verification Proof，并 MUST NOT将password或登录响应Token写入数据库、Identity、Claim、Verification Attempt、Cache、日志、审计、API响应或浏览器持久化存储。

#### Scenario: 验证成功
- **WHEN** ONES返回包含用户UUID、Token和团队的成功响应
- **THEN** Adapter提取允许字段并丢弃Token和原始响应
- **AND** Service、Repository和前端只接收不含Token的规范化主体

#### Scenario: 验证失败
- **WHEN** ONES拒绝email/password
- **THEN** 系统返回统一凭据失败错误并清空前端密码字段
- **AND** 错误和审计不包含email、password、Token或上游正文

#### Scenario: 运行日志扫描
- **WHEN** 成功或失败验证完成
- **THEN** 日志只包含correlation ID、Connection、actor、outcome和安全错误码
- **AND** 不包含请求体或响应体

### Requirement: ONES响应被严格校验并规范化
系统 SHALL 限制响应大小、要求JSON并校验`user.uuid`、可选展示字段和`teams[].uuid`，MUST 拒绝缺少稳定subject或团队上下文的响应。

#### Scenario: 合法登录响应
- **WHEN** ONES返回非空`user.uuid`、用户展示信息、Token和至少一个team UUID
- **THEN** 系统将`user.uuid`作为external subject ID
- **AND** 只把去重排序后的team UUID列表保存为受控Provider上下文

#### Scenario: 响应缺少user UUID
- **WHEN** 上游返回200但`user.uuid`为空、类型错误或缺失
- **THEN** 系统将响应视为协议错误并不创建Identity

#### Scenario: 响应过大或不是JSON
- **WHEN** 上游响应超过限制或Content不符合JSON契约
- **THEN** 系统中止解析并返回安全上游协议错误

### Requirement: ONES网络访问执行出站安全策略
系统 MUST 校验Connection scheme、Host和allowlist，禁止重定向和环境代理继承，并 SHALL 应用连接超时、读取超时与响应上限。

#### Scenario: 生产HTTPS连接
- **WHEN** 生产Connection使用allowlist中的HTTPS Host
- **THEN** 系统允许固定登录请求并执行证书校验

#### Scenario: 生产HTTP连接
- **WHEN** 生产Connection使用HTTP或Host不在allowlist
- **THEN** 系统拒绝保存或调用该Connection

#### Scenario: 本地Mock连接
- **WHEN** 开发环境显式允许insecure local且Host命中本地开发allowlist
- **THEN** 系统可以调用独立ONES Mock
- **AND** 该例外不能在生产配置中默认启用

#### Scenario: 上游重定向
- **WHEN** ONES登录端点返回重定向
- **THEN** Adapter拒绝跟随并返回安全连接错误

### Requirement: ONES验证具备限流和安全失败分类
系统 SHALL 按内部用户、Connection和来源地址限制验证频率，并 MUST 将凭据失败、限流、超时、连接失败和协议错误映射为不泄露上游细节的稳定错误码。

#### Scenario: 连续错误密码
- **WHEN** 用户在窗口期内超过允许的失败次数
- **THEN** 系统暂时拒绝新的ONES验证并返回429或等效限流错误
- **AND** 不再向ONES发送登录请求直到窗口恢复

#### Scenario: ONES超时
- **WHEN** 连接或读取超过配置时限
- **THEN** 系统返回可重试上游不可用错误
- **AND** Claim保持pending且不创建Identity

#### Scenario: ONES返回401
- **WHEN** 上游拒绝登录
- **THEN** 系统返回统一`ones_credentials_invalid`或等效错误
- **AND** 不说明邮箱是否存在

### Requirement: 成功验证原子绑定ONES身份
系统 MUST 使用不含 Token 的短时单次身份 Challenge，在确认默认 Team 时原子校验当前用户、唯一 subject、候选 Team 和现有 Identity，然后创建或刷新 Identity 并消费 Challenge。

#### Scenario: 新ONES主体验证成功
- **WHEN** 当前用户确认合法 Challenge 和候选 Team
- **THEN** 系统创建 verified/provider_login Identity 并保存最新 Team、默认 Team 和验证时间，不创建个人业务调用 Credential

### Requirement: ONES团队上下文不等于授权
系统 SHALL 保存经过验证的 Team ID/名称、默认 Team 和最近验证时间作为身份上下文，MUST NOT把 Team 自动转为内部角色、数据范围、Capability、MCP Tool 授权或业务调用 Token。

#### Scenario: 用户属于多个Team
- **WHEN** ONES 登录响应包含多个合法 Team
- **THEN** Identity 保存去重后的候选与默认 Team，内部 RBAC 保持不变

### Requirement: ONES Mock用于无真实凭据的集成验证
系统 SHALL 支持在开发测试中通过`docker-compose.ones-mock.yml`验证登录、subject/team提取、重复绑定、冲突和错误路径，并 MUST 使用明显的Mock凭据与标识。

#### Scenario: 使用Mock成功验证
- **WHEN** 开发环境指向本地ONES Mock并提交文档中的假凭据
- **THEN** 系统建立`MOCK-*` Identity和team上下文
- **AND** 数据库、日志和审计中不存在Mock返回Token

#### Scenario: 仓库敏感信息扫描
- **WHEN** 执行交付检查
- **THEN** 新增代码、测试、fixture和文档不包含真实ONES IP、邮箱、用户UUID、团队UUID或Token


<!-- Reconciled from mcp_new capability: `role-authorization-admin-console` -->

### Requirement: 管理端提供角色与授权导航和页面
系统 SHALL 在“用户与外部身份”导航组中依次提供“人员管理”“角色与授权”“未绑定钉钉用户”，并 SHALL 提供 `/users/roles` 和 `/users/roles/:roleId` 路由。

#### Scenario: 有权限管理员打开角色菜单
- **WHEN** 当前用户具有角色查看或授权管理能力
- **THEN** 导航显示“角色与授权”并允许加载角色列表

#### Scenario: 无权限用户直接访问路由
- **WHEN** 当前用户没有任何角色查看或授权管理能力
- **THEN** 前端不显示菜单，直接访问页面显示中文无权提示，后端 API 同时拒绝请求

### Requirement: 角色列表区分系统角色、自定义角色和高级例外
系统 SHALL 在角色授权中心展示自定义角色、系统角色和高级授权例外三个可辨识区域，并 MUST 显示角色状态、成员数量、管理能力摘要、业务应用摘要和更新时间。普通管理员不得编辑高级原始策略。

#### Scenario: 查看系统角色
- **WHEN** 管理员打开系统角色区域
- **THEN** 页面标记受保护角色并禁用删除、停用和关键权限编辑操作

### Requirement: 角色详情按授权区组织
系统 SHALL 在角色详情中提供“基本信息”“成员”“管理后台能力”“业务应用与数据范围”“有效权限预览”“操作记录”区域，并 MUST 根据当前操作者的分区权限将无权编辑的区域设为只读。

#### Scenario: 业务授权管理员打开复合角色
- **WHEN** 操作者只能编辑业务访问授权区
- **THEN** 页面允许修改业务应用和数据范围，同时只读显示管理后台能力且提交不得包含其修改

### Requirement: 角色授权使用勾选和明确层级配置
系统 SHALL 使用中文名称、风险说明和层级选择器配置管理能力、业务应用、只读能力、环境、基地和车间，不得要求普通管理员输入原始 `resource_type`、`resource_code`、`action`、`priority` 或工具编码。

#### Scenario: 当前只有 local 环境
- **WHEN** 管理员配置业务应用数据范围且系统只有 `local`
- **THEN** 页面显式展示并允许勾选 `local` 根节点，不展示虚假的多环境切换器

#### Scenario: 存在未保存修改
- **WHEN** 管理员切换页签或离开含有未提交勾选的角色页面
- **THEN** 页面提示存在未保存修改，防止意外丢失

### Requirement: 角色配置统一预览后原子提交
系统 SHALL 在当前可编辑授权区内暂存勾选变化，并 MUST 在提交前展示新增、撤销权限和受影响成员摘要。后端 MUST 原子保存该授权区，任一字段失败时不得部分生效。

#### Scenario: 授权区提交失败
- **WHEN** 提交同时包含有效能力和越权数据范围
- **THEN** 系统拒绝整个授权区修改并保持原配置不变

### Requirement: 人员详情和角色详情均可维护成员
系统 SHALL 支持在人员详情为单个用户分配或移除多个角色，也 SHALL 支持在角色详情批量添加、移除成员和设置可选失效时间。两处 MUST 使用同一成员事实和授权校验。

#### Scenario: 从人员详情分配多个角色
- **WHEN** 管理员为一个用户选择多个自己有权分配的角色
- **THEN** 系统原子更新成员关系并刷新该用户的有效权限摘要

### Requirement: 钉钉身份绑定可原子分配初始角色
系统 SHALL 在未绑定钉钉用户的绑定流程中允许选择零个或多个初始角色。选择角色时，身份绑定与成员关系创建 MUST 在同一个事务中完成；选择零个角色时页面 MUST 明确提示绑定后暂时不能使用业务应用。

#### Scenario: 绑定并分配多个初始角色
- **WHEN** 管理员确认把钉钉身份绑定到用户并选择多个可分配角色
- **THEN** 系统一次性完成绑定和成员创建，返回合并后的应用、数据范围和后台能力摘要

#### Scenario: 初始角色分配失败
- **WHEN** 任一所选角色已被停用、过期或超出操作者分配范围
- **THEN** 系统回滚身份绑定和全部成员变更，待绑定用户仍保留在发现列表

#### Scenario: 仅绑定身份
- **WHEN** 管理员明确选择“仅绑定身份，暂不授权”
- **THEN** 系统完成身份绑定、从未绑定列表移除该候选，并在人员详情显示“未获得应用权限”

### Requirement: 管理端提供安全的有效权限模拟
系统 SHALL 允许有权操作者按“用户 + 业务应用 + 业务能力 + 数据范围”模拟授权决策，并 MUST 返回最终允许或拒绝、来源角色、应用授权来源、数据范围来源和高级拒绝摘要。响应 MUST NOT 包含凭据、敏感条件或未脱敏原始策略。

#### Scenario: 用户缺少应用授权
- **WHEN** 管理员模拟已绑定但没有业务角色的用户访问某应用
- **THEN** 页面显示“未获得该业务应用的使用权限”，而不是暴露底层项目或 Agent 策略错误

### Requirement: 新建角色支持空白、模板和复制
系统 SHALL 允许从空白、受控系统模板或已有自定义角色创建角色。复制角色 MUST 只复制授权配置，不得复制成员；超出操作者可授权范围的项目 MUST 阻止创建。

#### Scenario: 复制已有角色
- **WHEN** 管理员复制一个已有自定义角色
- **THEN** 系统生成独立的新角色配置、保持成员为空并要求确认应用和数据范围

### Requirement: 角色编码创建后不可修改
系统 SHALL 在创建角色时生成可调整的建议编码，并 MUST 在创建成功后将编码设为不可变。中文名称、描述和用途标签可以后续修改。

#### Scenario: 编辑已有角色
- **WHEN** 管理员修改角色中文名称
- **THEN** 系统保留原角色编码和所有策略引用不变

### Requirement: 所有用户可见文案使用中文
系统 SHALL 对角色授权页面、确认提示、字段错误、权限拒绝和运行时授权变更提示使用中文；稳定编码、ID、协议名称和安全 `error_code` 可以保留英文。

#### Scenario: 后端返回内部英文错误
- **WHEN** 角色授权请求发生未预期服务器错误
- **THEN** 前端显示中文安全提示，不直接展示内部英文异常或堆栈


<!-- Reconciled from mcp_new capability: `role-authorization-model` -->

### Requirement: 自定义角色统一承载管理能力和业务访问能力
系统 SHALL 使用同一个自定义角色聚合管理后台能力、业务应用访问、只读业务能力和数据范围，且 MUST 将“平台管理角色”和“业务访问角色”仅作为模板或用途标签，不得作为互斥的授权主体类型。

#### Scenario: 复合自定义角色生效
- **WHEN** 管理员为一个自定义角色同时配置运行记录查看能力和生产诊断应用访问能力
- **THEN** 该角色的启用成员同时获得两类权限，且每类权限仍由对应后端资源和动作独立校验

### Requirement: 系统角色受到不可绕过的保护
系统 SHALL 将 `platform-admin` 标记为受保护系统角色，并 MUST 自动赋予其当前及未来全部管理后台能力、禁止删除或修改其关键能力，同时 MUST NOT 因该角色自动授予任何业务应用、工具或数据访问权限。

#### Scenario: 新增管理能力
- **WHEN** 新版本注册一个新的管理后台能力
- **THEN** `platform-admin` 无需新增策略即可获得该管理能力，其他角色默认不获得

#### Scenario: 平台管理员访问业务数据
- **WHEN** 只有 `platform-admin` 角色的用户尝试运行未显式授权的业务应用
- **THEN** 系统拒绝业务访问，但仍允许其进入授权管理页面配置业务角色

### Requirement: 角色成员关系支持状态和失效时间
系统 SHALL 允许人员账号和服务账号加入一个或多个角色，并 MUST 只展开启用角色、启用成员关系且尚未到期的成员关系。成员有效期为空时表示长期有效，到期后 MUST 立即停止参与新的权限决策。

#### Scenario: 临时成员到期
- **WHEN** 某成员关系的失效时间已经到达
- **THEN** 系统在新的授权决策中忽略该成员关系，并在管理端显示“已到期”

#### Scenario: 服务账号加入业务角色
- **WHEN** 管理员把服务账号加入仅包含业务应用、只读能力和数据范围的角色
- **THEN** 系统允许该成员关系参与非交互式业务入口授权

#### Scenario: 服务账号加入管理角色
- **WHEN** 管理员尝试把服务账号加入包含任一管理后台能力的角色
- **THEN** 系统拒绝保存并提示服务账号不能获得 Web 管理能力

### Requirement: 多角色权限按允许并集和拒绝优先求值
系统 SHALL 合并用户全部有效角色的允许权限和数据范围，并 MUST 让命中的高级显式拒绝优先于任一用户直接允许或角色允许。系统 MUST 为最终结果保留可安全展示的来源信息。

#### Scenario: 两个角色提供不同数据范围
- **WHEN** 用户通过两个有效角色获得同一业务应用下两个不同基地的允许范围
- **THEN** 用户对该应用的有效数据范围为两个基地的并集

#### Scenario: 高级拒绝覆盖角色允许
- **WHEN** 用户的角色允许某业务能力但用户主体命中该能力的高级拒绝例外
- **THEN** 系统拒绝该能力并在安全解释中标记存在高级拒绝，不暴露原始敏感策略内容

### Requirement: 角色授权按独立授权区进行并发控制
系统 SHALL 至少将角色基本信息、成员关系、管理后台能力、业务访问能力划分为独立授权区，每个授权区 MUST 使用独立 revision 或等价并发控制。一个授权区的保存 MUST 在单个数据库事务中原子完成，且不得覆盖操作者无权编辑的其它授权区。

#### Scenario: 两名管理员编辑不同授权区
- **WHEN** 平台权限管理员保存管理后台能力，同时业务授权管理员保存同一角色的业务应用范围
- **THEN** 两次操作分别按各自 revision 提交且互不覆盖

#### Scenario: 授权区版本冲突
- **WHEN** 管理员使用过期 revision 提交授权区修改
- **THEN** 系统拒绝该次修改并要求刷新，不得静默覆盖新配置

### Requirement: 角色配置变更保存后立即生效
系统 SHALL 在角色授权区或成员关系保存成功后立即使新授权参与后续决策，不得要求 Agent 或业务应用重新发布。高风险管理能力、生产数据范围扩大和高级拒绝修改 MUST 在提交前要求二次确认和变更原因。

#### Scenario: 移除成员
- **WHEN** 管理员成功移除某角色成员
- **THEN** 该成员在下一次授权检查时不再继承该角色权限

#### Scenario: 延长成员有效期
- **WHEN** 管理员延长成员有效期
- **THEN** 系统按普通成员关系更新记录原失效时间、新失效时间和操作者，但不要求单独的延长原因或审批

### Requirement: 角色分配权按目标角色显式委派
系统 SHALL 为每个自定义角色提供独立的成员分配权限，非 `platform-admin` 操作者 MUST 具有目标角色的分配权限才能添加、移除或调整成员有效期。能编辑角色某个授权区 MUST NOT 自动意味着能分配该角色。

#### Scenario: 人员管理员尝试分配平台角色
- **WHEN** 仅具有人员管理权限的操作者尝试分配未委派给自己的平台管理角色
- **THEN** 系统拒绝操作并且不创建成员关系

#### Scenario: 被委派管理员分配业务角色
- **WHEN** 操作者拥有目标业务角色的成员分配权限
- **THEN** 系统允许其为目标用户分配该角色，但不得修改角色授权配置

### Requirement: 授权编辑不得扩大到操作者可授权范围之外
系统 SHALL 将操作者的运行使用权限与可授权管理范围分开计算。非 `platform-admin` 操作者只能配置被明确委派给自己的管理资源、业务应用、业务能力和数据范围，并 MUST NOT 通过创建、复制、编辑或分配角色实现自我提权。

#### Scenario: 超出委派范围
- **WHEN** 业务授权管理员尝试把未委派给自己的业务应用或基地加入角色
- **THEN** 系统拒绝整个授权区提交并返回中文字段错误

#### Scenario: 复制角色包含越权能力
- **WHEN** 管理员复制的来源角色包含超出其可授权范围的能力
- **THEN** 系统要求移除越权项后才能创建新角色，不得静默保留

### Requirement: 最后一名平台管理员不得被移除
系统 SHALL 始终保留至少一个启用的人员账号拥有启用的 `platform-admin` 成员关系。非最后一名平台管理员可以在二次确认后移除自己的成员关系，成功后 MUST 立即刷新当前会话权限。

#### Scenario: 移除最后一名平台管理员
- **WHEN** 操作会导致系统不存在启用的 `platform-admin` 人员账号
- **THEN** 系统拒绝停用用户、停用成员关系或其它导致锁死的操作

### Requirement: 自定义角色只停用不物理删除
系统 SHALL 允许管理员停用和重新启用自定义角色，且 MUST 保留其成员、授权配置和审计记录。停用角色 MUST 立即停止参与新的授权决策，系统角色不得停用。

#### Scenario: 停用自定义角色
- **WHEN** 管理员确认停用一个自定义角色
- **THEN** 系统展示受影响成员和资源摘要、停用该角色并保留原配置

### Requirement: 角色业务工具授权必须只引用 MCP Tool Identifier
角色 SHALL 继续承载业务应用访问、稳定 MCP Tool 使用权限和业务数据范围；角色模型 MUST NOT 保存或展示 API Capability、Handler、API Connection、Resource Mapping 或 Resource Revision grant。

#### Scenario: 授权 test 环境数据库工具
- **WHEN** 管理员为角色选择应用、`query_database`/`get_schema_directory` MCP Tool 和 `environment=test` 数据范围
- **THEN** 成员的新 Job 可以在应用 Tool 子集内访问 test 目标，资源由 `tool-mcp` 唯一解析

#### Scenario: 旧 Capability 授权字段提交
- **WHEN** 角色授权请求包含 API Capability 或 Resource Mapping
- **THEN** 后端拒绝旧字段且不创建兼容 grant

### Requirement: 统一 RBAC 必须是唯一授权事实源
系统 MUST 只使用现行 `rbac_*` 角色、成员、管理能力、应用访问、MCP Tool grant 和数据范围表计算授权；MUST NOT 保留或读取 `permission_policy`、`platform_access_grant`、旧授权清理操作表或 DB-backed 测试兼容层。

#### Scenario: 从包含旧授权数据的数据库升级
- **WHEN** 数据库同时包含现行统一 RBAC 和旧 policy/grant 行
- **THEN** 迁移保留现行用户、角色、成员、应用授权和数据范围，并永久删除旧授权表而不把旧行重新解释为有效权限


<!-- Reconciled from mcp_new capability: `role-based-access-control` -->

### Requirement: 用户可以通过角色继承权限
系统 SHALL 持久化角色和用户角色关系，并 MUST 只展开 enabled 用户、enabled 角色和 enabled membership。

#### Scenario: 用户通过角色获得工具权限
- **WHEN** 启用用户属于拥有某只读工具 allow policy 的启用角色
- **THEN** 权限求值器允许该用户在其它安全条件满足时使用该工具

#### Scenario: 角色被禁用
- **WHEN** 管理员禁用一个角色
- **THEN** 该角色授予的权限不再用于新的请求，用户其它直接或角色权限保持独立

### Requirement: 权限求值统一处理用户角色和 deny
系统 SHALL 在一个统一 evaluator 中计算用户直接 policy、角色 policy、平台 access grant、资源通配符、作用域和 effect，并 MUST 让命中的显式 deny 阻止对应 allow。

#### Scenario: 角色宽泛允许但用户被明确拒绝
- **WHEN** 用户通过角色获得 `tool:*` allow，同时用户主体命中目标工具 deny
- **THEN** 系统拒绝该工具并返回安全权限原因

#### Scenario: 用户有工具权限但无数据范围
- **WHEN** 用户被允许调用数据库工具，但没有目标基地或车间 platform access grant
- **THEN** 系统拒绝工具调用且不访问目标数据源

### Requirement: 管理动作使用明确资源和 action 权限
系统 SHALL 对用户、角色、身份绑定、Agent 编辑、Agent 发布、平台配置、密钥和审计查看定义独立管理 action，并 MUST 在每个写 API 执行前授权。

#### Scenario: 用户管理员不能发布 Agent
- **WHEN** 操作者具有 `user:manage` 但不具有 `agent:publish`
- **THEN** 系统允许管理用户但拒绝发布 Agent

#### Scenario: Agent 编辑者提交草稿
- **WHEN** 操作者具有目标 Agent 的 `agent:edit`
- **THEN** 系统允许更新草稿，但发布仍要求 `agent:publish`

### Requirement: 工具授权与 Agent 分配共同生效
系统 SHALL 将用户/角色工具权限与 Agent publication 的工具分配分开管理；工具只有在两者都允许且工具本身 enabled/read-only 时才可暴露给 runtime。

#### Scenario: 用户有权限但 Agent 未分配
- **WHEN** 用户拥有 `query_loki` 权限，但当前 Agent publication 未分配该工具
- **THEN** runtime 不向模型暴露 `query_loki`

#### Scenario: Agent 已分配但用户无权限
- **WHEN** 当前 Agent publication 分配 `query_database`，但用户和角色均无该工具权限
- **THEN** runtime 不向模型暴露或执行该工具

### Requirement: 权限决策提供安全 trace 和审计
系统 SHALL 为 allow/deny 决策生成包含内部用户、角色摘要、资源、action、作用域、命中 policy/grant ID 和最终结果的安全 trace，并 MUST 不包含密码、session token、secret 或原始敏感数据。

#### Scenario: 权限被拒绝
- **WHEN** Web、钉钉、Agent 或工具请求被 RBAC 拒绝
- **THEN** 系统记录可排障的安全决策 trace，并向调用方返回不泄漏内部策略细节的错误


<!-- Reconciled from mcp_new capability: `service-account-identity` -->

### Requirement: Webhook 使用不可交互登录的服务账号
系统 SHALL 支持 `account_type=service` 的内部账号，并 MUST 禁止该账号创建密码凭证、Web session或绑定钉钉等人类外部身份。

#### Scenario: 创建 Webhook Trigger
- **WHEN** 管理员创建 Trigger 且未选择现有专用服务账号
- **THEN** 系统事务创建一个默认禁用权限的专用服务账号并绑定该 Trigger

#### Scenario: 服务账号尝试 Web 登录
- **WHEN** 调用方使用服务账号标识提交登录请求
- **THEN** 系统拒绝认证且不创建 session

#### Scenario: 服务账号绑定人类外部身份
- **WHEN** 管理员试图把钉钉或其他人类身份绑定到服务账号
- **THEN** 系统返回校验错误且不创建绑定

### Requirement: 服务账号复用统一 RBAC 和平台范围
系统 SHALL 使用 Trigger 绑定的服务账号作为 Webhook job 的内部权限主体，并 MUST 校验项目、Agent、工具和 environment/base/workshop 平台数据范围。

#### Scenario: 服务账号拥有最小诊断权限
- **WHEN** 服务账号被允许使用默认诊断 Agent、目标项目、query_loki 和指定生产范围
- **THEN** Webhook job 可以创建且 Agent 只能在该交集范围内调用 query_loki

#### Scenario: Trigger routing 超出服务账号范围
- **WHEN** 映射得到的 environment/base/workshop 不在服务账号 grant 中
- **THEN** 系统拒绝创建 job并记录范围拒绝决策

#### Scenario: Agent publication 包含未授权工具
- **WHEN** Agent publication 分配了某工具但服务账号没有该工具的 use 权限
- **THEN** 该工具不进入运行时允许集合

### Requirement: 服务账号和 Trigger 启停均为运行时闸门
系统 SHALL 在接收新事件和创建 job 时检查 Trigger、Connector、服务账号和相关 publication 状态，任一被禁用时 MUST fail closed。

#### Scenario: 禁用服务账号
- **WHEN** 管理员禁用 Trigger 绑定的服务账号
- **THEN** 后续 Webhook 请求不能创建新 job，且拒绝结果可审计

#### Scenario: 禁用 Trigger
- **WHEN** 管理员停用 Trigger 但服务账号仍启用
- **THEN** public endpoint 拒绝新事件且不影响该服务账号的其他明确授权用途

### Requirement: 服务账号操作具有独立审计主体
系统 SHALL 在 Webhook event、Agent job、tool call、permission decision 和 Delivery 证据中记录服务账号 ID、Trigger ID 和 correlation ID，MUST NOT 把行为错误归属到发布管理员或固定字符串 `grafana`。

#### Scenario: Webhook Agent 调用工具
- **WHEN** Agent 为 Webhook job 调用允许的只读工具
- **THEN** tool call 和权限审计记录 Trigger 服务账号为主体，并保留 Trigger publication 引用


<!-- Reconciled from mcp_new capability: `unbound-dingtalk-identity-discovery` -->

### Requirement: 未绑定钉钉消息形成安全发现候选

系统 SHALL 只为通过渠道认证和规范化、已持久化且明确因钉钉身份从未绑定、身份已停用或解绑、或所属用户已停用而被拒绝的新消息创建发现候选，并 MUST NOT 因此创建 Agent Job、发布 Job 消息、调用模型或 API Capability。

#### Scenario: 从未绑定用户发送私聊消息

- **WHEN** 部署本功能后，一个没有历史钉钉身份的用户向已启用机器人发送私聊消息
- **THEN** 系统 SHALL 返回现有未授权提示、创建或更新该用户的发现候选，且不得创建 Agent Job

#### Scenario: 从未绑定用户发送群聊消息

- **WHEN** 部署本功能后，一个没有历史钉钉身份的用户在群聊中向已启用机器人发送消息
- **THEN** 系统 SHALL 创建或更新同一身份候选并记录安全群会话标识，且不得触发 Agent 执行

#### Scenario: 不符合身份发现条件的入口失败

- **WHEN** 钉钉事件因连接器认证失败、格式错误、缺少 `senderStaffId` 或非身份授权原因被拒绝
- **THEN** 系统 MUST NOT 创建身份发现候选，且不得泄露事件是否对应现有人员

### Requirement: 候选按租户和钉钉用户聚合且幂等

系统 SHALL 以钉钉企业租户和 `senderStaffId` 唯一聚合候选，并 SHALL 以来源渠道事件唯一标识保证候选消息写入幂等。

#### Scenario: 同一用户经多个会话和机器人发消息

- **WHEN** 同一企业租户内同一 `senderStaffId` 通过私聊、群聊或不同机器人发送多条消息
- **THEN** 系统 SHALL 只展示一个候选人，并在其最近消息中保留各消息的会话和机器人来源

#### Scenario: 不同租户使用相同用户 ID

- **WHEN** 两个企业租户出现相同的 `senderStaffId`
- **THEN** 系统 SHALL 创建两个相互隔离的候选人

#### Scenario: 同一渠道事件重复投递

- **WHEN** DingTalk Runtime 重复投递同一个渠道事件
- **THEN** 系统 SHALL 返回相同拒绝语义且不得增加第二条候选消息、第二次观察计数或任何 Agent Job

### Requirement: 管理员查看和筛选未绑定用户

系统 SHALL 在“用户与外部身份”导航组下提供“人员管理”和“未绑定钉钉用户”，并 SHALL 在 `/users/dingtalk-discovery` 统一展示私聊与群聊候选。

#### Scenario: 查看候选列表

- **WHEN** 具备 `identity:manage` 权限的管理员打开未绑定钉钉用户页面
- **THEN** 系统 SHALL 按最近接收时间倒序稳定分页展示最新消息、消息时间、钉钉用户名、用户 ID、群 ID、所属机器人和身份状态

#### Scenario: 筛选会话类型

- **WHEN** 管理员选择全部、私聊、群聊或两者筛选
- **THEN** 系统 SHALL 只返回符合该候选最近保留消息会话构成的候选人

#### Scenario: 搜索候选

- **WHEN** 管理员按钉钉用户名、用户 ID、群 ID或机器人关键字搜索
- **THEN** 系统 SHALL 在当前可见候选范围内返回匹配结果，并保持稳定排序和分页

#### Scenario: 展开最近消息

- **WHEN** 管理员展开一个候选人
- **THEN** 系统 SHALL 展示该候选跨私聊、群聊和机器人的最近安全消息摘要及其来源

### Requirement: 候选消息内容有界且安全

系统 SHALL 为每个候选最多保留最近 20 条发现消息，文本或 Markdown 摘要最多保留 1,000 个 Unicode 字符；附件只允许保存并返回经过白名单校验的类型、名称和大小。

#### Scenario: 文本超过长度上限

- **WHEN** 未绑定用户发送超过 1,000 个字符的文本或 Markdown 消息
- **THEN** 系统 SHALL 截断安全纯文本摘要并返回明确的内容已截断标志

#### Scenario: 收到附件消息

- **WHEN** 未绑定用户发送图片、文件、音频或视频
- **THEN** 系统 SHALL 只展示安全的附件类型、名称和大小，不提供预览、下载或内容提取

#### Scenario: 候选收到超过二十条消息

- **WHEN** 同一候选累计收到超过 20 条幂等的新消息
- **THEN** 系统 SHALL 只保留最近 20 条投影消息，同时保持正确的累计观察次数

#### Scenario: 管理端展示外部可控内容

- **WHEN** 候选昵称、文本或附件名称包含 HTML、Markdown 或脚本字符
- **THEN** 前端 SHALL 仅按纯文本展示，不得执行 HTML、Markdown、脚本或外部链接

### Requirement: 发现接口不得暴露原始事件和敏感材料

系统 MUST 使用专用响应白名单，并 MUST NOT 通过候选接口、页面、日志或审计返回或记录原始渠道事件、`sessionWebhook`、下载凭据、临时 URL、Secret、Token、模型 API Key、完整附件内容或消息正文日志。

#### Scenario: 管理员查询候选详情

- **WHEN** 管理员请求候选详情和最近消息
- **THEN** 响应 SHALL 只包含候选身份、来源、安全摘要和时间等白名单字段

#### Scenario: 候选处理失败

- **WHEN** 投影、查询或绑定操作失败
- **THEN** 日志和审计 SHALL 只记录候选 ID、目标资源、结果、安全错误码和追踪信息，不得记录消息正文或凭据

### Requirement: 消息时间、候选排序和保留期使用安全时间语义

系统 SHALL 优先将有效的钉钉 `createAt` 作为消息展示时间、缺失或无效时使用服务端接收时间，并 SHALL 使用服务端接收时间进行候选排序、活动窗口判断和清理。

#### Scenario: 钉钉消息时间有效

- **WHEN** 事件包含格式有效的钉钉 `createAt`
- **THEN** 页面 SHALL 将其显示为消息时间，同时候选活动窗口仍以服务端接收时间计算

#### Scenario: 钉钉消息时间缺失或异常

- **WHEN** 事件不含有效 `createAt` 或其值不能安全解析
- **THEN** 系统 SHALL 使用服务端接收时间作为展示时间，且不得因外部异常时间戳错误置顶或永久保留候选

### Requirement: 候选保留三十天且不回填历史

系统 SHALL 只观察本功能部署后新进入身份拒绝分支的消息，并 SHALL 仅展示最近一次服务端接收时间在 30 天内的候选；过期清理只能删除发现投影。

#### Scenario: 功能首次部署

- **WHEN** 数据库中已经存在部署前的钉钉渠道事件
- **THEN** 系统 MUST NOT 扫描这些事件或据此创建候选

#### Scenario: 候选三十天没有新消息

- **WHEN** 候选最近一次服务端接收时间早于 30 天
- **THEN** 列表和徽标 SHALL 立即排除该候选，后台 SHALL 可幂等清理其候选和投影消息

#### Scenario: 清理发现投影

- **WHEN** 后台清理过期候选
- **THEN** 系统 MUST NOT 删除或修改原始渠道事件、审计事件、Agent Job 或投递记录

### Requirement: 候选绑定只使用服务端可信身份

系统 SHALL 允许管理员通过内部候选 ID 将从未绑定候选关联到已启用自然人用户，并 SHALL 在服务端重新读取和校验租户、Connector、`senderStaffId`、候选版本和目标用户版本。

#### Scenario: 绑定到现有自然人用户

- **WHEN** 管理员选择已启用自然人用户并使用当前版本提交候选绑定
- **THEN** 系统 SHALL 使用候选的服务端可信身份创建钉钉绑定，不得接受客户端覆盖租户、Connector 或用户 ID

#### Scenario: 客户端伪造身份字段

- **WHEN** 客户端在 URL、路由状态、表单或请求中提交与候选不同的租户、Connector、`senderStaffId` 或昵称
- **THEN** 系统 SHALL 忽略或拒绝这些字段，且不得将伪造身份绑定到任何用户

#### Scenario: 目标用户不可绑定

- **WHEN** 目标是服务账号、已停用用户、不存在用户或版本已过期
- **THEN** 系统 SHALL 拒绝绑定并返回中文可操作错误，不得修改候选或身份

#### Scenario: 候选来源 Connector 已失效

- **WHEN** 候选最近可信来源 Connector 已停用、删除或与租户不匹配
- **THEN** 系统 SHALL 拒绝绑定并要求刷新或修复渠道配置，不得猜测其它 Connector

### Requirement: 人员管理承接选择、新建和绑定

系统 SHALL 从发现列表只携带内部候选 ID 进入现有人员管理流程，并 SHALL 复用现有人员创建、人员详情和钉钉绑定界面。

#### Scenario: 选择现有人员

- **WHEN** 管理员对待绑定候选点击“去绑定”并选择一个可用自然人用户
- **THEN** 系统 SHALL 打开该用户详情中的钉钉绑定面板，并以只读方式显示服务端加载的候选身份字段

#### Scenario: 新建人员并继续绑定

- **WHEN** 管理员在候选上下文选择“新建人员并继续绑定”
- **THEN** 系统 SHALL 使用钉钉昵称预填显示名称、要求用户名，并保持邮箱和密码可选，创建成功后继续打开绑定面板

#### Scenario: 新建人员后绑定失败

- **WHEN** 人员创建成功但随后的候选绑定因冲突、并发或 Connector 状态失败
- **THEN** 系统 SHALL 保留已创建人员和当前候选上下文、显示中文错误并允许重试，不得秘密删除人员

### Requirement: 历史身份只能由原人员恢复

系统 SHALL 识别与候选相同租户和 `senderStaffId` 的停用或已解绑历史身份，以及其停用所属用户，并 SHALL 禁止将该候选绑定到其它人员。

#### Scenario: 已解绑身份再次发消息

- **WHEN** 一个软解绑的钉钉身份发送新消息
- **THEN** 候选 SHALL 显示原人员和“需恢复”状态，只提供前往原人员详情的操作

#### Scenario: 所属用户或身份已停用

- **WHEN** 候选对应身份或所属用户处于停用状态
- **THEN** 系统 SHALL 显示具体不可用状态，并要求管理员在原人员详情显式恢复适用对象

#### Scenario: 尝试把历史身份绑定给另一人员

- **WHEN** 客户端对存在历史归属的候选提交其它目标用户
- **THEN** 系统 SHALL 返回冲突错误，且不得转移、覆盖或创建重复身份

### Requirement: 绑定或恢复后立即隐藏且不回放消息

系统 SHALL 在每次候选列表、详情和计数查询时核对当前身份与用户状态；身份和所属用户均启用后 SHALL 立即排除候选，并 SHALL 只允许绑定后的新消息进入正常 Agent 流程。

#### Scenario: 候选绑定成功

- **WHEN** 管理员成功绑定候选
- **THEN** 页面 SHALL 返回发现列表、显示中文成功提示并立即刷新列表与徽标，候选 SHALL 不再出现

#### Scenario: 历史身份恢复成功

- **WHEN** 管理员使原用户和对应钉钉身份恢复为可用状态
- **THEN** 下一次候选查询和计数 SHALL 立即排除该候选

#### Scenario: 绑定后发送新消息

- **WHEN** 已完成绑定且启用的用户发送一条新钉钉消息
- **THEN** 系统 SHALL 按现有授权和路由规则处理这条新消息，不得回放候选中任何旧消息

### Requirement: 页面和徽标使用有界轮询

系统 SHALL 在发现页面处于前台时每 15 秒刷新候选，在管理端前台每 30 秒刷新侧边徽标，并 SHALL 提供手动刷新；第一版不得为此新增 WebSocket 或 SSE。

#### Scenario: 发现页面保持前台

- **WHEN** 管理员持续查看发现页面
- **THEN** 页面 SHALL 每 15 秒刷新，并允许管理员随时手动刷新

#### Scenario: 页面进入后台后恢复

- **WHEN** 浏览器页面不可见后重新进入前台
- **THEN** 系统 SHALL 在后台暂停定时请求，并在恢复前台时立即刷新

#### Scenario: 候选数量超过九十九

- **WHEN** 当前可见候选人数超过 99
- **THEN** 侧边菜单徽标 SHALL 显示 `99+`，且计数 SHALL 与列表使用相同的身份状态和 30 天过滤条件

### Requirement: 发现与绑定复用统一管理安全控制

候选列表、详情和计数 SHALL 要求已认证 Session 与 `identity:manage` 权限；绑定 SHALL 额外要求 CSRF、乐观并发和安全审计，且本变更不得新增权限模型。

#### Scenario: 无权限读取候选

- **WHEN** 未认证用户或不具备 `identity:manage` 权限的用户请求候选列表、详情或计数
- **THEN** 系统 SHALL 拒绝请求，且不得通过响应差异泄露候选是否存在

#### Scenario: 缺少 CSRF 的候选绑定

- **WHEN** 浏览器会话发起候选绑定但缺少有效 CSRF 凭据
- **THEN** 系统 SHALL 拒绝请求且不得修改用户、身份或候选

#### Scenario: 审计候选绑定结果

- **WHEN** 管理员的候选绑定成功或失败
- **THEN** 系统 SHALL 审计操作者、候选、目标用户、动作、结果和安全错误码，且不得记录消息正文或敏感材料

### Requirement: 第一版不提供回复和人工处置

系统 SHALL NOT 在未绑定钉钉用户页面提供发送消息、回复、忽略、人工删除或批量处置能力。

#### Scenario: 管理员查看候选操作

- **WHEN** 管理员查看待绑定或需恢复的候选
- **THEN** 页面 SHALL 只提供查看、筛选、刷新、去绑定或前往原人员恢复等身份管理操作


<!-- Reconciled from mcp_new capability: `unified-user-identity` -->

### Requirement: 内部用户是跨入口唯一权限主体
系统 SHALL 为每个自然人或受管服务账号创建稳定的内部用户 ID，并 MUST 让 Web 登录、钉钉入口、Agent job、工具调用、配置操作和审计使用该内部用户 ID 作为权限主体。

#### Scenario: 同一用户从 Web 和钉钉访问
- **WHEN** 一个启用用户使用本地 Web 账号登录，并通过已绑定的钉钉身份发送 Agent 请求
- **THEN** 两个入口解析到同一个内部用户 ID，并使用同一组角色、工具权限和平台数据范围

#### Scenario: 外部身份字段发生变化
- **WHEN** 用户昵称或其它非唯一钉钉展示字段发生变化
- **THEN** 系统仍通过稳定绑定解析同一个内部用户，不复制用户或权限

### Requirement: 钉钉外部身份按 provider tenant 和 subject 唯一绑定
系统 SHALL 使用 `provider + tenant_code + external_subject_id` 唯一标识钉钉外部身份，并 MUST 从受信 connector 配置解析 tenant/corp 边界。系统 MUST NOT 仅凭昵称、姓名、手机号、邮箱或缺少 tenant 的员工号自动绑定用户。

#### Scenario: 管理员绑定钉钉员工
- **WHEN** 管理员为内部用户提交启用的钉钉 tenant、connector 和 `senderStaffId`
- **THEN** 系统创建唯一外部身份绑定并返回不包含敏感 payload 的绑定摘要

#### Scenario: 同一钉钉身份绑定两个用户
- **WHEN** 管理员尝试把同一 provider、tenant 和 `senderStaffId` 绑定到另一个用户
- **THEN** 系统拒绝绑定、保留原关系并记录冲突审计

#### Scenario: 不同企业出现相同员工号
- **WHEN** 两个钉钉 tenant 使用相同 `senderStaffId`
- **THEN** 系统把它们视为两个独立外部身份，不发生跨企业权限共享

### Requirement: 第一版钉钉身份由管理员手工管理
系统 SHALL 在第一版支持管理员创建、查看、启用、禁用和解绑钉钉外部身份，并 MUST NOT 自动为未知钉钉发送者创建内部用户。

#### Scenario: 未绑定用户发送消息
- **WHEN** 钉钉 Stream 收到无法解析到启用内部用户的发送者
- **THEN** 系统安全拒绝请求、记录 identity resolution denial，并且不创建 Agent job

#### Scenario: 管理员禁用外部身份
- **WHEN** 管理员禁用某个钉钉绑定但保持内部用户启用
- **THEN** 该用户仍可通过其它有效身份登录，但该钉钉身份不能创建新 job

### Requirement: 用户和身份状态立即影响新请求
系统 SHALL 对内部用户和外部身份执行 enabled/disabled 状态检查，并 MUST 在用户或身份被禁用后阻止新的认证、Channel 请求和权限使用。

#### Scenario: 用户被禁用
- **WHEN** 管理员禁用一个已有 Web session 和钉钉绑定的用户
- **THEN** 系统使其现有管理 session 失效，并拒绝后续 Web 和钉钉请求

#### Scenario: 用户重新启用
- **WHEN** 管理员重新启用用户但外部身份仍为 disabled
- **THEN** 用户可通过其它启用登录身份访问，但被禁用的钉钉身份仍不可用

### Requirement: 外部身份来源可审计但不替代内部 actor
系统 SHALL 在新 job、session、消息和审计中保存内部用户 ID，并 MAY 保存外部身份记录 ID、provider、tenant 和 connector 作为来源证据。系统 MUST NOT 把完整钉钉 payload 或不必要的个人信息复制到权限策略和审计摘要。

#### Scenario: 钉钉请求被接受
- **WHEN** 已绑定钉钉用户通过 Stream 创建 job
- **THEN** job requester 使用内部用户 ID，审计关联外部身份记录和 connector，并避免保存完整原始身份 payload

### Requirement: 历史原始主体迁移可对账且不错误合并
系统 SHALL 为现有用户型 permission、platform grant 和已知钉钉主体提供 legacy 映射及迁移报告，并 MUST 保留历史 job/session/audit 的可追溯性。无法唯一确定 tenant 或用户归属的主体 MUST 保持未迁移或 legacy 状态。

#### Scenario: 现有主体可唯一匹配
- **WHEN** 现有 user policy 的主体能通过已知 tenant 和 `senderStaffId` 唯一映射到内部用户
- **THEN** 系统迁移该权限到内部主体并在对账报告中记录映射

#### Scenario: 现有主体存在歧义
- **WHEN** 同一原始主体可能属于多个 tenant 或无法确认所属用户
- **THEN** 系统不自动合并，报告人工处理项，并保持历史记录不变


<!-- Reconciled from mcp_new capability: `web-admin-authentication` -->

### Requirement: 管理端支持安全的本地账号登录
系统 SHALL 支持启用用户通过用户名和密码登录管理端，并 MUST 使用经过审计的强密码哈希算法保存密码验证材料。系统 MUST NOT 保存或返回明文密码。

#### Scenario: 正确凭证登录
- **WHEN** 启用用户提交正确用户名和密码
- **THEN** 系统创建服务端 session、记录登录成功审计并返回不含密码材料的当前用户信息

#### Scenario: 错误凭证登录
- **WHEN** 用户提交错误密码、未知用户名或已禁用账号
- **THEN** 系统返回一致的安全失败响应、记录受限审计，并不泄漏账号是否存在

### Requirement: Web 使用可撤销的服务端 session
系统 SHALL 生成高熵随机 session token，只在安全 cookie 中返回明文 token，并 MUST 只在数据库保存 token hash、用户、创建时间、最后使用时间、过期时间和撤销状态。

#### Scenario: 有效 session 访问管理 API
- **WHEN** 浏览器携带未过期且未撤销的 session cookie
- **THEN** authentication middleware 解析内部用户 principal 并把它传给管理 API

#### Scenario: 用户退出
- **WHEN** 用户调用退出接口
- **THEN** 系统撤销当前 session、清除 cookie，并拒绝后续使用原 token

#### Scenario: 用户被禁用
- **WHEN** 管理员禁用一个拥有多个活动 session 的用户
- **THEN** 系统撤销或立即拒绝该用户的所有 session

### Requirement: 管理端请求具备 CSRF 和 cookie 安全保护
系统 SHALL 对基于 cookie 的状态修改请求执行 SameSite、Origin 和 CSRF 防护，并 MUST 在生产环境使用 Secure、HttpOnly cookie。

#### Scenario: 合法 Web 表单提交
- **WHEN** 已认证页面携带有效 CSRF token 和允许的 Origin 提交修改
- **THEN** 系统继续执行权限和业务校验

#### Scenario: 跨站请求缺少 CSRF 证明
- **WHEN** 状态修改请求来自不允许的 Origin 或缺少有效 CSRF token
- **THEN** 系统拒绝请求且不执行配置修改

### Requirement: 管理 API actor 来自可信认证上下文
系统 SHALL 从 authentication middleware 注入的内部 principal 获取 actor，生产模式 MUST NOT 信任客户端直接提交的 `x-admin-user-id` 或 `x-agent-user-id`。

#### Scenario: 客户端伪造管理员请求头
- **WHEN** 未认证请求仅携带 `x-admin-user-id`
- **THEN** 生产管理 API 返回未认证错误且不执行操作

#### Scenario: 测试适配器注入 principal
- **WHEN** 测试环境显式启用 test-only identity adapter
- **THEN** 测试可以注入内部 principal，但该能力不能在生产配置中默认启用

### Requirement: 首个管理员通过显式 bootstrap 创建
系统 SHALL 提供在 schema migration 成功后执行的显式、幂等初始管理员 bootstrap；当数据库尚无有效平台管理员时，该操作 SHALL 创建唯一启用的人类用户 `admin`、显示名称 `Administrator`、受保护的 `platform-admin` 角色和启用的成员关系，并写入不含凭据的审计记录。系统 MUST 只保存符合现有密码策略的 Argon2 密码哈希，不得记录、返回或持久化明文密码，并 MUST NOT 在非 local/test 环境的 migration、seed 或 bootstrap 中使用已知默认密码。

#### Scenario: Local 空库创建首个管理员
- **WHEN** schema migration 已成功、`APP_ENV` 为 local 或 test、数据库尚无管理员且 bootstrap 未提供外部密码文件
- **THEN** 系统创建 `admin`、`platform-admin` 角色和启用成员关系，并使密码 `111111111111` 可用于本地首次登录
- **THEN** 数据库、日志、审计和命令输出均不包含该明文

#### Scenario: 重复执行 bootstrap
- **WHEN** 初始管理员、平台管理员角色或成员关系已经存在
- **THEN** bootstrap 幂等完成且不创建重复用户、重复角色或重复成员关系
- **THEN** 系统不重置任何现有密码、状态或 revision

#### Scenario: 存在其他管理员
- **WHEN** 数据库已有至少一个有效平台管理员但不存在固定 ID 的本地管理员 fixture
- **THEN** bootstrap 保留现有管理员事实并安全退出，不额外创建默认管理员

#### Scenario: Production 空库提供安全密码输入
- **WHEN** staging、production 或其他非 local/test 空库通过权限受限文件、容器 Secret 或交互式安全输入提供合规初始密码
- **THEN** 系统创建初始管理员、立即丢弃明文输入并只保存 Argon2 哈希

#### Scenario: Production 空库没有安全密码输入
- **WHEN** 非 local/test 数据库没有管理员且 bootstrap 未获得受支持的安全密码输入
- **THEN** 初始化非零退出并阻止业务服务启动，错误不包含密码或其他 Secret
- **THEN** 系统不得回退到 `111111111111`、命令行明文参数、普通环境变量或仓库内明文


<!-- Reconciled from mcp_new capability: `web-admin-console` -->

### Requirement: 管理端提供认证后的基础页面
系统 SHALL 提供登录页和认证后的管理端外壳，并 MUST 对未认证用户隐藏管理数据和操作。

#### Scenario: 未登录访问管理页面
- **WHEN** 浏览器没有有效管理 session 访问用户或 Agent 页面
- **THEN** 前端跳转登录页，后台 API 返回未认证响应

#### Scenario: 已登录管理员进入控制台
- **WHEN** 拥有相应权限的用户登录
- **THEN** 前端根据权限展示可访问导航并加载当前用户安全摘要

### Requirement: 第一版 Web 管理用户角色和钉钉绑定
系统 SHALL 提供用户列表/详情、用户启停、角色列表/详情、用户角色分配和钉钉身份绑定管理页面，并 MUST 在操作前显示目标和影响范围。

#### Scenario: 管理员绑定钉钉身份
- **WHEN** 管理员在用户详情页选择 tenant/connector 并提交 `senderStaffId`
- **THEN** 页面调用绑定 API、显示成功摘要并刷新该用户身份列表

#### Scenario: 绑定发生冲突
- **WHEN** 目标钉钉身份已绑定其他用户
- **THEN** 页面显示明确冲突，不覆盖原绑定

### Requirement: 第一版 UI 只开放默认诊断 Agent
系统 SHALL 使用多 Agent API 和数据模型，但第一版 Web MUST 只展示 `default-diagnostic-agent`，并 MUST 不提供创建、删除或切换到其它 Agent 的入口。

#### Scenario: 管理员打开 Agent 配置
- **WHEN** 管理员进入 Agent 管理页面
- **THEN** 页面直接展示默认诊断 Agent 的草稿、当前 publication 和发布历史

#### Scenario: 数据库存在其它 Agent
- **WHEN** 后端数据中存在其它 Agent 定义
- **THEN** 第一版 UI 不列出或允许管理这些 Agent，但 API 权限和 repository 仍保持多 Agent 隔离

### Requirement: 默认 Agent 页面支持草稿校验发布和回滚
系统 SHALL 提供默认 Agent 的基础信息、业务指令、模型/限制、已有只读工具、Skill、Channel/Delivery、有效配置预览、校验、发布和回滚界面。

#### Scenario: 草稿校验失败
- **WHEN** 管理员提交包含无效工具或缺失 connector 的草稿
- **THEN** 页面显示字段级错误且不允许发布

#### Scenario: 发布成功
- **WHEN** 有发布权限的管理员发布合法草稿
- **THEN** 页面显示新 revision、config hash、发布人和发布时间

### Requirement: Web 不展示敏感认证和密钥材料
系统 SHALL 确保管理页面和浏览器 API 响应不包含密码 hash、session token/hash、secret value/ciphertext、完整敏感外部 payload 或钉钉凭证。

#### Scenario: 查看用户与 Agent 配置
- **WHEN** 管理员查看用户、外部身份或 Agent 模型配置
- **THEN** 页面只显示必要状态、引用和脱敏摘要

### Requirement: Web 写操作处理 revision 冲突
系统 SHALL 在用户、角色、身份绑定和 Agent 草稿写操作中携带 expected revision 或等价并发控制，并 MUST 在版本冲突时要求刷新而不是静默覆盖。

#### Scenario: 两个管理员同时编辑草稿
- **WHEN** 后提交者使用已经过期的 expected revision 保存
- **THEN** API 返回冲突，页面展示当前版本已变化并允许刷新比较
