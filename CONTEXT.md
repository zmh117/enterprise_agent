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

**Connection 发布版本（Connection Revision）**:
API Connection 通过验证后形成的不可变连接与认证协议版本，可被禁用或归档但不能原地修改。
_Avoid_: Connection Draft、可编辑当前连接、浮动 Base URL

**Connection 启动验证（Connection Bootstrap Verification）**:
首个 Connection 尚无可绑定发布版本时，由当前授权管理员临时输入自己的外部账号密码，对 Draft 的 Origin、登录协议、字段提取和认证注入完成一次无持久凭据的受控验证。
_Avoid_: 正式用户绑定、共享测试账号、把临时 Token 转存为运行时凭据

**外部 API 凭据（External API Credential）**:
内部用户在一个外部系统实例中调用业务 API 所需的加密 Token，与外部身份绑定分开管理且不包含用户密码。
_Avoid_: 外部身份、登录密码、平台 Session

**验证主体（Verification Actor）**:
使用自己外部身份和凭据执行 Connection 或 Handler 真实验证的当前授权管理员，其凭据不进入发布版本。
_Avoid_: 独立共享测试 Token、其他用户凭据、运行时回退账号

**Agent Publication**:
Agent 经过校验后形成的不可变运行版本，冻结模型、提示词、运行策略和 Agent 能力上限，供业务应用精确引用。
_Avoid_: Agent Draft、最新 Agent、应用运行时重新解析

**应用发布（Application Publication）**:
业务应用经过校验后形成的不可变运行版本，冻结其 Agent Publication、应用能力子集及全部解析后的执行依赖版本。
_Avoid_: 应用草稿、当前最新配置、动态别名

**钉钉应用访问（DingTalk Application Access）**:
钉钉消息命中绑定活动 Application Publication 的连接器，且实际发送人解析为已启用内部用户后获得的当前应用访问资格。
_Avoid_: 群级共享访问、应用角色白名单、未绑定外部主体

**用户能力可用状态（User Capability Availability）**:
当前内部用户在一次调用中满足应用访问、Agent 能力上限、应用能力子集、Release 运维状态、外部身份、默认 Team 和凭据交集后得到的个人可执行状态，不影响应用自身发布状态。
_Avoid_: 应用就绪、全局 Capability 状态、用户已绑定即有权限

**API 治理管理权限（Governed API Administration Permission）**:
控制管理员查看、编辑、测试、验证或发布 API Connection 和 API 能力配置的操作级 RBAC 权限，与业务用户运行时调用能力分开授权。
_Avoid_: 平台管理员全能开关、应用运行时访问权、用户凭据所有权

**Agent 能力上限（Agent Capability Envelope）**:
Agent Publication 显式配置并冻结的 Capability Release 集合，定义使用该 Agent 的应用最多可以选择哪些 API 能力。
_Avoid_: Agent 自动获得全部能力、应用能力子集、用户角色授权

**应用能力子集（Application Capability Allowlist）**:
Application Publication 从所选 Agent 能力上限中显式选择并冻结的 Capability Release 子集，是该应用运行时唯一可以暴露和执行的 API 能力集合。
_Avoid_: Capability 全局授权、Agent 全量能力、运行时动态添加

**凭据主体策略（Credential Subject Policy）**:
能力 Handler 用于确定外部 API 凭据所有者的显式规则，当前允许当前消息发送人或指定服务账号两类主体。
_Avoid_: 自动回退、会话共享凭据、任意用户

**ONES 默认 Team（ONES Default Team）**:
用户从 ONES 登录验证返回的已验证 Team 集合中选择的单一默认 Team，是其运行时 ONES 查询上下文。
_Avoid_: 应用配置的 Team、用户消息中的 team_uuid、自动跨 Team

**ONES 验证 Challenge（ONES Verification Challenge）**:
用户密码验证成功后由服务端创建的短时单次绑定流程，只向当前用户暴露安全的 User 和 Team 候选，不向浏览器返回 Token。
_Avoid_: 浏览器 Token、长期登录会话、可重复绑定凭证

**外部执行主体快照（External Execution Subject Snapshot）**:
Agent Job 创建时从当前用户绑定冻结的外部 User ID 和默认 Team ID，用于保证该 Job 后续所有外部调用的主体与范围不因绑定变更而漂移。
_Avoid_: 浮动默认 Team、执行时重新选择主体、冻结用户 Token

**操作语义（Operation Semantics）**:
API 能力对外部业务状态产生影响的分类，与 HTTP Method 无关；第一版只允许不改变业务状态的 `QUERY`。
_Avoid_: GET 等同只读、POST 等同写入、模型自行判断

**Handler 发布版本（Handler Revision）**:
能力 Handler 通过验证后形成的不可变执行版本，可被禁用或归档但不能原地修改。
_Avoid_: Handler Draft、可编辑发布记录、最新浮动配置

**能力发布（Capability Release）**:
一次原子发布形成的不可变事实，固定一个 API 能力版本及其 Handler、Connection 和认证配置版本。
_Avoid_: 浮动最新 Handler、独立半成品发布、应用临时解析

**能力发布运维状态（Capability Release Operational Status）**:
发布后独立于不可变配置内容的治理状态，允许 `ACTIVE`、`DEPRECATED`、`DISABLED` 或 `ARCHIVED`，用于控制新绑定、既有调用和历史可见性。
_Avoid_: Draft 生命周期、原地编辑发布内容、自动版本升级

**字段映射计划（Mapping Plan）**:
由受限类型化字段映射编译得到的不可变请求与响应投影，不支持通用表达式、脚本或 Secret 读取。
_Avoid_: 模板引擎、脚本、任意 JSON 转换

**Agent 能力组合（Agent Capability Composition）**:
Agent 根据用户消息、会话上下文和先前 Capability 的规范化输出，组织符合另一个 Capability Input Schema 的结构化参数并发起下一次独立调用。
_Avoid_: Handler 直连、服务端隐式流水线、原始响应透传、跳过逐次授权

**Capability 测试预览（Capability Test Preview）**:
管理员使用自己的外部身份测试 Draft 时看到的非持久化业务预览，完整展示 Method、相对路径、Query、映射后请求体和规范化输出，但其数据结构中根本不包含密码、Token、Cookie 或认证 Header。
_Avoid_: 原始外部响应、凭据掩码、测试证据、可重放请求

**外部调用尝试（External Call Attempt）**:
一次 Handler 对外部 API 的实际请求尝试，同一 Tool Call 可以因瞬时故障产生多个带统一关联标识的 Attempt。
_Avoid_: 新 Job、独立用户请求、无界重试

**规范化能力输出（Normalized Capability Output）**:
外部响应经过 Mapping Plan 投影并通过 API 能力 Output Schema 校验后的有界业务结果，是唯一可以提供给 Agent 和 Tool Call 记录的外部数据形态。
_Avoid_: 原始 HTTP 响应、完整 Provider Payload、认证响应

**能力数据分级（Capability Data Classification）**:
API 能力版本对其规范化输入输出声明的数据使用边界；`INTERNAL` 表示企业内部业务数据，可在授权的应用、Job、模型调用和后续同范围记忆中使用，但不是公开数据，也不表示定时删除。
_Avoid_: 发布状态、保留期限、日志脱敏开关、全局共享记忆

**ONES 工作项查询（ONES Work Item Search）**:
在当前用户的 ONES 默认 Team 内，按关键词和需求、任务或缺陷类型返回有界工作项摘要的只读 API 能力。
_Avoid_: 跨 Team 搜索、工作项详情、创建或修改工作项

## Relationships

- 一个 **内部用户**可以绑定多个不同 Provider 或系统实例的**外部身份绑定**
- 第一版只治理一个逻辑 ONES 实例，每个内部用户最多存在一个当前有效的 ONES 外部身份绑定；多 ONES 实例不属于本变更
- 一条钉钉消息先计算**钉钉应用访问**，再计算该应用允许的 **API 能力**可用状态
- 第一版**钉钉应用访问**只要求消息命中绑定活动应用发布的钉钉连接器，且实际发送人解析为已启用的内部用户
- 第一版不为钉钉应用另设用户白名单或应用访问角色；未绑定钉钉身份或内部用户已停用时拒绝访问
- 群聊中的**钉钉应用访问**和后续 Capability 可用性始终按每条消息的实际发送人计算，不存在群级共享主体
- 应用访问失败时只返回安全的中文绑定或联系管理员提示，不暴露用户、连接器或授权内部细节
- **外部身份绑定**与外部系统调用凭据是两个独立事实
- 一个启用的**外部身份绑定**对同一**认证配置**版本至多关联一个当前有效的**外部 API 凭据**
- **外部 API 凭据**失效后必须由用户重新验证，平台不得依靠持久化密码自动登录
- Connection 和 Handler 的真实 Verify/Test 使用当前**验证主体**自己的外部身份、默认 Team 和**外部 API 凭据**
- **验证主体**的 Token 只在验证调用中解析，绝不能进入发布版本、真实 Agent Job 或成为其他用户的回退凭据
- Handler 验证只保留状态、Schema 摘要、耗时、响应大小和脱敏错误，不保存完整外部响应
- **API Connection**通过**认证配置**完成用户身份验证、Token 提取和运行时认证 Header 注入
- 登录接口只允许身份与凭据服务调用，不得发布为 **API 能力**或暴露给 Agent
- **能力 Handler**只能声明凭据主体策略，不能读取 Token、修改认证 Header 或覆盖外部主体
- **应用发布**冻结**认证配置**版本，但不保存或冻结具体**外部 API 凭据**
- 每次调用按当前内部用户和被冻结的**认证配置**版本解析最新有效 Token
- 用户重新验证只轮换**外部 API 凭据**，不要求重新发布业务应用；认证配置变更则需要新版本和应用显式升级
- 个人**外部 API 凭据**只能由其所属内部用户在自己的认证会话中创建或轮换
- 管理员只能查看凭据元数据并禁用或解绑，不能查看 Token、代输密码或代替用户轮换
- 用户通过 `external_credentials.self_manage` 只能管理自己的绑定、重新验证和解绑，服务端必须校验目标用户等于当前主体
- 管理员治理其他用户凭据时只允许 `external_credentials.read`、`external_credentials.disable` 和 `external_credentials.unbind`，不得代为绑定或重新验证
- 现有“用户详情 → 外部身份”面板必须复用为本人模式和管理员模式，不建立第二套 ONES 绑定组件
- 本人模式允许当前用户绑定、重新验证、选择或切换默认 Team 以及解绑自己的 ONES 身份和凭据
- 管理员查看其他用户时只显示外部 User ID、默认 Team、凭据状态和验证时间，并只允许禁用或解绑；不得渲染 ONES 邮箱密码表单
- 普通用户通过独立“我的外部身份”入口访问同一面板的本人模式，不得因此获得人员列表、角色、会话或其他用户详情权限
- ONES 自助绑定和 Challenge 接口必须从认证会话取得当前用户 ID，不接受客户端指定目标 `user_id`
- 现有只有 ONES 外部身份绑定的用户保留原绑定，并显示凭据待验证；不得批量伪造 Token 或要求破坏性重绑
- API Connection 管理权限拆分为 `api_connections.read`、`api_connections.manage`、`api_connections.verify` 和 `api_connections.publish`
- API 能力配置管理权限拆分为 `api_capabilities.read`、`api_capabilities.manage`、`api_capabilities.test`、`api_capabilities.verify` 和 `api_capabilities.publish`
- `test` 只执行一次受控验证调用而不改变生命周期状态；`verify` 使当前 Draft 在验证成功后进入 `VERIFIED`
- Capability Test 允许管理员填写模拟 Agent 输入，并返回一次**Capability 测试预览**
- **Capability 测试预览**完整展示普通业务字段，不对关键词、工作项编号、名称、User ID 或 Team ID 做掩码
- 密码、Token、Cookie 和认证 Header 必须在构建测试预览前从预览模型中排除，不能先写入响应再依赖字符串脱敏
- 测试页只展示 Schema 过滤后的**规范化能力输出**，不得显示或保存外部 API 原始响应
- API 治理管理权限与既有 Agent、业务应用编辑发布权限必须分别判定，任一管理权限不得隐含授予运行时应用访问
- 管理员 Verify/Test 只能解析自己的 ONES 身份、默认 Team 和 Token，即使其拥有凭据治理权限也不得使用其他用户凭据
- 应用发布只验证 Capability、Handler、Connection、最近验证结果和治理授权，不枚举未来使用者或保存用户/Team ID
- `ACTIVE` 的 Capability Release 发布后进入 Agent 配置和业务应用配置的候选目录
- Agent 配置显式选择 Capability Release 并在 Agent Publication 中冻结为**Agent 能力上限**
- 同一 Agent Publication 对同一 Capability Code 最多选择一个精确的 `ACTIVE` Release
- Agent 配置默认推荐最新 `ACTIVE` Release，但允许管理员展开版本列表选择仍处于 `ACTIVE` 的较旧 Release
- `DEPRECATED` Release 只在既有引用中展示警告，不得用于新 Agent 配置
- 业务应用选择 Agent Publication 后，只能从该**Agent 能力上限**中配置自己的**应用能力子集**；后端必须拒绝越过 Agent 上限的选择
- 应用配置只勾选 Agent Publication 已冻结的精确 Capability Release，不提供独立版本选择器
- Agent 和应用的 Capability 选择界面必须展示名称、稳定 Code、业务 `description`、Release Revision 和运维状态，不能只显示机器编码
- 管理界面可以额外展示 `release_note`；模型 Tool 定义和运行时提示不得包含该管理备注
- 钉钉用户取得业务应用访问权后，即取得该应用能力子集的运行时调用资格，不再额外配置逐用户或逐角色 Capability Code `use` 权限
- 应用没有配置的 Capability、或所选 Agent Publication 没有配置的 Capability，均不得暴露或执行
- **应用发布**同时冻结所选 Agent Publication 和**应用能力子集**中的精确 Capability Release
- Agent 新增、移除或升级 Capability 时必须创建新的**Agent Publication**；既有应用发布不得自动解析新 Agent 版本
- 应用升级 Agent 时必须显式选择新的 Agent Publication，并重新校验原应用能力子集是否仍属于新的 Agent 能力上限
- 新 Agent 缺失原 Capability、只提供 `DEPRECATED` Release 或公开 Schema 不兼容时，应用发布必须被阻止并要求管理员明确替换或移除
- Agent 升级不得静默删除应用能力、自动选择替代 Release 或改写既有应用发布
- **用户能力可用状态**由当前用户的应用访问权、Agent 能力上限、应用能力子集、Release 运维状态、外部身份、默认 Team 和有效 Token 共同决定
- 任一用户的**用户能力可用状态**失败只阻止该用户调用，不改变应用发布或其他用户的状态
- 模型 Tool 暴露前必须计算**用户能力可用状态**，不可用的 API 能力不进入本次 Tool 列表
- 不可用能力可以向模型提供安全原因和中文操作提示，但不得暴露身份、Token 或授权细节
- Handler 执行前必须再次计算**用户能力可用状态**，不得依赖会话或模型暴露阶段的旧结果
- **API 能力**通过已发布的**能力 Handler**执行
- **API 能力**拥有 Agent 可见的公开输入、输出和业务语义 Schema
- Capability Code 是稳定业务标识，不包含 `v1`、`v2` 等版本后缀，也不得被复用于不同业务含义
- API Capability Revision 必须包含 `description`，说明业务用途、适用场景和返回内容；该字段同时展示在 Agent、应用配置并作为模型 Tool 描述
- Capability Release 可以包含仅管理端可见的可选 `release_note`，用于说明本次修改、替代关系和运维注意事项，不得进入模型上下文
- API Capability Input Schema 允许管理员配置字段名称、类型、说明、必填性、枚举、默认值以及字符串、数值、对象和数组边界
- Agent 每次调用只能提交 Input Schema 声明的字段，未知字段、类型不匹配和越界值必须在 Handler 执行前拒绝
- **能力 Handler**必须证明其字段映射计划能够实现所绑定 **API 能力**版本的公开 Schema
- 每次 Publish 都为同一 Capability Code 创建单调递增的 Release Revision
- 外部路径、固定 Query 或字段映射变化但公开业务契约不变时，复用 Capability Revision 并创建新 Handler Revision 和 Capability Release
- 公开 Input 或 Output Schema 变化时，在同一稳定 Capability Code 下创建新 Capability Revision 和 Capability Release，既有应用仍冻结旧 Revision
- 业务含义变化时必须创建新的 Capability Code；不得把查询能力原地改成写入能力或其他不同业务操作
- 管理员只编辑一个 **API 能力配置**并执行一次验证和发布，不需要单独创建或绑定 Handler
- **API 能力配置**工作台固定包含能力定义、Agent 输入字段、Agent 输出字段、Handler 映射和测试预览五个区域
- 能力定义维护名称、Capability Code、说明、操作语义和数据分级；输入输出区域维护 Agent 可见的公开 Schema
- Handler 映射区域维护已发布 Connection、Method、相对路径、固定 Query Document 以及请求响应字段投影
- 测试预览使用模拟 Agent 输入和当前管理员自己的外部身份执行 Draft；工作台只提供一次 Verify 和一次原子 Publish 操作
- 平台在内部为 **API 能力配置**分别维护业务契约和 Handler 版本，并原子创建**能力发布**
- 业务应用最终冻结**能力发布**，不得在运行时重新解析最新 Handler 或 Connection
- 新创建的**能力发布**初始为 `ACTIVE`，可供业务应用选择并支持既有应用调用
- `DEPRECATED` 是软废弃：既有应用发布继续执行，但新应用绑定和应用升级不能再选择该 Release
- 软废弃允许记录原因和可选 `replacement_release_id`，但不会按日期自动禁用、自动升级或修改任何既有应用
- `DISABLED` 用于紧急阻断，该 Release 的所有新调用立即失败关闭
- `ARCHIVED` 只保留历史记录且不进入日常选择列表，应在没有活动应用继续依赖后使用
- 废弃、禁用和归档只改变**能力发布运维状态**，不得修改被冻结的 Capability、Handler、Connection 或认证配置内容
- **能力 Handler**必须声明**凭据主体策略**，运行时不得自动改用其他主体
- `CURRENT_ACTOR` 在私聊和群聊中都表示当前消息发送人；群会话不得共享任一成员的**外部 API 凭据**
- ONES 查询第一版只允许 `CURRENT_ACTOR`，缺失或失效凭据时失败关闭，不回退平台服务账号
- ONES 登录验证绑定外部 User ID、已验证 Team 集合和一个**ONES 默认 Team**；存在多个 Team 时用户必须选择一个默认值
- ONES 绑定界面不提供实例选择器；所有 ONES API 能力复用同一个逻辑 ONES Connection 的发布版本
- ONES 绑定先创建**ONES 验证 Challenge**，再由当前用户选择 Challenge 返回集合中的默认 Team
- **ONES 验证 Challenge**必须绑定当前内部用户和 Connection Revision，短时有效且只能成功消费一次
- 密码在 Challenge 创建后立即丢弃，Token 不返回浏览器；确认前不得修改原身份或凭据
- 确认时原子保存外部 User ID、已验证 Team、默认 Team 和加密 Token
- 用户更换默认 Team 必须重新完成 ONES 密码验证并创建新**ONES 验证 Challenge**，不得直接从历史 Team 集合切换
- 更换确认时必须使用 ONES 当前返回的 Team 集合，原子刷新已验证 Team、默认 Team 和加密 Token
- Agent Job 创建时冻结当前外部 User ID 和默认 Team ID 形成**外部执行主体快照**；默认 Team 变更只影响之后创建的 Job
- 已创建 Job 的**外部执行主体快照**不得因用户重绑或切换默认 Team 而变化，也不得自动切换到新主体或新默认 Team
- 每次外部调用前必须确认快照 User ID 仍等于当前启用绑定主体、快照 Team 仍属于最新验证 Team 集合且当前个人 Token 有效
- 用户解绑、换绑 ONES 账号、失去快照 Team 或凭据失效时，旧 Job 失败关闭，不得使用新主体或其他 Team 继续
- 只轮换 Token 且快照 User ID 与 Team 仍有效时，旧 Job 可以按被冻结的认证配置解析新 Token 继续执行
- API 能力、Handler 和业务应用配置不得保存 ONES User ID 或 Team ID
- 运行时从当前发送人的外部身份绑定读取 ONES User ID 和**ONES 默认 Team**并安全注入请求
- 消息、Agent 参数和**能力 Handler**输入不得提供或替换 ONES User ID 或 `team_uuid`
- **能力 Handler**必须声明**操作语义**；第一版只允许 `QUERY`
- `QUERY` 可以使用 HTTP POST，但 GraphQL Document 必须由 Handler 版本固定且不得包含 `mutation`
- Agent 只能提供 Input Schema 允许的变量，不能提供原始 GraphQL、任意请求体或响应字段
- Agent 可以通过**Agent 能力组合**使用前一个 Capability 的**规范化能力输出**组织后续 Capability 输入，但平台不自动在 Handler 之间传递数据
- 每个组合调用必须独立重新校验 Agent 能力上限、应用能力子集、用户能力可用状态、应用访问、外部身份和凭据，不得继承上一次调用的结果
- 外部 API 输出即使通过 Schema 规范化，仍必须作为不可信业务数据进入模型上下文，不能解释为系统、开发者或 Tool 指令
- ONES User ID、默认 Team、Token 和其他系统上下文字段不得出现在 Agent 可写 Input Schema 中，也不得由前一个 Capability 输出覆盖
- **能力 Handler**使用**字段映射计划**在 Capability 输入、系统上下文、外部请求和 Capability 输出之间投影字段
- **字段映射计划**只能读取声明的输入、常量和系统上下文，不能读取 Token、Secret、环境变量或动态主机
- **字段映射计划**必须通过字段存在性、类型、系统字段所有权、数组数量、字符串长度和响应大小校验
- `401` 使当前**外部 API 凭据**失效且不重试；`403` 表示外部授权不足但不自动使 Token 失效
- `400`、`404`、响应过大、JSON 无效和 Schema 不匹配不重试
- `QUERY` 遇到网络错误、超时、`429`、`502`、`503` 或 `504` 时最多进行两次退避重试
- 同一 Tool Call 的所有**外部调用尝试**共享 Job、Tool Call 和 Correlation 标识，并分别记录脱敏结果
- 原始外部响应只在当前 Attempt 内存中存在，映射完成后丢弃，不得进入数据库、日志、审计、错误或模型上下文
- 只有**规范化能力输出**可以提供给 Agent，并在数组、字段和总大小限制内正常写入 Tool Call 结果；Agent 最终回复按现有 Job 和会话模型正常保存
- Audit 只保存版本、主体、Team、状态、耗时、结果数量和摘要 Hash，不保存原始请求响应或认证数据
- API 能力版本必须声明**能力数据分级**，能力发布冻结该分级；`ones.work_item.search` 第一版固定为 `INTERNAL`
- `INTERNAL` 规范化输出只能由具备对应业务应用和 Job 访问权的主体访问，不得复制到日志、审计或公共导出
- 本变更不对规范化结果或最终回复执行定时清理，现有 `session_policy.retention_days` 继续明确为仅保存、未执行
- 后续记忆系统若摄取 `INTERNAL` 输出或最终回复，必须继承用户、业务应用、Capability 和数据分级来源边界；记忆摄取本身不属于本变更
- 第一版通用框架只以 `ones.work_item.search` 实现**ONES 工作项查询**真实验收
- **ONES 工作项查询**输入仅包含关键词、工作项类型和有界数量，输出仅包含编号、名称、类型、总数和截断状态
- 第一版通过测试专用的两个 Capability Fixture 验证“API A 规范化输出 → Agent 组织参数 → API B 输入”的组合链路，不新增第二个生产 ONES Capability
- 能力 Handler 遵循 `DRAFT → VERIFIED → PUBLISHED`，任何 Draft 变更都会使旧验证结果失效
- 只有最新 Draft 验证通过后才能创建**Handler 发布版本**
- **Handler 发布版本**不可修改或普通删除；被禁用后所有新调用失败关闭，被归档后不再供新绑定选择
- Agent 和业务应用只引用 **API 能力**，不得直接选择**能力 Handler**或 **API Connection**
- Agent Publication 先冻结**Agent 能力上限**，Application Publication 再冻结其中显式选择的**应用能力子集**
- 一个已发布 **API 能力**版本解析到一个确定的**能力 Handler**版本
- 一个**能力 Handler**绑定一个已发布的 **API Connection**版本，只保存受限 Method、相对路径和请求/响应映射
- **能力 Handler**不得保存完整 URL、任意代码、脚本或直接引用 Secret
- **API Connection**是平台级共享治理资源，多个 API 能力可以引用同一已发布 Connection 版本
- API 能力配置只能选择已发布 **API Connection**版本，不能内联修改地址、认证 Header 或 Secret
- 新 Connection 版本不会自动改变能力发布或应用发布；依赖方必须重新验证并显式发布升级
- API Connection 遵循 `DRAFT → VERIFIED → PUBLISHED`，任何 Draft 变更都会使旧验证结果失效
- 只有固定 Origin、认证配置和当前**验证主体**的受控测试通过后才能创建**Connection 发布版本**
- 首个 ONES Connection 因尚无可绑定发布版本而无法解析正式用户凭据时，必须使用**Connection 启动验证**解除启动循环
- **Connection 启动验证**只允许拥有 `api_connections.verify` 的当前管理员输入自己的 ONES 邮箱和密码，并验证 Draft Origin、登录、User/Team/Token 提取及认证 Header 注入
- 启动验证中的密码和 Token 只能存在于该验证请求内，响应结束后必须丢弃；不得建立外部身份绑定、持久化凭据或成为发布内容
- 首个 Connection 发布后，管理员必须通过正式两阶段绑定流程建立自己的外部身份、默认 Team 和加密 Token，之后才能 Test、Verify 或 Publish API Capability
- **Connection 发布版本**不可修改或普通删除；被禁用后所有依赖它的新调用失败关闭
- Origin 或认证配置变化产生新**Connection 发布版本**，旧用户 Token 不得跨不兼容版本复用
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
- “修改 Agent 的 Capability”曾可能自动改变所有使用它的应用；已解决为 Agent 与应用分别发布并冻结版本，应用显式升级且重新校验能力子集。
- “Agent 与应用各自选择 Capability 版本”曾可能产生版本不一致；已解决为 Agent 冻结精确 Release，应用只选择其子集且同时展示业务描述。
- “Capability 备注描述”曾可能把版本运维说明一并发送给模型；已解决为业务 `description` 模型可见，`release_note` 仅管理端可见。
- “废弃 Capability”曾可能等同立即停用或删除；已解决为软废弃只阻止新选择，既有应用继续运行，紧急阻断必须显式禁用。
- “群聊调用 ONES”曾可能被理解为共享会话凭据；已解决为每条消息按当前发送人独立解析凭据，且不得回退共享账号。
- “钉钉用户访问应用”曾可能需要额外应用白名单或角色；第一版已解决为路由命中活动应用且发送人映射为启用内部用户即可访问。
- “查询用户的 ONES”曾先被解决为应用固定 Team；该决定已被取代，现在使用当前用户绑定的 ONES User ID 和默认 Team，且不自动跨 Team。
- “只读 Handler”曾被理解为只允许 HTTP GET；已解决为按业务操作语义判断，允许固定只读 GraphQL 的 POST，但禁止 mutation 和原始查询输入。
- “修改已发布 Handler”曾被理解为直接编辑当前配置；已解决为发布版本不可变，任何调整都从新 Draft 开始并重新验证发布。
- “测试 Handler”曾考虑使用 Connection 独立验证凭据；已解决为当前授权管理员使用自己的 ONES 身份和 Token，且该 Token 不进入发布或其他用户运行时。
- “ONES 登录 API”曾可能被当作 Agent 可调用能力；已解决为 Connection Authentication Profile 的内部认证协议，永不进入 Capability Catalog。
- “应用发布冻结凭据”曾可能被理解为把 Token 写入发布快照；已解决为只冻结认证协议版本，运行时读取当前用户最新有效 Token。
- “应用能否使用 ONES”曾被理解为一个全局布尔状态；已解决为应用发布就绪与每个当前用户的能力可用状态分别计算。
- “管理员绑定 ONES”曾可能表示管理员代输普通用户密码并持有 Token；已解决为个人凭据只能本人自助创建和轮换，管理员只治理状态。
- “管理员不能操作其他用户凭据”曾可能同时禁止泄露处置；已解决为管理员可查看元数据、禁用或解绑，但不能查看 Token、绑定、代输密码或重新验证。
- “新增我的外部身份”曾可能表示重做一套绑定页面；已解决为复用现有外部身份面板，仅按当前主体与目标用户切换本人或管理员模式。
- “拥有 API 配置权限”曾可能自动允许业务调用；已解决为治理管理权限只控制配置，运行时调用资格来自 Agent 能力上限、应用能力子集和用户应用访问权。
- “Capability 还要按用户或角色单独授权”曾造成重复配置；已解决为不设独立 Capability Code `use` Grant，用户访问应用即获得该应用已选能力的调用资格。
- “输入 ONES 密码后选择 Team”曾可能要求把 Token 暂存到浏览器；已解决为服务端短时单次 Challenge 返回安全候选，确认后原子绑定。
- “切换默认 Team”曾可能表示从历史 Team 列表直接改值并影响正在执行的任务；已解决为重新验证后从当前 Team 集合选择，且只影响之后创建的 Job。
- “Job 冻结外部主体”曾可能允许已撤销权限继续执行；已解决为快照防止身份漂移，但每次调用仍实时校验主体、Team 成员资格和当前 Token。
- “不可用 Capability”曾可能仍暴露给模型并等待调用失败；已解决为暴露前隐藏并提供安全提示，执行前仍再次失败关闭检查。
- “请求/响应映射”曾可能表示管理员可编写任意模板或表达式；已解决为只支持可静态验证的类型化字段投影。
- “测试预览不脱敏”曾可能包含认证材料或原始响应；已解决为普通业务字段完整显示，但凭据字段从预览模型中直接排除，外部原始响应仍不展示。
- “一个 API 的结果作为另一个 API 输入”曾可能表示 Handler 自动直连或透传原始响应；已解决为 Agent 只使用规范化输出组织下一个公开 Input Schema，并对每次调用独立授权。
- “Handler Schema”曾可能同时表示 Agent 业务契约和外部接口结构；已解决为公开业务 Schema 属于 API 能力，Handler 只负责实现和验证该契约。
- “Capability 版本”曾可能通过修改 Code 中的 `v1`、`v2` 表示；已解决为 Code 稳定、Release Revision 递增，并按实现、Schema 或业务语义变化选择不同版本路径。
- “Capability 与 Handler 分离”曾可能表示管理员需要维护两个对象；已解决为产品上一体化 API 能力配置和一次发布，平台内部保留职责与版本分离。
- “API 能力配置页面”曾可能继续拆成独立 Schema、Handler 和测试页面；已解决为五区单工作台，并通过一次验证和原子发布形成 Capability Release。
- “配置 ONES API”曾可能在每个 Capability 中重复填写 Base URL 和认证；已解决为共享 API Connection 独立治理，Capability 只引用发布版本。
- “多个 ONES 实例”曾引出按实例维护多份用户凭据；第一版明确不处理，每个用户只有一个 ONES 账号绑定，但仍可从多个 Team 中选择一个默认值。
- “暂不做网络限制”曾可能表示允许 Handler 请求任意 URL；已解决为延期完整 Network Zone，但仍固定 Connection Origin、限制相对路径并禁止 Token 跨 Origin。
- “修改 ONES Connection”曾可能表示直接覆盖当前地址或认证；已解决为 Connection 发布版本不可变，任何调整都从新 Draft 验证发布。
- “首个 Connection 使用管理员已绑定凭据验证”形成了未发布就不能绑定、未绑定就不能验证的循环；已解决为一次不落盘密码和 Token 的启动验证，发布后再走正式绑定。
- “ONES 调用失败”曾被当作统一可重试错误；已解决为按认证、授权、输入、契约和瞬时故障分类，只有只读查询的瞬时故障有限重试。
- “保存 Tool 调用结果”曾可能表示落盘整个外部响应；已解决为原始响应永不持久化，只有 Schema 允许的有界规范化输出可以保存。
- “INTERNAL”曾可能被理解为自动过期或禁止保存；已解决为它只定义内部访问与后续记忆继承边界，规范化结果和最终回复正常保存且不定时清理。
- “第一版查询 ONES”曾可能包含多个工作项能力；已解决为通用框架只用 `ones.work_item.search` 完成单 Team 只读端到端验收。
