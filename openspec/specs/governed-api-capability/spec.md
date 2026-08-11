# governed-api-capability Specification

## Purpose
定义外部 API Connection、认证配置、个人凭据、Capability、Handler、Release 及 ONES 能力的治理契约。

## Requirements

<!-- Migrated from canonical source capability: `external-api-connection-authentication` -->

### Requirement: API Connection 使用 Draft Verify Publish 生命周期
API Connection MUST 具有稳定身份、可编辑 Draft、验证证据和不可变 Published Revision，正常发布路径为 `DRAFT → VERIFIED → PUBLISHED`；Draft 内容改变 MUST 使原验证证据失效。

#### Scenario: 发布已验证 Connection
- **WHEN** 授权管理员发布 Revision 与内容 hash 均匹配的 VERIFIED Draft
- **THEN** 系统创建不可变 Connection Revision并记录发布者、时间和安全验证摘要

#### Scenario: 发布未验证 Connection
- **WHEN** Draft 未验证或验证后 Origin/Authentication Profile 已变化
- **THEN** 系统拒绝发布且不创建部分 Revision

#### Scenario: 修改 Published Connection
- **WHEN** 管理员尝试原地修改已发布 Origin 或认证配置
- **THEN** 系统拒绝并要求复制为新 Draft

### Requirement: Connection 固定请求 Origin
Connection Revision MUST 固定 scheme、host 和 port；Handler 只能引用该 Connection 并配置相对路径。系统 MUST 拒绝用户信息、动态 host、完整请求 URL 和跨 Origin 认证材料传递。

#### Scenario: 组合合法相对路径
- **WHEN** 已发布 Connection Origin 为受信任 ONES 地址且 Handler 使用合法相对路径
- **THEN** 执行器只向规范化后的同一 Origin 发起请求

#### Scenario: Handler 提交完整 URL
- **WHEN** Handler 路径包含 scheme、host、userinfo 或网络位置
- **THEN** 系统拒绝保存、验证和执行

#### Scenario: 外部服务返回跨 Origin 重定向
- **WHEN** 请求响应要求跳转到不同 scheme、host 或 port
- **THEN** 执行器不得携带认证材料跟随重定向，并将调用归类为非重试安全失败

### Requirement: Connection 明文 HTTP 必须显式授权
外部 API Connection SHALL 默认使用 HTTPS；管理员 MAY 在企业内网、开发、测试或生产 Connection Draft 中显式启用 `allow_plain_http` 以使用 HTTP。系统 MUST 拒绝未显式授权的 HTTP Origin，MUST 将授权纳入内容 hash 和不可变 Connection Revision，并 MUST 在管理界面说明密码、Token 和业务数据可能被窃听或篡改。该授权 MUST NOT 被描述为网络区限制或完整 SSRF 防护。

#### Scenario: 企业内网显式配置 HTTP ONES
- **WHEN** 管理员配置固定 HTTP Origin、显式启用明文 HTTP 并完成验证
- **THEN** 系统允许在生产环境发布和调用该精确 Origin，并保留明文传输警告和不可变授权事实

#### Scenario: HTTP 未显式授权
- **WHEN** 任一环境的 Connection 使用 HTTP 但未启用 `allow_plain_http`
- **THEN** 系统拒绝保存、验证和发布，且不发起登录或业务调用

#### Scenario: HTTPS Connection
- **WHEN** Connection 使用 HTTPS
- **THEN** 系统允许按固定 Origin 规则处理，并将无意义的明文 HTTP 授权规范化为 false

### Requirement: Authentication Profile 固定登录与认证协议
Authentication Profile Revision MUST 定义固定登录相对路径、登录请求字段、Token/User/Team 提取规则和认证 Header 注入规则；系统 MUST 静态校验提取类型并 MUST NOT 将登录动作暴露为 Capability 或模型 Tool。

#### Scenario: 验证合法 ONES 登录协议
- **WHEN** 登录响应包含匹配规则的 User、Team 集合与 Token
- **THEN** 系统返回内部验证结果供绑定或 Connection Verify 使用，不向模型注册登录 Tool

#### Scenario: 登录响应结构不符
- **WHEN** User ID、Team 集合或 Token 缺失或类型错误
- **THEN** 系统判定验证失败，不创建身份、凭据或发布证据

### Requirement: 首个 Connection 可临时使用当前管理员自验证
当系统尚无可供正式绑定的 Published ONES Connection Revision 时，具备 `api_connections.verify` 的当前管理员 SHALL 能在 Connection Verify 请求内临时输入自己的邮箱密码，验证 Draft Origin、登录、字段提取和认证注入；密码和 Token MUST 在请求完成后丢弃，不得创建身份、凭据或运行时回退账号。

#### Scenario: 首连接启动验证成功
- **WHEN** 当前管理员提交有效个人邮箱密码且 Draft 全链验证通过
- **THEN** 系统只保存验证证据与安全摘要，并允许后续发布该 Connection Revision

#### Scenario: 启动验证后直接测试 Capability
- **WHEN** Connection 已发布但管理员尚未通过该 Revision 完成正式自助绑定
- **THEN** 系统拒绝 Capability Test/Verify，并提示完成本人绑定

#### Scenario: 启动验证失败
- **WHEN** 登录、提取或认证注入测试失败
- **THEN** 系统返回安全错误，且数据库、缓存、日志和审计均不保存密码、Token 或原始响应

### Requirement: Connection 失效时运行时失败关闭
Published Connection Revision SHALL 支持禁用和归档；被禁用、无法解析或完整性校验失败的 Connection MUST 阻止依赖它的新外部调用，且不得回退到其他 Origin 或浮动 Revision。

#### Scenario: 禁用当前 Connection Revision
- **WHEN** 某 Capability Release 冻结的 Connection Revision 被禁用
- **THEN** 新调用返回安全配置错误，不尝试其他 Connection

#### Scenario: 新 Connection Revision 已发布
- **WHEN** Connection 发布新 Revision 但既有 Capability Release 未重新发布
- **THEN** 既有 Release 继续冻结旧 Revision，不自动漂移到新版本

### Requirement: 网络调用边界不得被描述为完整 SSRF 防护
系统 MUST 实施固定 Origin、相对路径、HTTP 显式授权、拒绝跨 Origin 重定向、超时和响应大小限制；在完整网络区/CIDR/DNS 出站治理交付前，管理状态和文档 MUST NOT 宣称具备通用 SSRF 防护。

#### Scenario: 管理员查看 Connection 安全状态
- **WHEN** Connection 只具备第一版 Origin 边界
- **THEN** 界面准确显示已实施约束和未覆盖的网络区治理，不显示“完整 SSRF 防护”


<!-- Migrated from canonical source capability: `external-api-credential-binding` -->

### Requirement: 外部身份与个人 API 凭据分离持久化
系统 MUST 将 ONES External Identity 用于证明外部主体，将 External API Credential 用于保存加密个人 Token；明文密码 MUST NOT 持久化，个人 Token MUST NOT 保存到共享平台 Secret、身份展示字段、日志、审计或 API 响应。

#### Scenario: 用户完成 ONES 绑定
- **WHEN** 两阶段验证成功并选择默认 Team
- **THEN** 系统分别保存外部 User ID/Team 元数据和加密 Token，并关联同一内部用户与 Published Connection Revision

#### Scenario: 管理员查看用户绑定
- **WHEN** 管理员读取他人的 ONES 外部身份
- **THEN** API 只返回 User ID、默认 Team、凭据状态和验证时间，不返回 Token、密码或可逆密文

### Requirement: ONES 自助验证分为 Challenge 两阶段
ONES 自助绑定第一阶段 MUST 从认证会话确定当前内部用户，使用邮箱密码调用精确 Connection/Authentication Profile Revision，并创建与当前用户和 Connection Revision 绑定的短时单次 Verification Challenge；响应只能包含 Challenge ID 和安全 User/Team 候选，MUST NOT 包含 Token。

#### Scenario: 第一阶段验证成功
- **WHEN** 当前用户提交有效邮箱密码
- **THEN** 系统丢弃密码，创建包含加密临时 Token、候选摘要、过期时间和未消费状态的 Challenge，并向浏览器返回安全候选

#### Scenario: 客户端提交目标用户
- **WHEN** 自助接口请求包含其他 `user_id`
- **THEN** 系统拒绝或忽略该字段并只使用认证会话中的当前用户

#### Scenario: 第一阶段验证失败
- **WHEN** ONES 拒绝凭据或响应不符合 Authentication Profile
- **THEN** 系统不创建 Challenge、身份或凭据，并返回不泄露账号存在性和认证材料的安全错误

### Requirement: Challenge 确认原子保存默认 Team 和凭据
第二阶段 MUST 校验 Challenge 属于当前用户、精确 Connection Revision、未过期且未消费，并只允许选择 Challenge 候选中的 Team；成功后 MUST 在一个事务中保存外部 User ID、最新验证 Team 集合、default Team、加密 Token 和验证时间，并将 Challenge 标记为已消费。

#### Scenario: 用户选择合法默认 Team
- **WHEN** 当前用户提交有效 Challenge 和候选中的 Team ID
- **THEN** 系统原子更新身份与凭据，且后续重复消费同一 Challenge 被拒绝

#### Scenario: 用户选择候选外 Team
- **WHEN** 提交的 Team ID 不在 Challenge 的已验证候选集合中
- **THEN** 系统拒绝确认，不改变现有身份或凭据

#### Scenario: Challenge 已过期
- **WHEN** 用户提交过期或已消费的 Challenge
- **THEN** 系统失败关闭并要求重新验证，不使用其中 Token

### Requirement: 切换默认 Team 必须重新验证
用户切换 ONES default Team MUST 重新提交邮箱密码并创建新 Challenge，以 ONES 当前返回的 Team 集合为准；系统 MUST NOT 允许直接从历史 Team 集合切换。

#### Scenario: 最新 Team 集合包含目标 Team
- **WHEN** 用户重新验证并选择新响应中的 Team
- **THEN** 系统原子刷新 User、Team 集合、default Team 和 Token

#### Scenario: 历史 Team 已被撤销
- **WHEN** 旧绑定包含某 Team 但新登录响应不再包含它
- **THEN** 系统不得允许选择该 Team，并从最新验证集合中移除

### Requirement: 第一版每个用户只有一个有效 ONES 账号
第一版 MUST 只支持一个逻辑 ONES Connection，且每个内部用户最多一个当前有效 ONES External Identity、一个 default Team 和一个有效个人 Token；界面和 API MUST NOT 提供实例或账号选择器。

#### Scenario: 用户重复绑定同一 ONES 主体
- **WHEN** 用户再次验证同一外部 User ID
- **THEN** 系统幂等更新允许更新的 Team、默认 Team、Token 和验证时间，不创建第二个有效账号

#### Scenario: 用户尝试绑定不同 ONES 主体
- **WHEN** 当前用户已有有效主体却确认另一个 User ID
- **THEN** 系统按显式换绑流程原子替换并使旧主体不再有效，不得同时保留两个有效账号

#### Scenario: 外部主体已属于其他内部用户
- **WHEN** 经验证 ONES User ID 已绑定给另一个启用内部用户
- **THEN** 系统返回冲突，不自动迁移或共享凭据

### Requirement: 本人和管理员复用外部身份面板
现有 `ExternalIdentityPanel` SHALL 支持本人模式与管理员治理模式；模式 MUST 按入口及其授权边界判定，不得按当前认证主体与目标用户是否相同自动切换。“我的外部身份”必须使用本人模式；受治理授权保护的“人员管理 → 用户详情”必须使用治理模式，即使管理员查看自己的人员记录。本人模式允许绑定、重新验证、切换 default Team 和解绑本人 ONES，且只读展示本人当前钉钉身份；治理模式保留钉钉可信绑定、启停、解绑和候选恢复，但不得直接修改已绑定身份的租户或外部主体，不得显示 ONES 邮箱密码表单或代替用户重新验证。

#### Scenario: 普通用户访问我的外部身份
- **WHEN** 已认证普通用户打开“我的外部身份”
- **THEN** 系统复用本人模式面板，且该用户不能访问人员列表、角色、会话或其他用户详情

#### Scenario: 管理员查看其他用户
- **WHEN** 管理员打开他人的用户详情外部身份区域
- **THEN** 面板进入治理模式，只显示允许元数据和禁用/解绑操作

#### Scenario: 管理员查看本人
- **WHEN** 管理员在用户详情查看自己的记录
- **THEN** 面板进入治理模式并提供获授权的钉钉治理动作，不得请求本人自助接口

#### Scenario: 两个入口查看同一绑定事实
- **WHEN** 管理员分别打开“我的外部身份”和人员管理中的本人记录
- **THEN** 两个入口读取同一服务端绑定事实，但前者应用本人边界、后者应用治理边界，不得形成独立身份或凭据状态

#### Scenario: 本人查看钉钉身份
- **WHEN** 当前用户在本人模式存在当前钉钉身份
- **THEN** 系统只读展示状态、租户和最近使用信息，且不提供本人绑定、启停或解绑钉钉身份的操作

#### Scenario: 管理员治理当前钉钉身份
- **WHEN** 管理员在人员详情查看当前钉钉身份
- **THEN** 系统提供启停和软解绑动作，但租户、外部主体及连接器来源事实保持只读

### Requirement: 当前身份与历史记录明确分层
本人模式 MUST 只返回当前绑定且不得展示 `unbound` 历史；治理模式 MUST 在主区域只展示 `enabled` 或 `disabled` 的当前身份，并将 `unbound` 记录保留在默认折叠的只读历史区域。历史记录不得伪装成第二个当前绑定。

#### Scenario: 用户存在旧 ONES 历史和当前 ONES 绑定
- **WHEN** 同一用户同时具有 `unbound` ONES 历史记录与当前 ONES 身份
- **THEN** 本人模式只展示当前身份，治理模式只在折叠历史区域展示旧记录

#### Scenario: 管理员查看历史身份
- **WHEN** 管理员展开用户的外部身份历史记录
- **THEN** 系统只读展示 `unbound` 事实，不提供普通启停或再次解绑操作

#### Scenario: 钉钉候选要求恢复历史身份
- **WHEN** 受信钉钉候选解析为 `restore_required`
- **THEN** 治理模式定位并展开匹配的历史钉钉身份，只允许通过既有候选恢复流程恢复

### Requirement: ONES 身份与个人凭据精确关联
本人 ONES 状态 MUST 根据个人凭据的 `external_identity_id` 返回对应身份，或使用等价的单次关联查询；系统 MUST NOT 分别选择第一条 ONES 身份和最新凭据后拼接响应。

#### Scenario: 历史 ONES 身份排序在当前身份之前
- **WHEN** 用户的 `unbound` 历史 ONES 身份按租户或主体排序早于当前身份
- **THEN** 本人状态仍返回当前凭据精确关联的身份、Team 和默认 Team，不得混入历史元数据

#### Scenario: 最新凭据没有可关联的当前身份
- **WHEN** 最新凭据引用的身份不存在或已成为 `unbound`
- **THEN** 系统不得返回由其他身份拼成的正常状态，并以安全的不一致状态失败关闭

### Requirement: 个人凭据操作使用本人权限和受限管理员权限
系统 MUST 使用 `external_credentials.self_manage` 授权本人绑定、重新验证、切换 Team 和解绑；管理员对他人的操作只允许 `external_credentials.read/disable/unbind`，不得读取或轮换 Token。

#### Scenario: 普通用户管理本人凭据
- **WHEN** 当前用户具备 self_manage 并调用本人接口
- **THEN** 系统允许受控操作并记录不含邮箱密码和 Token 的审计

#### Scenario: 管理员尝试代用户重新验证
- **WHEN** 管理员在他人上下文提交邮箱密码或凭据轮换请求
- **THEN** 系统拒绝操作且不访问 ONES 登录端点

### Requirement: 解绑和凭据错误具有明确状态
解绑 MUST 软删除身份并禁用关联个人凭据；外部 API 返回 401 时系统 MUST 将当前凭据标记为 invalid，403 MUST 保留凭据有效状态；任何状态变更 MUST 保留审计且不得删除历史事实。

#### Scenario: 用户解绑 ONES
- **WHEN** 本人确认解绑
- **THEN** 系统原子停用身份与凭据，后续 Tool 暴露和执行均失败关闭

#### Scenario: 外部 API 返回 401
- **WHEN** 使用当前凭据的调用收到 401
- **THEN** 系统标记该凭据 invalid，不重试，并提示用户重新验证

#### Scenario: 外部 API 返回 403
- **WHEN** 调用收到 403
- **THEN** 系统不重试但保留凭据状态，并返回权限不足的安全结果

### Requirement: 现有 ONES 身份记录非破坏迁移
已有只有身份元数据而没有个人 Token 的 ONES 记录 MUST 保留，并 SHALL 显示“需要凭据验证”；迁移 MUST NOT 伪造 Token、自动共享服务账号或强制删除后重新绑定。

#### Scenario: 旧用户打开外部身份面板
- **WHEN** 用户存在历史 ONES User ID 和 Team 元数据但没有 External API Credential
- **THEN** 面板保留身份信息并提示完成重新验证，运行时不暴露依赖 ONES 凭据的 Capability


<!-- Migrated from canonical source capability: `governed-api-capability-control-plane` -->

### Requirement: 受治理 API Capability 使用专用稳定标识
系统 MUST 使用同一个 Capability Identifier 作为业务标识、模型 Tool 名、Agent/Application 引用和审计标识，并 MUST 以专用校验器校验 `cap__<provider>__<domain>__<operation>` 格式、小写 snake_case 层级、双下划线分隔、全局唯一和不超过 128 字符。

#### Scenario: 创建合法 Capability
- **WHEN** 管理员创建 Identifier 为 `cap__ones__work_item__search` 的 Capability
- **THEN** 系统接受该标识并在所有发布和运行时引用中保持原值

#### Scenario: 内部 Tool 占用保留前缀
- **WHEN** 内部代码注册表 Tool 或非受治理能力尝试使用 `cap__` 前缀
- **THEN** 系统拒绝注册并报告命名空间冲突

#### Scenario: 复用通用业务编码校验器
- **WHEN** 通用业务编码规则会因连续下划线拒绝一个合法 Capability Identifier
- **THEN** 系统 MUST 使用 Capability 专用校验规则而不得转换或改写 Identifier

### Requirement: 统一工作台保持领域对象分离
管理端 MUST 提供一个“API Capability 配置”工作台，包含 Capability 定义、Agent 输入字段、Agent 输出字段、Handler Mapping 和测试预览五个区域，并 SHALL 通过一个 Draft 聚合协调保存；系统内部 MUST 分别持久化 Capability、Handler、API Connection、Authentication Profile 和 Mapping Plan 的身份与版本。

#### Scenario: 管理员编辑完整配置
- **WHEN** 管理员在同一工作台修改公开 Schema、HTTP 配置和字段映射并保存
- **THEN** 系统原子保存一个新的 Draft Revision，并返回五个区域一致的 Draft 快照

#### Scenario: 读取已发布配置
- **WHEN** 管理员从历史 Release 打开详情
- **THEN** 界面展示被冻结的各对象 Revision，并只允许复制为新 Draft而不允许原地修改

### Requirement: Capability 公开契约具有严格 Schema
Capability Revision MUST 定义业务名称、模型可见 `description`、`operation_semantics`、数据分级以及严格的 Input/Output Schema；Input Schema SHALL 支持字段名称、类型、说明、必填性、枚举、固定默认值和字符串、数值、对象、数组边界，并 MUST 拒绝未知字段和越界输入。

#### Scenario: 保存合法查询契约
- **WHEN** 管理员配置 QUERY Capability，并为输入输出定义完整类型与边界
- **THEN** 系统保存规范化 Schema，并使用业务 `description` 生成模型 Tool 描述

#### Scenario: Schema 包含系统拥有字段
- **WHEN** 管理员把 Token、外部 User ID 或 default Team ID 配置为 Agent 可写输入
- **THEN** 系统拒绝保存并指出该字段只能来自 System Context 或 Credential Resolver

#### Scenario: 发布说明进入模型描述
- **WHEN** Release 配置了可选 `release_note`
- **THEN** 管理端可以展示该说明，但 Tool 定义和模型上下文 MUST NOT 包含它

### Requirement: Handler 只能使用固定声明式执行器
Handler Draft MUST 引用平台代码内置的 `http-json-v1` 执行器，并 MAY 配置受支持 HTTP method、相对路径、固定只读 GraphQL document 和声明式 Mapping；系统 MUST 拒绝 Python、JavaScript、SQL、Shell、模板、函数、完整 URL、动态 host 或任意可执行内容。

#### Scenario: 保存声明式 HTTP Handler
- **WHEN** 管理员配置固定 Connection、POST 相对路径、固定 GraphQL query 和受限 Mapping
- **THEN** 系统接受 Draft，且数据库只保存声明式配置和固定执行器 ID

#### Scenario: 提交任意实现代码
- **WHEN** Handler 配置包含脚本、函数、SQL 或可执行模板
- **THEN** 系统拒绝 Draft 且不得保存或执行该内容

### Requirement: Mapping Plan 只允许确定性投影
Mapping Draft SHALL 只允许字段重命名、对象层级调整、Agent Input/System Context/固定常量取值、受限响应路径读取、数组逐项投影、固定默认值以及 `string`、`integer`、`number`、`boolean` 显式转换；系统 MUST 拒绝条件、过滤、拼接、日期计算、正则、函数、脚本和部分成功语义。

#### Scenario: 编译合法 Mapping
- **WHEN** Mapping 只包含白名单节点且输入输出路径与 Schema 一致
- **THEN** 系统在发布前编译并静态校验带 schema version 和内容 hash 的不可变计划

#### Scenario: Mapping 使用过滤表达式
- **WHEN** 管理员配置数组过滤、条件分支或字符串拼接
- **THEN** 系统拒绝验证和发布，并返回不含业务数据的字段级错误

#### Scenario: 必填字段无法映射
- **WHEN** 静态分析发现必填请求或输出字段没有合法来源
- **THEN** 系统拒绝验证，不得依赖运行时部分成功补偿

### Requirement: Draft 写入使用乐观并发控制
所有 Capability Draft 保存 MUST 携带 `expected_revision`；当预期版本与当前版本不一致时，系统 MUST 拒绝覆盖并返回当前非敏感 Revision 摘要。

#### Scenario: 保存当前 Draft
- **WHEN** 管理员提交与当前值一致的 `expected_revision`
- **THEN** 系统原子创建下一 Draft Revision 并使旧验证证据失效

#### Scenario: 两名管理员并发保存
- **WHEN** 后提交者使用已经过期的 `expected_revision`
- **THEN** 系统返回冲突，不覆盖先提交者的修改

### Requirement: Capability 测试和验证使用当前管理员自己的绑定
Capability Test/Verify MUST 使用当前授权管理员正式绑定的外部 User ID、默认 Team 和个人 Token执行 Draft，不得使用共享 Verification Credential、服务账号或其他用户凭据；Verify 证据 MUST 绑定 Draft Revision 和规范化内容 hash。

#### Scenario: 管理员具备有效个人绑定
- **WHEN** 具备 `api_capabilities.test` 或 `api_capabilities.verify` 权限的管理员执行测试或验证
- **THEN** 系统使用该管理员自己的绑定和凭据，并记录验证人、Team、时间、结果摘要与内容 hash

#### Scenario: 管理员尚未正式绑定
- **WHEN** 管理员只有已发布 Connection 但没有有效个人外部凭据
- **THEN** 系统阻止 Capability 测试和验证，并提示先完成本人外部身份绑定

#### Scenario: 验证后修改配置
- **WHEN** Capability Schema、Handler、Connection 或 Mapping 的规范化内容发生变化
- **THEN** 旧验证证据立即失效，Publish 必须拒绝使用该证据

### Requirement: 测试预览排除认证材料和原始响应
Capability Test SHALL 展示 Method、相对路径、Query、映射后的普通业务请求体和通过 Output Schema 的规范化输出；密码、Token、Cookie 和认证 Header MUST 在预览结构构建前排除，原始外部响应 MUST NOT 返回、保存或记录。

#### Scenario: 测试包含普通业务字段
- **WHEN** 测试请求使用关键词、工作项类型、外部 User ID 和 default Team
- **THEN** 预览完整展示允许的普通业务字段而不做无意义掩码

#### Scenario: 认证 Header 已注入真实请求
- **WHEN** 执行器为外部请求注入当前管理员 Token
- **THEN** 预览、API 响应、日志和审计的数据结构均不包含该 Header 或 Token

### Requirement: Publish 原子、幂等且创建不可变版本
Publish MUST 接收已验证 Draft Revision、内容 hash 和 idempotency key，并在单一事务中创建或复用 Capability Revision、创建 Handler Revision、编译 Mapping Plan、冻结精确 Connection/Authentication Profile Revision 并创建单调递增 Capability Release；任一步失败 MUST 整体回滚。

#### Scenario: 首次发布已验证 Draft
- **WHEN** Revision、hash、证据和依赖均有效
- **THEN** 系统创建初始 `ACTIVE` Release，保存不可变快照、发布审计和唯一幂等记录

#### Scenario: 重复提交同一幂等键
- **WHEN** 客户端因超时再次提交相同 Publish 请求和 idempotency key
- **THEN** 系统返回第一次创建的同一 Release，不新增 Revision 或 Release

#### Scenario: 发布事务中编译失败
- **WHEN** Mapping 编译或任一依赖冻结失败
- **THEN** 系统回滚全部创建，不留下部分 Release 或孤立 Revision

### Requirement: Capability 与 Handler 按变更类型独立版本化
系统 MUST 在只改变路径、固定 Query 或 Mapping 时复用原 Capability Revision并创建新 Handler Revision；公开 Input/Output Schema 改变时 MUST 在同一 Identifier 下创建新 Capability Revision；业务含义改变时 MUST 使用新 Identifier。

#### Scenario: 只修正响应字段映射
- **WHEN** 管理员复制旧 Release 并仅修改 Handler Mapping
- **THEN** 新 Release 引用原 Capability Revision和新 Handler Revision

#### Scenario: 修改公开输出结构
- **WHEN** 管理员改变模型可见 Output Schema
- **THEN** 新 Release 使用新的 Capability Revision，旧 Release 与既有应用快照保持不变

### Requirement: Release 内容不可变但支持受控运维状态
发布后的配置内容 MUST 不可变；Release SHALL 支持 `ACTIVE`、`DEPRECATED`、`DISABLED`、`ARCHIVED` 状态，并允许保存废弃原因与兼容的 `replacement_release_id`，但状态变化 MUST NOT 修改任何冻结 Revision。

#### Scenario: 软废弃 Release
- **WHEN** 管理员把 Release 标记为 `DEPRECATED`
- **THEN** 既有应用仍可执行，但新 Agent、应用绑定和升级选择不能再选择它

#### Scenario: 紧急禁用 Release
- **WHEN** 管理员把 Release 标记为 `DISABLED`
- **THEN** 所有后续新调用失败关闭，历史发布、用户绑定和凭据保持不变

#### Scenario: 归档仍被活动应用依赖的 Release
- **WHEN** 管理员尝试归档仍有活动 Application Publication 引用的 Release
- **THEN** 系统拒绝归档并返回安全的依赖摘要

### Requirement: 管理操作使用细粒度 RBAC 和安全审计
系统 MUST 分别执行 `api_connections.read/manage/verify/publish`、`api_capabilities.read/manage/test/verify/publish` 权限，并 SHALL 继续复用既有 Agent/Application 编辑与发布权限；本阶段 MUST NOT 要求双人审批。

#### Scenario: 无发布权限的管理员发布 Capability
- **WHEN** 操作者具备读取和测试权限但缺少 `api_capabilities.publish`
- **THEN** 系统拒绝发布，不创建 Release，并记录不含配置正文和凭据的拒绝审计

#### Scenario: 授权管理员完成发布
- **WHEN** 操作者具备所需操作权限且发布校验通过
- **THEN** 系统记录 actor、对象、Revision、hash、动作、结果和 correlation id，不记录原始响应或认证材料


<!-- Migrated from canonical source capability: `governed-api-capability-runtime` -->

### Requirement: 运行时 Tool Catalog 只暴露完整治理交集
模型可见受治理 API Tool MUST 同时属于当前 Agent Capability Envelope 和 Application Capability Allowlist，引用可运行 Release，且当前用户具备该 Provider 所需启用身份、default Team 和有效个人凭据；缺少任一条件时 MUST 不暴露。

#### Scenario: 用户与发布链均就绪
- **WHEN** 当前 Job 冻结的 Agent/Application Publication 允许某 Release，Release 可运行，用户 ONES 绑定与凭据有效
- **THEN** Tool Catalog 使用稳定 Identifier、业务 description 和公开 Schema 暴露该 Tool

#### Scenario: 应用未允许 Capability
- **WHEN** Agent Envelope 包含 Capability 但 Application Allowlist 不包含
- **THEN** Tool Catalog 不包含该 Tool

#### Scenario: 用户没有个人凭据
- **WHEN** 应用允许 ONES Capability但当前用户只有身份元数据或凭据 invalid
- **THEN** Tool Catalog MUST 不暴露或批准该 Tool，同时 MUST 向模型投影一条不可调用的固定安全提示，说明当前发送者需要在“我的外部身份”完成绑定或重新验证、选择 default Team 并重新发送请求

#### Scenario: 应用未选择 Capability 时不泄露提示
- **WHEN** Agent Envelope 包含 Capability 但 Application Allowlist 不包含
- **THEN** 运行时既不暴露该 Tool，也不向模型投影该 Capability 的不可用提示

### Requirement: 每次 Tool 执行重新校验授权和可用状态
受治理 API Tool 在实际外部请求前 MUST 重新校验 Job 冻结的 Agent/Application 引用、Allowlist、Release 运维状态、当前用户身份、default Team 和个人 Token；模型参数、缓存 Catalog 或先前成功调用 MUST NOT 绕过复核。

#### Scenario: Tool 暴露后 Release 被禁用
- **WHEN** 模型准备调用时目标 Release 已从 ACTIVE/DEPRECATED 变为 DISABLED
- **THEN** 执行器失败关闭且不发起外部 HTTP 请求

#### Scenario: Tool 暴露后用户解绑
- **WHEN** 用户在同一 Job 执行期间解绑 ONES
- **THEN** 后续调用失败关闭，不使用历史 Token

### Requirement: Job 冻结外部执行主体但不冻结 Token
创建需要 ONES Capability 的 Agent Job 时，系统 MUST 冻结当前外部 User ID 和 default Team ID 作为 External Execution Subject Snapshot，且 MUST NOT 把 Token写入 Job、消息总线或快照。

#### Scenario: Job 创建后用户切换默认 Team
- **WHEN** Job 已冻结 Team A 而用户后来切换为 Team B
- **THEN** 旧 Job 不切换到 Team B，后续调用因快照 Team 不再有效而失败关闭

#### Scenario: 用户只轮换 Token
- **WHEN** 外部 User ID 和快照 Team 保持有效且用户更新个人 Token
- **THEN** 旧 Job 可在调用时解析新 Token继续执行

### Requirement: 主体快照必须实时复核撤权
每次外部调用前系统 MUST 确认快照 User ID 等于当前启用绑定主体、快照 Team 仍属于最新验证 Team 集合，并解析当前有效个人 Token；换绑、解绑、Team 撤销或凭据失效 MUST 导致失败关闭，且不得回退到管理员、服务账号或其他 Team。

#### Scenario: 用户换绑另一个 ONES 账号
- **WHEN** 旧 Job 的 User ID 与当前绑定 User ID 不一致
- **THEN** 系统拒绝调用，不使用新账号替代旧快照

#### Scenario: ONES 撤销快照 Team
- **WHEN** 最新验证 Team 集合不再包含 Job 快照 Team
- **THEN** 系统拒绝调用并提示重新发起任务，不选择其他 Team

### Requirement: 系统上下文字段不可由 Agent 覆盖
外部 User ID、default Team ID、Token、Connection Origin、认证 Header、Handler Path 和固定 GraphQL document MUST 来自冻结配置或平台 System Context，MUST NOT 出现在 Agent 可写 Input Schema或被模型参数覆盖。

#### Scenario: 模型参数包含 Team ID
- **WHEN** Tool 调用提交公开 Schema之外的 `team_id`
- **THEN** Input Schema 校验拒绝请求，执行器不读取或使用该值

#### Scenario: Mapping 同时引用 Agent 和 System Context
- **WHEN** 请求 Mapping 从 Agent Input 读取 keyword、从 System Context 读取 User/Team
- **THEN** 执行器分别使用已验证来源并保持系统字段不可写

### Requirement: 固定执行管线解释已编译 Mapping Plan
运行时 MUST 只执行 Release 冻结的 `http-json-v1` 和已编译 Mapping Plan，顺序为输入校验、System Context 构造、Request Mapping、同 Origin认证注入、受限 HTTP、内存 JSON 解析、Response Mapping、Output Schema 校验和规范化结果返回。

#### Scenario: 合法调用完成
- **WHEN** 输入、身份、HTTP 响应和所有 Mapping/Schema 均有效
- **THEN** 系统返回完整规范化结果并记录有界 Tool 事件

#### Scenario: 标量转换失败
- **WHEN** Response Mapping 无法把外部值转换为声明类型
- **THEN** 整次调用以契约错误失败，不返回部分数组或部分对象

#### Scenario: 运行时遇到未知 Mapping 节点
- **WHEN** 编译计划 schema version 不受支持或包含未知节点
- **THEN** 系统在外部调用前失败关闭并记录安全完整性错误

### Requirement: 外部 HTTP 请求遵守冻结网络和认证边界
执行器 MUST 使用精确 Connection Origin与Handler相对路径，认证材料只允许按冻结 Authentication Profile 注入同 Origin 请求；执行器 MUST 执行连接/读取超时、最大响应大小、JSON content 约束并拒绝跨 Origin 重定向。

#### Scenario: 正常同 Origin 请求
- **WHEN** Release 引用的 Connection、Handler 和 Authentication Profile 均有效
- **THEN** 执行器向唯一规范化目标发起请求且不向其他 Origin 发送 Token

#### Scenario: 返回超大响应
- **WHEN** 外部响应超过配置上限
- **THEN** 执行器立即停止读取，按非重试失败处理且不保存已读取正文

### Requirement: QUERY 调用使用有界重试分类
对 `operation_semantics=QUERY`，网络错误、超时、429、502、503 和 504 SHALL 在单次 Tool 总预算内最多重试两次并退避；401、403、400、404、超大响应、无效 JSON、Mapping 或 Schema 错误 MUST NOT 重试。

#### Scenario: 外部服务首次返回 503
- **WHEN** 第一次 attempt 返回 503 且仍有时间预算
- **THEN** 系统按策略退避并最多再尝试两次

#### Scenario: 外部服务返回 401
- **WHEN** attempt 返回 401
- **THEN** 系统不重试，原子标记当前个人凭据 invalid并返回重新验证提示

#### Scenario: 外部服务返回 403
- **WHEN** attempt 返回 403
- **THEN** 系统不重试且不使凭据失效，返回权限不足的安全结果

#### Scenario: 输出 Schema 不匹配
- **WHEN** 外部 HTTP 成功但规范化结果不满足 Output Schema
- **THEN** 系统按非重试契约错误失败且不返回部分结果

### Requirement: 每个 HTTP attempt 独立记录安全元数据
重试 attempts MUST 共享 job_id、tool_call_id 和 correlation_id，并 SHALL 分别记录 attempt 序号、状态分类、耗时、响应大小摘要和安全错误码；记录 MUST NOT 包含认证材料、请求正文、原始响应或不受限业务内容。

#### Scenario: 两次重试后成功
- **WHEN** 查询在第三次 attempt 成功
- **THEN** 审计可关联三个 attempt 和一个 Tool Call结果，但不复制任何原始 HTTP body

### Requirement: 原始响应只存在于单次 attempt 内存
外部 HTTP 原始响应 MUST NOT 写入数据库、缓存、日志、审计、错误、模型上下文或测试 UI；只有通过 Mapping、Output Schema 和大小限制的规范化结果 MAY 按既有 Tool Call、会话和最终回复模型持久化。

#### Scenario: ONES 返回正常工作项
- **WHEN** Response Mapping 和 Output Schema 均成功
- **THEN** 系统保存有界规范化结果及 `INTERNAL` 来源元数据，不保存原始响应

#### Scenario: ONES 返回无效 JSON
- **WHEN** 响应无法解析
- **THEN** 系统只记录状态、大小、hash和安全错误分类，不记录响应片段

### Requirement: INTERNAL 分类随规范化结果传播
Capability Release MUST 冻结数据分级；`INTERNAL` 规范化 Tool结果和最终回复 SHALL 继承 user、Application Publication、Capability Release 和分类来源，并只允许具备对应应用和 Job 访问权的主体读取。本变更 MUST NOT 对这些正常结果执行定时清理。

#### Scenario: 保存 INTERNAL Tool 结果
- **WHEN** ONES Capability成功返回规范化工作项
- **THEN** Tool Call和最终回复按现有生命周期保存，并关联用户、应用、Capability和INTERNAL分类

#### Scenario: 未来记忆摄取结果
- **WHEN** 后续记忆系统尝试读取该结果
- **THEN** 它必须继承上述来源与访问边界；本变更不实现该记忆摄取

### Requirement: 外部文本始终是不可信业务数据
规范化输出中的外部文本 MUST 作为 Tool data传给模型，不得拼接为 system、developer 或 Tool 指令，也不得因文本内容扩大可用 Tool、权限、System Context或 Mapping 能力。

#### Scenario: 工作项名称包含指令文本
- **WHEN** ONES 工作项名称试图要求模型泄露 Token或调用未授权 Tool
- **THEN** 运行时仍把它作为普通字段，且授权、Schema与 Tool集合不发生变化

### Requirement: Agent 可通过公开 Schema 组合 Capability
Agent SHALL 能依据用户消息、会话上下文和前一个 Capability 的规范化输出，组织后一个 Capability 的结构化 Input；每个调用 MUST 独立通过 Schema、Agent Envelope、Application Allowlist、Release状态、身份与凭据校验，平台 MUST NOT 建立隐式 Handler-to-Handler管道或透传原始响应。

#### Scenario: Tool A 输出用于 Tool B 输入
- **WHEN** 模型读取 Tool A 的规范化字段并构造 Tool B 的合法输入
- **THEN** Tool B 作为独立调用执行全部治理校验

#### Scenario: Tool A 未在应用 Allowlist
- **WHEN** 模型尝试调用未被当前应用允许的 Tool A 以获得输入
- **THEN** 该 Tool 不被暴露且执行请求被拒绝


<!-- Migrated from canonical source capability: `governed-capability-handler-runtime` -->

### Requirement: Capability Handler 实现必须来自代码注册表
系统 MUST 从代码加载稳定 Handler ID、不可变版本、输入/输出 schema、风险等级、所需权限和逻辑资源槽；数据库只能管理安装、治理与发布元数据。

#### Scenario: 发布已安装 Handler
- **WHEN** 数据库发布的 Handler ID 和版本存在于当前代码注册表
- **THEN** 系统可以将其标记为可参与运行时解析

#### Scenario: 数据库包含动态 Handler 内容
- **WHEN** 配置试图保存或执行 Python、脚本、SQL 模板或任意 URL 作为 Handler 实现
- **THEN** 系统必须拒绝

### Requirement: Handler 可执行集合必须满足全部治理交集
运行时 MUST 仅在 Handler 同时满足 installed、published、resource-bound、agent-allowed、application-allowed、role-allowed 和 scope-allowed 时执行。

#### Scenario: 任一授权维度缺失
- **WHEN** Handler 已安装且已发布，但当前角色未获授权
- **THEN** 系统必须拒绝调用并记录不含敏感数据的拒绝原因

### Requirement: Handler 逻辑资源槽必须在应用发布时绑定
Handler MUST 只声明逻辑资源槽，业务应用发布 MUST 将每个必需槽绑定到具体已发布 Resource Revision。

#### Scenario: 必需槽未绑定
- **WHEN** 业务应用尝试发布但某 Handler 必需资源槽没有有效 revision
- **THEN** 系统必须阻止应用发布

### Requirement: Job 必须固化不可变 Execution Scope
Job 创建时 MUST 固化业务应用发布、Handler 版本、Resource Revision 绑定及环境/基地/车间范围；Agent、Handler 和请求 payload 均不得在执行时扩展或替换该范围。

#### Scenario: Agent 请求另一个基地
- **WHEN** 工具参数指定的基地不在 Job 固化 Execution Scope
- **THEN** Internal API Platform 必须拒绝该调用且不访问目标资源

### Requirement: 通用数据库查询必须作为受治理的只读业务能力
`query_database` MUST 出现在业务应用 API 能力目录，但仍只允许调用代码内置的只读 Handler；平台不得因此新增面向外部调用方的公共查询端点。

#### Scenario: 业务应用选择通用数据库查询
- **WHEN** 业务应用在组成配置中选择 `query_database`
- **THEN** 平台必须允许保存和校验该能力，并继续要求 Agent、应用、角色、数据范围和数据库资源绑定全部通过

#### Scenario: 通用数据库查询缺少治理条件
- **WHEN** `query_database` 缺少已发布资源绑定、角色授权或 Execution Scope
- **THEN** 平台必须在访问数据库前拒绝调用


<!-- Migrated from canonical source capability: `ones-work-item-search` -->

### Requirement: 第一版只发布一个生产 ONES 查询 Capability
第一版生产范围 MUST 只包含 `cap__ones__work_item__search`，其 `operation_semantics` MUST 为 `QUERY`，数据分级 MUST 为 `INTERNAL`；系统 MUST NOT 在本变更发布 ONES 写入、详情、跨 Team 或其他 Provider Capability。

#### Scenario: 发布工作项搜索
- **WHEN** 管理员完成完整验证和发布
- **THEN** 系统创建稳定 Identifier 下的 QUERY/INTERNAL Release

#### Scenario: 配置 ONES 写操作
- **WHEN** 管理员尝试在第一版使用相同框架发布创建或更新工作项
- **THEN** 发布校验拒绝该操作语义

### Requirement: 工作项搜索公开输入契约固定
`cap__ones__work_item__search` Input Schema MUST 只公开 `keyword`、`issue_type` 和 `limit`；`issue_type` MUST 限定为 `demand`、`task`、`defect`，`limit` MUST 为 1 至 50 的整数。User ID、Team ID、Token、Origin、Path 和 GraphQL document MUST NOT 公开。

#### Scenario: Agent 提交合法搜索
- **WHEN** Tool Input 包含合法 keyword、issue_type 和 limit
- **THEN** 系统接受输入并由平台注入当前 Job快照 User/Team及当前Token

#### Scenario: limit 超出范围
- **WHEN** Agent提交 limit 为 0、51 或非整数
- **THEN** 系统在外部调用前拒绝并返回结构化输入错误

#### Scenario: Agent 尝试覆盖 Team
- **WHEN** Tool Input包含 `team_id`、`user_id`或认证字段
- **THEN** 系统按未知/禁止字段拒绝，且不使用这些值

### Requirement: 工作项搜索公开输出契约固定
Capability Output Schema MUST 返回有界工作项数组，每项只包含 `number`、`name`、`type`，并返回 `total` 和 `truncated`；所有字段 MUST 完整通过类型和大小校验后才能交给模型。

#### Scenario: 返回有限搜索结果
- **WHEN** ONES 返回匹配工作项且 Mapping 成功
- **THEN** 模型只收到契约字段、total和truncated标记

#### Scenario: 单项缺少必填 number
- **WHEN** 外部响应中的任一映射项无法产生合法 number
- **THEN** 整次调用按输出契约错误失败，不返回其他部分工作项

#### Scenario: 外部结果超过 limit
- **WHEN** ONES匹配数超过请求 limit
- **THEN** 规范化输出最多包含 limit 项，并通过 total/truncated明确说明截断

### Requirement: ONES 搜索使用固定只读 GraphQL POST
Handler MUST 使用固定 GraphQL POST document执行搜索，并 MUST 在 Draft验证和发布时解析或检查该 document 为 query；任何 mutation、动态 document 或 Agent提供的 GraphQL文本 MUST 被拒绝。

#### Scenario: 固定 query 通过验证
- **WHEN** Handler配置受支持的只读搜索 query
- **THEN** 系统将该 document冻结在 Handler Revision中

#### Scenario: GraphQL document包含 mutation
- **WHEN** 管理员或客户端提交 mutation operation
- **THEN** 系统拒绝验证和发布，不向 ONES 发起请求

#### Scenario: Agent输入 GraphQL文本
- **WHEN** Tool Input额外包含 query或document字段
- **THEN** Input Schema拒绝该字段，固定 document不受影响

### Requirement: ONES 查询只使用当前发送人的执行主体
私聊和群聊中的 ONES搜索 MUST 使用每条消息实际钉钉发送人映射的内部用户、该用户的外部 User ID、Job冻结default Team和当前有效个人Token；系统 MUST NOT 使用管理员验证凭据、应用服务账号、群共享主体或其他用户身份。

#### Scenario: 群内两个用户先后查询
- **WHEN** 两条群消息分别来自已绑定用户甲和用户乙
- **THEN** 两个 Job分别冻结并使用各自 User、Team和Token，结果不得串用

#### Scenario: 当前发送人未绑定 ONES
- **WHEN** 钉钉用户可以访问应用但没有可用 ONES凭据
- **THEN** 系统不暴露或不执行搜索，并返回安全中文绑定提示

### Requirement: 完整发布链决定搜索可用性
工作项搜索 MUST 只有在 Published Connection、可运行 Capability Release（`ACTIVE`，或被既有 Application Publication 冻结的 `DEPRECATED`）、包含该精确 Release的 Agent Publication、包含其子集的活动 Application Publication以及当前用户个人绑定均有效时才能调用。

#### Scenario: Agent 未配置 Capability
- **WHEN** 应用选择的 Agent Publication不包含搜索 Release
- **THEN** 应用不能选择该能力，模型也不能调用

#### Scenario: 应用未配置 Capability
- **WHEN** Agent包含搜索 Release但Application Allowlist为空
- **THEN** 模型 Tool Catalog不包含搜索能力

#### Scenario: Release 被紧急禁用
- **WHEN** 运行中的应用仍引用搜索 Release但该 Release变为DISABLED
- **THEN** 所有新搜索调用失败关闭，不自动回退到其他 Release

### Requirement: ONES 错误不导致主体或 Team 回退
未绑定、Token无效、Team权限撤销、403或Release禁用 MUST 返回安全失败并保持原Job主体快照；系统 MUST NOT 切换到管理员、服务账号、新绑定或其他Team。

#### Scenario: Token失效
- **WHEN** ONES搜索返回401
- **THEN** 系统使当前用户凭据失效并提示重新验证，不重试或使用共享Token

#### Scenario: Team被撤销
- **WHEN** Job快照Team不再属于用户最新验证集合
- **THEN** 系统在HTTP请求前拒绝并要求重新发起任务

### Requirement: V1 端到端验收覆盖正向发布链
交付验收 MUST 覆盖管理员首连接启动验证与发布、管理员正式自助绑定和选择默认Team、Capability配置/测试/验证/发布、Agent精确选择并发布、应用选择Agent与能力子集并绑定钉钉应用发布、普通用户自助绑定后从钉钉查询并使用自己的User/Team/Token获得规范化结果。

#### Scenario: 完整正向链成功
- **WHEN** 所有控制面步骤和普通用户绑定均按顺序完成
- **THEN** 钉钉用户收到符合公开Output Schema的工作项结果，审计能关联路由、Job、Release、主体快照、Tool Call和Delivery且不含凭据或原始响应

### Requirement: V1 端到端验收覆盖失败关闭和回归
交付验收 MUST 证明Agent未选时应用不能配置、应用未选时模型不能调用，且未绑定、Token失效、Team撤销和Release禁用均失败关闭；同时 MUST 证明现有内部Tool和未升级Agent/Application Publication行为不变。

#### Scenario: 执行全部负向用例
- **WHEN** 测试分别触发发布链缺口和用户凭据/Team/Release故障
- **THEN** 每个用例在外部调用前或明确故障点安全失败，且无主体或Team切换

#### Scenario: 回归旧应用
- **WHEN** 运行未升级且Capability集合为空的历史Agent/Application Publication
- **THEN** 原有内部只读Tool、Job和Delivery路径保持原行为

### Requirement: 测试 fixture 证明模型侧组合调用
测试环境 MUST 提供两个只读、受治理的测试专用 Capability fixture，用于证明模型可以把第一个Capability的规范化输出组织为第二个Capability输入；fixture MUST NOT 成为生产可选能力或隐式服务端管道。

#### Scenario: 双 Capability组合成功
- **WHEN** 测试Agent依次调用fixture A和fixture B，并用A的公开输出构造B输入
- **THEN** 两次调用分别通过独立治理校验并留下独立Tool Call记录

#### Scenario: fixture出现在生产目录
- **WHEN** 生产环境构建Capability候选目录
- **THEN** 系统排除所有测试专用fixture
