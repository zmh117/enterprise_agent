## Context

当前平台已经具备：

- PostgreSQL 持久化的 Agent、Business Application、Channel、Job、Tool Call、审计、外部身份和加密 Secret 基础；
- 不可变 Agent/Application Publication 与活动应用路由解析；
- `ToolRegistry`、Claude SDK 内嵌 MCP Server 和代码注册表型内部只读 Handler；
- 用户详情中的 `ExternalIdentityPanel`，以及 ONES 登录验证但不保存 Token 的身份绑定能力。

缺口是“声明式受治理外部 API”这条独立控制面和数据面。现有代码注册表 Handler 适合平台内置工具，不允许管理员创建动态 HTTP 映射；现有 ONES 身份只证明账号归属，不能为当前钉钉发送人提供可轮换的个人 API Token；现有 Agent/Application 发布快照也尚未冻结精确的外部 Capability Release。

本设计受 ADR-0011 至 ADR-0048 约束。主要利益相关者包括平台管理员、Agent/应用配置管理员、普通钉钉用户、安全与运维人员，以及 Agent Job/Tool Runtime 的维护者。

## Goals / Non-Goals

**Goals:**

- 建立通用、查询优先的声明式外部 API Capability 框架，并交付一个真实 ONES 工作项搜索能力。
- 让管理员在一个页面完成 Capability、Schema、Handler Mapping 和测试，但在领域与持久化层保持职责分离。
- 让 Connection、Capability、Handler、Mapping Plan 和 Release 经过可验证、不可变、可审计的发布过程。
- 让 Agent 与 Application 冻结精确 Release，并使模型只看到当前应用、当前用户此刻确实可用的 Tool。
- 保证钉钉私聊和群聊都使用每条消息实际发送人的 ONES User ID、默认 Team 和个人 Token。
- 原始外部响应和认证材料不进入数据库、日志、审计、错误、模型上下文或测试预览。
- 保持现有内部只读 Tool 和未升级的 Agent/Application Publication 行为不变。

**Non-Goals:**

- 不支持写操作、任意脚本、Python/JavaScript/SQL、通用表达式语言或服务端 Handler-to-Handler 流水线。
- 不支持多个 ONES 实例、同一用户多个 ONES 账号、跨 Team 查询或应用固定 User/Team。
- 不实现通用网络区、CIDR、DNS 重绑定治理，也不宣称已解决全部 SSRF 风险。
- 不新增逐用户/逐角色 Capability `use` Grant、双人审批或全局功能开关。
- 不实现定时清理规范化 Tool 结果、会话 retention 执行器或记忆系统。
- 不在第一版交付 ONES 详情、创建、更新等其他生产 Capability。

## Decisions

### 1. 新建受治理 API bounded context，与内部 Handler 注册表并存

后端新增 `api_capability` bounded context，承载外部 API 控制面和运行时端口；用户 ONES 身份及个人凭据继续归属 `identity` bounded context。现有 `internal_tools` 代码注册表 Handler 保持不变。

两类 Tool 通过统一的 Agent Tool Catalog 投影汇合：

- 内部 Tool 使用现有名称和代码注册表实现；
- 受治理外部 Tool 必须使用 `cap__` 前缀，由已发布 Capability Release 和固定 `http-json-v1` 执行器实现。

这样可复用现有 Claude Tool 循环，又不会放宽内部 Handler “不得由数据库注入实现代码”的边界。备选方案是把外部 Handler 塞入现有代码注册表，但这会使每次业务映射都要求发版，也无法满足管理员配置需求，因此不采用。

### 2. 领域对象独立，统一 Draft 负责编辑体验

持久化模型至少包括：

- `ApiConnection` / `ApiConnectionRevision`：稳定身份、固定 Origin、环境约束、状态与验证摘要；
- `AuthenticationProfile` / `AuthenticationProfileRevision`：固定登录相对路径、Token/User/Team 提取规则、认证 Header 注入规则；
- `ApiCapability` / `ApiCapabilityRevision`：稳定 Identifier、名称、业务 `description`、公开 Input/Output Schema、`operation_semantics`、数据分级；
- `ApiHandler` / `ApiHandlerRevision`：固定执行器 ID、HTTP method、相对路径、固定 GraphQL document、请求/响应 Mapping 配置；
- `CompiledMappingPlan`：发布时从声明式 Mapping 编译出的不可变、带 schema version 和 hash 的执行计划；
- `CapabilityRelease`：精确冻结 Capability、Handler、Connection、Authentication Profile 和 Mapping Plan Revision，并持有单调递增 Release Revision、`release_note` 与独立运维状态；
- `ApiCapabilityDraft`：统一工作台的可编辑聚合，保存上述对象的候选配置、`revision`、规范化内容 hash 和最近验证证据。

界面只有一个保存、一个 Verify、一个 Publish。后端仍以独立对象和外键表达边界，Publish 在单事务中创建或复用 Capability Revision、创建 Handler Revision、编译 Mapping Plan 并创建 Release。

备选方案是把全部 JSON 存为一个可变配置对象；它实现快，但无法独立版本化公共契约与外部实现，也难以判断 Handler-only 变更是否需要新 Capability Revision，因此不采用。

### 3. 使用专用 Capability Identifier 与版本规则

Capability Identifier 同时是业务主键、模型 Tool 名、Agent/Application 引用和审计标识。专用校验器要求：

- 格式为 `cap__<provider>__<domain>__<operation>`；
- 层级使用双下划线，层级内使用小写 snake_case；
- 总长不超过 128，且全局唯一；
- `cap__` 是外部受治理 Capability 保留前缀，内部 Tool 禁止使用。

Identifier 不带 `v1`/`v2`。公共 Schema 改变时创建新的 Capability Revision；只改变路径、固定查询或 Mapping 时复用 Capability Revision并创建新的 Handler Revision；业务含义改变时创建新 Identifier。每次发布在 Identifier 内生成单调递增 Release Revision。

现有通用业务编码校验器会拒绝连续下划线，不能复用。备选的“点号业务编码 + 模型名转换”会产生两套身份和映射歧义，因此不采用。

### 4. Mapping Plan 是可静态验证的受限 AST

管理端配置只表达确定性数据投影。编译器接受：

- 从 Agent Input、平台 System Context 和固定常量取值；
- 字段重命名、对象层级调整；
- 受限对象/数组路径读取和数组逐项投影；
- `string`、`integer`、`number`、`boolean` 的显式转换；
- 可选字段缺失时使用管理员配置的固定默认值。

编译器拒绝未知节点、条件、过滤、拼接、日期计算、正则、函数、脚本、模板、秘密读取、任意 URL 和动态 host。运行时任何必填字段缺失、类型转换失败、数组边界或 Output Schema 失败都使整次调用失败，不返回部分结果。

编译结果保存 schema version、canonical JSON 和 SHA-256，运行时只解释已发布编译计划，不解释 Draft。备选方案是 JSONPath/JMESPath 加模板字符串，但其表达能力过大、审计难度高且容易演变成脚本语言，因此不采用。

### 5. Connection 固定 Origin，Authentication Profile 管理登录与注入

Connection Revision 只保存规范化 Origin（scheme、host、port）、显式明文 HTTP 授权和安全的超时/响应大小配置。Handler 只能保存相对路径；HTTP 客户端禁止跨 Origin 重定向，认证材料只能注入同一 Origin 请求。HTTPS 是默认传输；企业内网或本地 ONES 使用 HTTP 时，管理员必须在 Draft 中显式启用 `allow_plain_http`，界面必须说明密码、Token 和业务数据可能被窃听或篡改。该授权在开发、测试和生产环境语义一致，并冻结到不可变 Connection Revision。

旧 API 字段 `allow_insecure_local_http` 只作为升级期输入别名接受，规范化输出和新发布统一使用 `allow_plain_http`；数据库迁移将 Draft 与 Revision 的旧列名改为新列名。若 scheme 为 HTTPS，规范化结果强制把该授权置为 false，避免无意义或陈旧的明文授权进入内容 hash。

Authentication Profile Revision 保存固定登录相对路径、登录请求字段、Token/User/Team 提取路径和认证 Header 注入规则。登录动作是身份基础设施能力，不作为 Capability 或模型 Tool 暴露。

Connection 生命周期为 `DRAFT → VERIFIED → PUBLISHED`。首个 Connection 尚无 Published Revision 时，具备 `api_connections.verify` 的当前管理员可以临时输入自己的邮箱密码验证 Draft Origin、登录、提取和 Header 注入；密码与 Token 仅在该请求内存在，不创建运行时账号。发布后管理员必须通过正式自助绑定，才能测试 Capability。

本设计只承诺固定 Origin、相对路径和拒绝跨 Origin 重定向。完整出站网络区治理延期，避免给出不真实的 SSRF 安全保证。

### 6. ONES 自助绑定使用短时单次 Challenge

当前用户的绑定分两阶段：

1. 自助接口从认证会话取得内部 User ID，接收邮箱和密码，调用精确 Published Connection/Authentication Profile Revision。成功后创建绑定该用户和 Connection Revision 的短时单次 Verification Challenge；返回安全用户信息、Team 候选与 Challenge ID，不返回 Token。
2. 当前用户从候选中选择默认 Team。服务端以乐观/原子方式消费 Challenge，保存或更新 ONES External Identity、最新验证 Team 集合、默认 Team，以及使用应用主密钥加密的 `ExternalApiCredential` Token。

为了支持多 API 实例的无状态服务，Challenge 在数据库保存加密 Token、候选摘要、过期时间和 consumed 状态；密码永不保存。读取 Challenge 必须同时校验当前用户、Connection Revision、未过期和未消费。过期记录不构成可用凭据，可由后续维护任务清理；这与“不对正常 Tool 结果做定时清理”无关。

用户切换默认 Team 必须重新走登录 Challenge，以最新 Team 集合为准。每个内部用户第一版最多一个有效 ONES 身份和一个有效个人凭据。401 将凭据标为 invalid；403 保留凭据状态。

`ExternalIdentityPanel` 增加本人模式和管理员治理模式，普通用户新增“我的外部身份”路由复用同一组件。模式由入口及其授权边界决定：“我的外部身份”始终进入本人模式；受治理授权保护的“人员管理 → 用户详情”始终进入管理员治理模式，即使管理员查看自己的人员记录也不切换为本人模式。前端认证边界仍可向受保护后代暴露当前会话用户，但不再用主体相等关系选择面板模式；普通用户不能因此读取人员列表、角色、会话或其他用户详情。

本人模式使用面向当前主体的外部身份读模型：展示当前钉钉身份的状态、租户和最近使用信息，但钉钉身份只读；展示 ONES 时，身份和凭据必须通过 `external_identity_id` 精确关联，不得把按租户排序的第一条历史身份与最新凭据拼接。本人模式不展示 `unbound` 历史记录。

治理模式的主区域只展示 `enabled` 或 `disabled` 的当前身份；`unbound` 记录继续保留用于审计，但收纳到默认折叠的只读“历史记录”。钉钉治理保留可信绑定、启停、解绑和候选恢复流程，但已绑定记录的租户、外部主体等来源事实不可直接修改；历史记录除匹配候选恢复外不提供普通启停或再次解绑。治理模式不渲染 ONES 邮箱/密码输入，也不能代替用户重新验证，只能读取当前元数据、禁用或软解绑。

现有只有 ONES 身份、没有凭据的记录原样迁移，显示“需要凭据验证”；不伪造 Token，不强制破坏性重绑。

### 7. Verify 绑定内容 hash，Publish 乐观且幂等

Draft 保存要求 `expected_revision`。服务端规范化全部公共 Schema、Handler、Connection 与 Mapping 内容后计算 hash。Capability Verify 使用当前授权管理员自己正式绑定的 ONES 身份/default Team/Token 执行 Draft，并将验证人、Team、时间、结果摘要、Draft Revision 和内容 hash 保存为证据；任何相关内容修改都使证据失效。

Publish 请求必须携带已验证 revision、内容 hash 和 idempotency key。数据库唯一约束保证同一幂等键返回同一 Release；事务内任何 Revision、编译或 Release 创建失败都整体回滚。`release_note` 只进入管理快照，不进入模型 Tool 描述。

测试预览在认证注入前构建可展示的 Method、相对路径、Query、Body 与规范化输出。认证 Header、Cookie、密码、Token 从预览数据结构中完全排除，不依赖字符串掩码。原始响应不返回也不持久化。

### 8. Release 配置不可变，运维状态可变

新 Release 初始为 `ACTIVE`。状态语义为：

- `DEPRECATED`：既有 Application Publication 可继续运行；新 Agent 选择、新应用绑定和升级选择不可使用；可保存原因与 `replacement_release_id`；
- `DISABLED`：所有新 Tool 调用失败关闭，是第一版紧急回退机制；
- `ARCHIVED`：仅历史可见，且活动依赖迁移后才允许进入；
- `ACTIVE`：可被新 Agent 选择并正常运行。

状态变更只写运维状态事件，不修改被冻结的配置。管理员可从任一历史 Revision 复制为新 Draft。平台不按日期自动停用，也不自动替换已发布引用。

### 9. Agent 上限与 Application 子集形成唯一运行资格

Agent Publication 对同一 Identifier 最多冻结一个精确的 `ACTIVE` Release，形成 Agent Capability Envelope。Agent 配置默认推荐最新 ACTIVE，但允许选择仍为 ACTIVE 的旧 Release。

Application Draft 引用精确 Agent Publication，并只能从其 Envelope 勾选子集，发布后形成 Application Capability Allowlist。应用界面不提供独立版本选择器。Agent 发布新版本不会改变旧应用；应用升级 Agent Publication 时重新校验原子集，缺失、DEPRECATED 或公开 Schema 不兼容时阻止发布，要求管理员明确替换或移除。

Agent/Application 界面都显示名称、Identifier、业务 `description`、Release Revision 和状态；`release_note` 只供管理员查看。模型 Tool 定义只使用 Capability `description` 与公开 Schema。

不新增 Capability 用户/角色 Grant。对钉钉入口，命中绑定活动 Application Publication 的连接器且实际发送人解析为启用内部用户，即取得该应用及其 Allowlist 的运行资格；其他 Trigger 继续使用各自既有访问策略。

### 10. Tool Catalog 投影和执行都必须复核

Job 创建时，路由解析器冻结 Application Publication、Agent Publication、Application Allowlist，并在当前用户有可用 ONES 绑定时，为 ONES Capability 冻结 External Execution Subject Snapshot：外部 User ID 和默认 Team ID，不包含 Token。

构建模型 Tool Catalog 时取以下交集：

1. Agent Capability Envelope；
2. Application Capability Allowlist；
3. Release 对该历史 Application Publication 是否可继续运行；
4. 当前用户的 Provider 可用性。

Catalog 投影同时保留两个严格分离的通道：满足完整交集的 Capability 才进入
可注册、可批准的 Tool 集合；已经属于精确 Agent/Application 发布交集、但当前
发送者不满足 Provider 身份前置条件的 Capability，只生成固定白名单文案的
`unavailable` 平台事实供模型解释。后者不是 Tool，不进入 MCP 注册或
`allowed_tools`，不得携带用户、Team、Connection、Credential、Release 或底层异常
细节。应用未选择、Release 不可运行或不符合 QUERY/INTERNAL 边界时，两条通道都
不得暴露该 Capability，避免借提示泄露目录。

模型发起调用后必须再次校验上述条件，并确认：

- Job 快照 User ID 仍等于当前启用绑定主体；
- 快照 Team 仍在最新验证 Team 集合中；
- 当前加密 Token 存在且有效；
- Release 未 `DISABLED`/`ARCHIVED`；
- 调用输入通过精确公开 Input Schema。

解绑、换绑账号、Team 被撤销或凭据失效使旧 Job 失败关闭，绝不切换到新主体/Team；只有 Token 轮换且 User/Team 不变时，旧 Job 才可使用新 Token。

### 11. 外部执行使用固定 `http-json-v1` 管线

执行顺序固定为：

1. 解析精确 Capability Release 快照并复核运行资格；
2. 校验 Agent Input Schema；
3. 构造平台拥有的 System Context（User ID、Team ID、correlation/job/tool IDs）；
4. 执行已编译 Request Mapping；
5. 解析当前用户 Token，并按 Authentication Profile 注入认证；
6. 通过 Connection Origin + Handler relative path 发起受限 HTTP 请求；
7. 在内存中解析受限大小的 JSON；
8. 执行 Response Mapping 与 Output Schema 校验；
9. 返回并按既有 Tool Call/消息模型保存有界规范化结果和安全事件。

每个 HTTP attempt 使用相同 job/tool/correlation 标识，但记录独立 attempt 序号、状态分类和耗时。网络错误、超时、429、502、503、504 对 `QUERY` 最多重试两次并在 Tool 总预算内退避；401、403、400、404、超大响应、无效 JSON 和 schema/mapping 错误不重试。401 原子标记当前凭据 invalid，403 不改变凭据。

原始请求中的认证部分和原始响应只存在于 attempt 内存。日志/审计保存 method、Origin/路径安全标识、Release、状态分类、大小、耗时、hash，不保存正文。规范化 `INTERNAL` 结果可按现有 Job、Tool Call、会话和最终回复模型正常保存；本变更不执行定时清理。

### 12. 模型组合发生在 Tool 循环，不发生在服务器映射层

每个 Capability 的公开 Output Schema 决定模型可见的规范化结果。模型可以结合用户消息、会话上下文和先前 Tool Output，组织后续 Capability 的结构化 Input；后续调用仍独立经过 Schema、Allowlist、身份和凭据校验。

返回的外部文本始终标记为不可信业务数据，不能成为 system/developer/Tool 指令。测试环境提供两个只读 fixture Capability，验证 Tool A 的规范化结果能由模型组织成 Tool B 输入。生产范围仍只有 `cap__ones__work_item__search`。

### 13. ONES 工作项搜索是唯一生产验收能力

`cap__ones__work_item__search` 固定：

- `operation_semantics=QUERY`；
- `data_classification=INTERNAL`；
- 输入包含 `keyword`、`issue_type`（`demand|task|defect`）和 `limit`（1–50）；
- 输出包含工作项 `number`、`name`、`type`，以及 `total`、`truncated`；
- 使用固定只读 GraphQL POST document，并在发布/验证时拒绝 mutation；
- User ID、default Team ID 和 Token 只能由 System Context/credential resolver 注入。

该 Capability 不允许调用方指定 Team、User、Origin、Path 或 GraphQL document。

## Risks / Trade-offs

- [在途内部 Handler 规格要求 role-allowed，易与本变更混淆] → 以 `cap__` 命名空间和独立 resolver 区分；Capability 无单独 `use` Grant，但管理动作仍使用细粒度 RBAC。
- [声明式 Mapping 仍可能成长为难审计的表达式语言] → V1 使用带版本的封闭 AST 节点白名单，未知节点发布即拒绝，新增表达能力必须另行规格化。
- [仅固定 Origin 不能覆盖 DNS 重绑定和复杂出站风险] → 明确安全承诺边界，禁止完整 URL/跨 Origin redirect；完整网络区治理作为后续变更。
- [企业 ONES 使用 HTTP 时认证与业务数据没有传输加密] → HTTPS 保持默认；每个 HTTP Connection 必须显式授权并显示警告，授权进入不可变 Revision 和审计事实，但平台不声称能消除明文链路风险。
- [Challenge 中需要短期保存 Token] → 使用应用级加密、用户/Connection 绑定、短 TTL、单次消费和最小字段；密码永不保存，过期 Challenge 永不可执行。
- [发布状态变更可能使模型已看到的 Tool 在调用前失效] → 执行前再次校验，返回安全、非重试的 Capability 不可用错误。
- [隐藏不可用 Tool 会使模型误判平台未配置该能力] → 保持 Tool fail-closed，并通过独立、非可调用的固定安全提示说明当前发送者需要自助绑定或重新验证；提示不复用原始异常文本。
- [旧 Job 与用户重绑之间存在主体漂移风险] → Job 冻结 User/Team 且逐次调用比对当前绑定；任何不一致失败关闭。
- [第三方 5xx 重试增加 Tool 时延] → 仅 QUERY、最多两次、遵守 Tool 总预算并记录 attempt；其他错误不重试。
- [规范化业务文本可能包含提示注入] → 只作为 Tool data block 返回，不拼入系统指令；模型上下文标注不可信来源并保持 Schema 边界。
- [现有身份-only ONES 数据不满足新运行要求] → 非破坏迁移并显示“需要凭据验证”，不自动生成或共享凭据。
- [一次实现跨控制面、身份、发布和运行时，交付面较大] → 按 Connection/credential、Capability control plane、publication composition、runtime、ONES E2E 的依赖顺序分阶段，每阶段保留失败关闭和回归测试门。

## Migration Plan

1. 增加新表、枚举、索引和约束；为既有 ONES 身份生成“credential missing”投影，不修改或删除身份记录。
2. 部署 Connection/Auth Profile、External Credential 与 Challenge 后端；先用 ONES Mock 验证首连接启动和自助绑定，不暴露任何 Capability。
3. 部署 Capability Draft、Mapping 编译、Verify/Publish 和管理 UI；此时没有 Agent/Application 引用，数据面仍不变。
4. 扩展 Agent Publication、Application Publication snapshot schema 和解析器；旧 snapshot schema 保持可读，缺少 Capability 字段等价于空集合。
5. 部署运行时 Catalog/Executor 和 ONES 查询 Handler；在测试环境完成完整发布链与负向验收后才创建生产 Release。
6. 管理员显式为 Agent 发布新版本、为应用升级并激活；未升级的 Agent/Application 不受影响。

回退不删除数据：先将具体 Release 置为 `DISABLED` 阻止新调用，再回退到不含 Capability 的历史 Application Publication/Agent Publication。数据库迁移保持向前兼容，发布历史、用户绑定和加密凭据保留。

## Open Questions

当前没有阻塞 proposal 实施的产品决策。ONES 实际登录与 GraphQL 响应字段应在实现阶段以 Mock 契约和受控测试环境核对；若真实接口与已确认公共 Schema 不一致，只调整 Authentication Profile/Handler Mapping，不扩大 V1 产品范围。
