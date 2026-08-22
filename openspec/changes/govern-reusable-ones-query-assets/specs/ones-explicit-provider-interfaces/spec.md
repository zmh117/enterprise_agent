## ADDED Requirements

### Requirement: 每个 ONES 接口必须由代码显式定义
系统 MUST 为每个获准 ONES 接口建立代码拥有的固定 Operation，并在 Operation 中明确 Method、相对 Path、固定 Header、动态 Header 来源、请求体构造和响应解析。系统 MUST 只实现用户提供完整接口契约的 Operation，MUST NOT 从其它接口猜测 URL、Method、Header、变量或响应结构。

#### Scenario: 完整接口契约被实现
- **WHEN** 用户已经提供固定 URL/Path、Method、Headers、请求报文、成功/空结果响应和主要错误状态
- **THEN** 系统按该报文建立单独 Operation 和脱敏契约测试

#### Scenario: 接口契约不完整
- **WHEN** 一个接口缺少会影响请求或解析的 URL、Method、Header、变量或响应字段
- **THEN** 系统不登记、不暴露也不调用该接口，并要求补齐契约而不是自行推断

### Requirement: GraphQL document 必须独立存放并由 Operation 直接引用
系统 MUST 将 GraphQL document 保存于 `services/ones_mcp_server/provider/graphql/documents/`，由一个或多个代码拥有的 GraphQL Operation 直接引用。GraphQL 文件 MUST NOT 包含 Origin、Header、Token、User ID、Team ID 或其它凭据。Registry MUST 继续执行当前 code 唯一、固定相对 GraphQL Path 和只读 `query` 前缀检查，但本 change MUST NOT 增加 AST parser、document 指纹或反向依赖索引。

#### Scenario: Operation 加载 GraphQL 文件
- **WHEN** 已登记 Operation 引用存在且以只读 `query` 开头的 GraphQL 文件
- **THEN** 系统从该文件构造固定 GraphQL POST，并由 Operation 构造 variables 和解析响应

#### Scenario: 多个 Tool 使用同一 GraphQL 文件
- **WHEN** 两个业务 Tool 需要完全相同的 GraphQL document
- **THEN** 两个 Tool 可以直接引用同一文件，同时继续各自维护 Tool schema、授权和响应格式

### Requirement: HTTP Client 只能执行 Operation 指定的固定 GET 或 POST
Provider HTTP Client MUST 复用当前固定 Provider origin、Host allowlist、超时、响应大小、禁止重定向、禁用环境代理、状态分类和 JSON 解析，并允许代码 Operation 选择 `GET` 或 `POST`。Path MUST 是代码构造的固定相对 Path；模型和管理端 MUST NOT 提交 Method、URL、Path、Header 模板或原始请求体。

#### Scenario: 固定 REST GET 被发送
- **WHEN** 已授权 Service 调用一个 Method 为 GET 的显式 Operation
- **THEN** Client 按该 Operation 的固定 Path、Headers 和请求体契约发送请求，其中项目角色成员 GET 固定发送空 JSON Body `{}`

#### Scenario: 固定 REST POST 被发送
- **WHEN** 已授权 Service 调用一个 Method 为 POST 的显式 Operation
- **THEN** Client 按该 Operation 构造的 JSON Body 和固定 Path/Headers 发送请求

#### Scenario: 调用方尝试改变请求目标
- **WHEN** Tool 输入包含 URL、Method、Path、Header、Token 或原始 Body 字段
- **THEN** Tool 输入校验在 Provider 请求前拒绝该调用

### Requirement: 动态认证 Header 必须来自当前 Principal
所有 ONES Operation 的认证 Header 值 MUST 来自当前 Tool 调用解析出的活动个人 ONES 凭据和 User ID；Team UUID MUST 来自当前 Principal 的默认 Team。用户提供报文中的 Token/User ID 只能用于说明 Header 形状，MUST NOT 写入源码、配置样例、fixture、日志、审计或 Tool 输入。

#### Scenario: 当前用户身份被注入
- **WHEN** 已绑定用户调用一个显式 ONES Tool
- **THEN** Operation 使用该用户当前活动 Token/User ID 和默认 Team 构造请求，不使用示例值、管理员或服务账号

#### Scenario: 凭据不可用
- **WHEN** 当前用户没有活动凭据、默认 Team 或精确 Tool 授权
- **THEN** 系统在 Provider 请求前失败关闭

### Requirement: Service 编排必须固定写在业务代码中
当一个 Tool 需要多个接口时，Service MUST 以代码固定调用 Operation 的集合、顺序和数据映射。系统 MUST NOT 提供流程 DSL、数据库动态编排、模型选择 Operation 或运行时替换接口。

#### Scenario: Tool 固定调用两个 REST Operation
- **WHEN** 项目角色人员 Tool 完成角色成员查询并需要查询成员姓名
- **THEN** Service 按代码固定顺序调用角色成员 GET 和用户 POST，模型不能跳过、增加、替换或重排调用

### Requirement: Provider 响应必须按接口契约解析并有界输出
每个 Operation MUST 按用户提供的响应报文校验必需容器、字段、类型和关联键，并由业务 Service 只返回 Tool Output Schema 允许的有界字段。系统 MUST NOT 将完整 Provider 响应返回模型或写入日志/审计。

#### Scenario: 合法响应被映射
- **WHEN** Provider 返回符合该 Operation 契约的 JSON
- **THEN** Service 只输出 Tool 声明的业务字段并标记上游内容为不可信数据

#### Scenario: 响应缺少关联对象
- **WHEN** 第二个接口没有返回第一个接口所请求的全部关联 UUID
- **THEN** 整次 Tool 调用按 Provider 响应不完整失败，不静默省略、错配或返回半成品
