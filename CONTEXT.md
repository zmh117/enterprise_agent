# Enterprise Agent Control Plane

本上下文描述业务应用如何组合 Agent、外部身份和受治理 API 能力，并在消息发送者的权限范围内访问外部业务系统。

## Language

**内部用户（Internal User）**:
平台中承载角色、业务应用权限和数据范围的人员主体。
_Avoid_: 钉钉用户、ONES 用户、账号

**外部身份绑定（External Identity Binding）**:
内部用户与受信外部系统实例中一个已验证账号的关联，只证明主体对应关系，不保存可重复使用的登录凭据，也不自动授予权限。
_Avoid_: 外部凭据、Token 绑定、外部授权

**API 能力（API Capability）**:
向业务应用和 Agent 发布的版本化业务操作及其公开输入输出契约，不暴露底层接口地址、认证信息或传输细节。
_Avoid_: Tool、Endpoint、API Handler

**API 能力配置（API Capability Configuration）**:
管理员在单一工作台维护的聚合配置，同时包含 API 能力业务定义和对应 Handler 调用配置。
_Avoid_: 两个独立配置流程、直接 Handler 绑定、外部 URL 表单

**能力 Handler（Capability Handler）**:
实现 API 能力的不可变版本化请求规则，由管理员配置、平台验证并交给固定代码 Executor 执行。
_Avoid_: API 能力、任意代码、脚本

**API Connection**:
受平台治理的外部系统实例，提供固定服务地址、认证协议和网络出口边界，不包含具体业务操作。
_Avoid_: API Handler、用户 Token、任意 URL

**认证配置（Authentication Profile）**:
API Connection 中定义外部登录、主体与范围提取以及运行时认证注入方式的版本化协议，不属于业务 API 能力。
_Avoid_: 登录 Capability、登录 Handler、Agent Tool

**Connection Origin 边界（Connection Origin Boundary）**:
API Connection 固定的 Scheme、Host 和 Port 边界，Handler 只能在该 Origin 下使用相对路径，认证凭据不得发送到其他 Origin。
_Avoid_: 完整 Network Zone、任意 URL、动态 Host

**外部 API 凭据（External API Credential）**:
内部用户在一个外部系统实例中调用业务 API 所需的加密 Token，与外部身份绑定分开管理且不包含用户密码。
_Avoid_: 外部身份、登录密码、平台 Session

**验证凭据（Verification Credential）**:
API Connection 专用于 Handler 验证和测试的受限外部 Token，不能用于真实业务调用或作为用户凭据回退。
_Avoid_: 用户外部 API 凭据、运行时服务账号、共享回退 Token

**应用发布（Application Publication）**:
业务应用经过校验后形成的不可变运行版本，冻结其 API 能力及全部解析后的执行依赖版本。
_Avoid_: 应用草稿、当前最新配置、动态别名

**用户能力可用状态（User Capability Availability）**:
当前内部用户在一次调用中满足外部身份、Team、凭据和授权交集后得到的个人可执行状态，不影响应用自身发布状态。
_Avoid_: 应用就绪、全局 Capability 状态、用户已绑定即有权限

**凭据主体策略（Credential Subject Policy）**:
能力 Handler 用于确定外部 API 凭据所有者的显式规则，当前允许当前消息发送人或指定服务账号两类主体。
_Avoid_: 自动回退、会话共享凭据、任意用户

**ONES Team 范围（ONES Team Scope）**:
业务应用为一个 API 能力绑定的单一 ONES Team，是该能力调用不可由消息或 Agent 扩大的外部数据范围。
_Avoid_: 用户输入的 team_uuid、全部已加入 Team、自动跨 Team

**操作语义（Operation Semantics）**:
API 能力对外部业务状态产生影响的分类，与 HTTP Method 无关；第一版只允许不改变业务状态的 `QUERY`。
_Avoid_: GET 等同只读、POST 等同写入、模型自行判断

**Handler 发布版本（Handler Revision）**:
能力 Handler 通过验证后形成的不可变执行版本，可被禁用或归档但不能原地修改。
_Avoid_: Handler Draft、可编辑发布记录、最新浮动配置

**能力发布（Capability Release）**:
一次原子发布形成的不可变事实，固定一个 API 能力版本及其 Handler、Connection 和认证配置版本。
_Avoid_: 浮动最新 Handler、独立半成品发布、应用临时解析

**字段映射计划（Mapping Plan）**:
由受限类型化字段映射编译得到的不可变请求与响应投影，不支持通用表达式、脚本或 Secret 读取。
_Avoid_: 模板引擎、脚本、任意 JSON 转换

## Relationships

- 一个 **内部用户**可以绑定多个不同 Provider 或系统实例的**外部身份绑定**
- 一条钉钉消息先把发送者解析为**内部用户**，再计算业务应用和 **API 能力**权限
- **外部身份绑定**与外部系统调用凭据是两个独立事实
- 一个启用的**外部身份绑定**对同一**认证配置**版本至多关联一个当前有效的**外部 API 凭据**
- **外部 API 凭据**失效后必须由用户重新验证，平台不得依靠持久化密码自动登录
- 一个 **API Connection**可以配置一个**验证凭据**及固定测试范围
- **验证凭据**只允许 Handler Verify/Test 使用，绝不能进入真实 Agent Job 或替代**外部 API 凭据**
- Handler 验证只保留状态、Schema 摘要、耗时、响应大小和脱敏错误，不保存完整外部响应
- **API Connection**通过**认证配置**完成用户身份验证、Token 提取和运行时认证 Header 注入
- 登录接口只允许身份与凭据服务调用，不得发布为 **API 能力**或暴露给 Agent
- **能力 Handler**只能声明凭据主体策略，不能读取 Token、修改认证 Header 或覆盖外部主体
- **应用发布**冻结**认证配置**版本，但不保存或冻结具体**外部 API 凭据**
- 每次调用按当前内部用户和被冻结的**认证配置**版本解析最新有效 Token
- 用户重新验证只轮换**外部 API 凭据**，不要求重新发布业务应用；认证配置变更则需要新版本和应用显式升级
- 应用发布只验证 Capability、Handler、Connection、Team、验证凭据和治理授权，不枚举未来使用者
- **用户能力可用状态**由当前用户的外部身份、Team、有效 Token、角色和能力授权共同决定
- 任一用户的**用户能力可用状态**失败只阻止该用户调用，不改变应用发布或其他用户的状态
- 模型 Tool 暴露前必须计算**用户能力可用状态**，不可用的 API 能力不进入本次 Tool 列表
- 不可用能力可以向模型提供安全原因和中文操作提示，但不得暴露身份、Token 或授权细节
- Handler 执行前必须再次计算**用户能力可用状态**，不得依赖会话或模型暴露阶段的旧结果
- **API 能力**通过已发布的**能力 Handler**执行
- **API 能力**拥有 Agent 可见的公开输入、输出和业务语义 Schema
- **能力 Handler**必须证明其字段映射计划能够实现所绑定 **API 能力**版本的公开 Schema
- 外部接口或字段位置变化但业务契约不变时只创建新 Handler 版本；公开 Schema 或业务语义不兼容时创建新 API 能力版本
- 管理员只编辑一个 **API 能力配置**并执行一次验证和发布，不需要单独创建或绑定 Handler
- 平台在内部为 **API 能力配置**分别维护业务契约和 Handler 版本，并原子创建**能力发布**
- 业务应用最终冻结**能力发布**，不得在运行时重新解析最新 Handler 或 Connection
- **能力 Handler**必须声明**凭据主体策略**，运行时不得自动改用其他主体
- `CURRENT_ACTOR` 在私聊和群聊中都表示当前消息发送人；群会话不得共享任一成员的**外部 API 凭据**
- ONES 查询第一版只允许 `CURRENT_ACTOR`，缺失或失效凭据时失败关闭，不回退平台服务账号
- 业务应用为每个 ONES **API 能力**绑定一个 **ONES Team 范围**，并将其冻结到**应用发布**
- 运行时只在 **ONES Team 范围**同时属于当前发送人的已验证 Team 集合时调用 ONES
- 消息、Agent 参数和**能力 Handler**输入不得提供或替换 `team_uuid`
- **能力 Handler**必须声明**操作语义**；第一版只允许 `QUERY`
- `QUERY` 可以使用 HTTP POST，但 GraphQL Document 必须由 Handler 版本固定且不得包含 `mutation`
- Agent 只能提供 Input Schema 允许的变量，不能提供原始 GraphQL、任意请求体或响应字段
- **能力 Handler**使用**字段映射计划**在 Capability 输入、系统上下文、外部请求和 Capability 输出之间投影字段
- **字段映射计划**只能读取声明的输入、常量和系统上下文，不能读取 Token、Secret、环境变量或动态主机
- **字段映射计划**必须通过字段存在性、类型、系统字段所有权、数组数量、字符串长度和响应大小校验
- 能力 Handler 遵循 `DRAFT → VERIFIED → PUBLISHED`，任何 Draft 变更都会使旧验证结果失效
- 只有最新 Draft 验证通过后才能创建**Handler 发布版本**
- **Handler 发布版本**不可修改或普通删除；被禁用后所有新调用失败关闭，被归档后不再供新绑定选择
- 业务应用和 Agent 只引用 **API 能力**，不得直接选择**能力 Handler**或 **API Connection**
- 一个已发布 **API 能力**版本解析到一个确定的**能力 Handler**版本
- 一个**能力 Handler**绑定一个已发布的 **API Connection**版本，只保存受限 Method、相对路径和请求/响应映射
- **能力 Handler**不得保存完整 URL、任意代码、脚本或直接引用 Secret
- **API Connection**是平台级共享治理资源，多个 API 能力可以引用同一已发布 Connection 版本
- API 能力配置只能选择已发布 **API Connection**版本，不能内联修改地址、认证 Header 或 Secret
- 新 Connection 版本不会自动改变能力发布或应用发布；依赖方必须重新验证并显式发布升级
- 第一版暂不实现 Network Zone、CIDR 或完整 DNS/IP 出口策略，但每个 **API Connection**必须保留 **Connection Origin 边界**
- Handler 只能配置相对路径，不得改变 Scheme、Host 或 Port；用户 Token 只能发送到被冻结的 Connection Origin
- 跨 Origin 重定向必须拒绝；本变更不得宣称已经完成通用 SSRF 防护
- **应用发布**冻结 API 能力、能力 Handler 和 API Connection 的精确发布版本
- 发布新的**能力 Handler**版本不会改变既有**应用发布**；升级必须重新校验、发布并激活业务应用
- 既有依赖版本被禁用时，相关**应用发布**的新调用失败关闭，不得自动升级、回退或切换版本

## Example dialogue

> **Dev:** “用户已经绑定 ONES，Handler 能直接拿这个绑定重新登录 ONES 吗？”
> **Domain expert:** “不能。身份绑定只证明这个 ONES 账号属于该内部用户；Handler 使用独立保存的加密 Token，Token 失效后由用户重新验证。”

## Flagged ambiguities

- “绑定 ONES”曾被用于表示运行时可以重新登录 ONES；已解决为身份映射与 Token 凭据分离，且永不持久化 ONES 密码。
- “管理员设置 Handler”曾在代码插件和任意动态实现之间含糊；已解决为管理员配置受限 HTTP 规则，固定代码 Executor 负责执行。
- “给应用配置 API”曾被用于表示直接绑定 Handler；已解决为应用和 Agent 只绑定业务层 API 能力，Handler 与 Connection 保持平台治理细节。
- “发布新 Handler”曾被理解为线上应用自动获得新实现；已解决为应用发布冻结精确版本，升级只能通过显式重新发布完成。
- “群聊调用 ONES”曾可能被理解为共享会话凭据；已解决为每条消息按当前发送人独立解析凭据，且不得回退共享账号。
- “查询用户的 ONES”曾可能表示查询其所有 Team；已解决为每个应用 Capability Binding 固定一个 Team，并与发送人的已验证 Team 求交集。
- “只读 Handler”曾被理解为只允许 HTTP GET；已解决为按业务操作语义判断，允许固定只读 GraphQL 的 POST，但禁止 mutation 和原始查询输入。
- “修改已发布 Handler”曾被理解为直接编辑当前配置；已解决为发布版本不可变，任何调整都从新 Draft 开始并重新验证发布。
- “测试 Handler”曾可能使用管理员或任意业务用户 Token；已解决为 Connection 使用独立验证凭据，且与真实运行凭据完全隔离。
- “ONES 登录 API”曾可能被当作 Agent 可调用能力；已解决为 Connection Authentication Profile 的内部认证协议，永不进入 Capability Catalog。
- “应用发布冻结凭据”曾可能被理解为把 Token 写入发布快照；已解决为只冻结认证协议版本，运行时读取当前用户最新有效 Token。
- “应用能否使用 ONES”曾被理解为一个全局布尔状态；已解决为应用发布就绪与每个当前用户的能力可用状态分别计算。
- “不可用 Capability”曾可能仍暴露给模型并等待调用失败；已解决为暴露前隐藏并提供安全提示，执行前仍再次失败关闭检查。
- “请求/响应映射”曾可能表示管理员可编写任意模板或表达式；已解决为只支持可静态验证的类型化字段投影。
- “Handler Schema”曾可能同时表示 Agent 业务契约和外部接口结构；已解决为公开业务 Schema 属于 API 能力，Handler 只负责实现和验证该契约。
- “Capability 与 Handler 分离”曾可能表示管理员需要维护两个对象；已解决为产品上一体化 API 能力配置和一次发布，平台内部保留职责与版本分离。
- “配置 ONES API”曾可能在每个 Capability 中重复填写 Base URL 和认证；已解决为共享 API Connection 独立治理，Capability 只引用发布版本。
- “暂不做网络限制”曾可能表示允许 Handler 请求任意 URL；已解决为延期完整 Network Zone，但仍固定 Connection Origin、限制相对路径并禁止 Token 跨 Origin。
