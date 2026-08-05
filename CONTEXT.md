# Enterprise Agent Control Plane

本上下文描述业务应用如何组合 Agent、内置只读工具、外部身份和受治理 API 能力，并在消息发送者的权限范围内访问内部数据与外部业务系统。

## Language

**内部用户（Internal User）**:
平台中承载角色、业务应用权限和数据范围的人员主体。
_Avoid_: 钉钉用户、ONES 用户、账号

**外部身份绑定（External Identity Binding）**:
内部用户与受信外部系统实例中一个已验证账号的关联，只证明主体对应关系，不保存可重复使用的登录凭据，也不自动授予权限。
_Avoid_: 外部凭据、Token 绑定、外部授权

**钉钉昵称（DingTalk Display Name）**:
钉钉外部身份最近一次受信消息携带的非空发送者昵称，用于识别外部主体但不等同于平台人员姓名。
_Avoid_: 人员姓名、平台显示名称、管理员备注

**外部身份本人模式（External Identity Self Mode）**:
当前认证主体管理自己外部身份和个人凭据的自助边界。
_Avoid_: 管理员模式、代用户绑定、人员详情编辑

**外部身份治理模式（External Identity Governance Mode）**:
授权管理员从人员管理入口查看并处置用户外部身份和凭据状态的治理边界，包括管理员自己的人员记录。
_Avoid_: 本人模式、代输密码、代用户重新验证

**API 能力（API Capability）**:
向业务应用和 Agent 发布的版本化业务操作及其公开输入输出契约，不暴露底层接口地址、认证信息或传输细节。
_Avoid_: Tool、Endpoint、API Handler

**内置只读工具（Built-in Read-only Tool）**:
由平台代码注册并以不可变 Handler 版本发布的内部诊断操作，管理员只能治理其版本、资源绑定、Agent 分配和访问权限，不能在 Web 中定义可执行实现。
_Avoid_: API 能力、动态 HTTP 工具、MCP 配置、SQL 模板、脚本

**内置工具发布（Built-in Tool Release）**:
将一个精确的内置只读工具 Handler 版本纳入运行治理的不可变事实，其内容不变但运维状态可以在 `ACTIVE`、`DEPRECATED`、`DISABLED` 和 `ARCHIVED` 之间按规则推进。
_Avoid_: 可编辑工具定义、浮动最新版本、全局工具开关

**内置工具安装状态（Built-in Tool Installation Status）**:
部署对账代码 Manifest 与安装目录后得到的 `INSTALLED`、`MISSING` 或 `DRIFTED` 事实，只表示代码可用性，不表示该版本已经发布给 Agent 使用。
_Avoid_: 内置工具发布状态、Agent 分配、运行时授权

**内置工具验证证据（Built-in Tool Verification Evidence）**:
由固定验证器生成并绑定精确 Handler Version、Implementation Digest 与 Verifier Version 的机器验证结果，证明 Manifest、Schema、资源槽、只读边界、风险权限和契约兼容性满足发布要求。
_Avoid_: 管理员勾选确认、工具资源连通性结果、未绑定 Digest 的测试报告

**内置工具目录（Built-in Tool Catalog）**:
汇总代码安装状态、内置工具发布、Schema、风险、资源槽、引用影响和运行健康的全局治理目录，不承担 Agent、应用或角色配置。
_Avoid_: Agent 工具上限、应用工具子集、工具资源目录

**工具资源（Tool Resource）**:
供内置只读工具访问数据库、Redis 或 Loki 等目标的受治理资源身份，其连接内容通过验证后形成不可变发布版本。
_Avoid_: 内置只读工具、Agent 配置、明文连接凭据

**应用工具资源绑定（Application Tool Resource Binding）**:
Application Publication 将一个内置工具发布声明的逻辑资源槽绑定到精确工具资源发布版本及有界执行约束的不可变关系。
_Avoid_: Agent 资源绑定、工具全局默认实例、浮动最新资源

**内置工具使用权限（Built-in Tool Use Grant）**:
允许内部用户通过角色或直接策略调用一个稳定内置工具标识的运行时授权事实，独立于业务应用访问、工具治理管理权限和数据范围授权。
_Avoid_: 应用访问权、工具资源管理权限、Agent 工具分配

**内置工具治理管理权限（Built-in Tool Governance Permission）**:
控制管理员查看、对账、发布或变更内置工具发布生命周期的操作级 RBAC 权限，与工具资源管理和运行时工具使用授权分开。
_Avoid_: 工具资源管理权限、内置工具使用权限、平台配置全能开关

**Capability 标识（Capability Identifier）**:
同时作为业务标识、模型 Tool 名、Agent/Application 引用和审计键的稳定名称，使用保留的 `cap__` 命名空间，例如 `cap__ones__work_item__search`。
_Avoid_: 点号 Code、运行时名称转换、内部 Tool 名、版本后缀

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

**明文 HTTP 授权（Plain HTTP Opt-in）**:
管理员针对一个固定 API Connection Origin 显式接受无 TLS 传输风险的发布事实；HTTPS 是默认值，HTTP 未授权时失败关闭，授权后仍不代表网络区或 SSRF 防护。
_Avoid_: 本地 Mock 开关、关闭证书校验、全局 HTTP 开关、安全连接

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
Agent 经过校验后形成的不可变运行版本，冻结模型、提示词、运行策略、精确内置工具发布和 API 能力上限，供业务应用精确引用。
_Avoid_: Agent Draft、最新 Agent、应用运行时重新解析

**应用发布（Application Publication）**:
业务应用经过校验后形成的不可变运行版本，冻结其 Agent Publication、应用内置工具子集、API 能力子集及全部解析后的执行依赖版本。
_Avoid_: 应用草稿、当前最新配置、动态别名

**应用内置工具子集（Application Built-in Tool Allowlist）**:
Application Publication 从所选 Agent Publication 的精确内置工具上限中显式选择并冻结的子集，是该应用能够暴露内置工具的最大范围。
_Avoid_: 自动继承 Agent 全部工具、应用另选工具版本、运行时动态添加

**钉钉应用访问（DingTalk Application Access）**:
钉钉消息命中绑定活动 Application Publication 的连接器，且实际发送人解析为已启用内部用户后获得的当前应用访问资格。
_Avoid_: 群级共享访问、应用角色白名单、未绑定外部主体

**钉钉应用连接（DingTalk Application Connection）**:
平台为一个钉钉应用维护的受信消息连接，负责接入和投递但不构成人员外部身份。
_Avoid_: 钉钉身份、用户应用绑定、钉钉用户账号

**钉钉企业（DingTalk Enterprise）**:
以钉钉 Corp ID 为稳定标识并承载管理员维护企业名称的钉钉身份命名空间，由一个或多个钉钉应用连接共同引用。
_Avoid_: 钉钉应用、连接器、自由填写的租户字符串

**钉钉企业生命周期（DingTalk Enterprise Lifecycle）**:
钉钉企业在接入、运行、停用和历史保留过程中的治理状态，只允许 `PENDING_VERIFICATION`、`ACTIVE`、`DISABLED` 和 `ARCHIVED`。
_Avoid_: 仅以连接心跳表示企业可用、删除企业记录、跳过 Corp ID 复核直接恢复

**钉钉应用观察记录（DingTalk Application Observation）**:
某个钉钉身份通过某个钉钉应用连接出现过的首次和最近受信时间证据，不表示用户绑定应用或获得应用授权。
_Avoid_: 用户应用绑定、应用授权、身份归属

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
能力 Handler 用于确定外部 API 凭据所有者的显式规则；第一版只允许当前消息发送人的 `CURRENT_ACTOR`，指定服务账号策略延期。
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

- **内置只读工具**与 **API 能力**是两类独立的模型 Tool 来源；内部诊断操作使用代码注册表，管理员配置的外部业务接口必须通过受治理 **API 能力**发布
- Web 管理端不得创建或修改**内置只读工具**的 HTTP、MCP、SQL、脚本或其他可执行实现，只能治理代码已安装版本的发布状态、资源绑定、Agent 分配和访问权限
- `ACTIVE` **内置工具发布**允许新 Agent 选择和运行；`DEPRECATED` 允许既有 Agent Publication 继续运行但禁止新选择，并应说明废弃原因和替代版本
- `DISABLED` **内置工具发布**用于紧急阻断，状态变更后的新 Tool 调用必须立即失败关闭；`ARCHIVED` 只保留历史，且只能在没有活动依赖后进入
- 部署过程必须根据代码 Manifest 自动、幂等地对账**内置工具安装状态**并记录审计，但不得因此自动创建或激活**内置工具发布**
- 只有安装状态为 `INSTALLED`、Implementation Digest 一致且最新**内置工具验证证据**为 `VERIFIED` 的精确版本才能由管理员人工发布；`MISSING`、`DRIFTED` 或未验证版本必须禁止发布和执行
- **内置工具验证证据**必须覆盖 Manifest、输入输出 Schema、资源槽、只读与副作用边界、结果大小、风险权限、契约测试及版本兼容性；Digest 变化必须立即使旧证据失效
- 工具资源连通性和具体实例预检分别属于工具资源发布与 Application Publication，不得以全局工具验证偷偷绑定或调用生产资源
- 发现新的已安装版本不得改变既有工具发布、Agent Publication 或 Application Publication，也不得自动进入 Agent 选择目录
- **内置工具目录**负责全局安装与发布生命周期；工具资源治理、Agent 工具上限、应用工具子集与资源绑定、角色工具使用权限分别由各自上下文管理，不得合并为同一份可编辑工具配置
- **内置工具治理管理权限**拆分为 `builtin_tools.read`、`builtin_tools.reconcile`、`builtin_tools.verify`、`builtin_tools.publish` 和 `builtin_tools.lifecycle`；自动部署对账使用受审计的系统身份，不获得其他管理权限
- `builtin_tools.verify` 只允许触发或重试代码注册的固定验证计划，管理员不得提交命令、URL、SQL、脚本或手工把结果标记为通过
- **内置工具验证证据**必须保存证据 Hash、构建标识、Verifier Version、触发主体、时间和脱敏失败原因；验证结果由机器判定且不可人工覆盖，`builtin_tools.publish` 不能绕过失败或失效证据
- `builtin_tools.*` 不得授予工具资源连接管理或运行时调用资格；工具资源使用独立的 `tool_resources.*` 权限，运行时继续使用稳定工具标识上的**内置工具使用权限**
- 一个 **Agent Publication**对同一内置工具标识最多冻结一个精确的**内置工具发布**，并保存 Tool Release ID、Handler Version 和 Implementation Digest；发布后不得自动解析或升级到其他版本
- Job 重试继续引用原 **Agent Publication**冻结的精确内置工具版本，但每次 Tool 调用仍须检查该**内置工具发布**的实时运维状态，不能以发布快照绕过 `DISABLED` 或 `ARCHIVED`
- **应用发布**必须显式冻结**应用内置工具子集**，不得自动继承所选 Agent 的全部工具，也不得选择 Agent Publication 未包含的工具或其他版本
- 新 Agent Publication 不改变既有**应用发布**；应用显式升级 Agent 时必须重新校验原内置工具子集，缺失、`DEPRECATED` 或不兼容版本必须要求管理员明确替换或移除
- **内置工具发布**只声明逻辑资源槽及允许的资源类型，不绑定具体数据库、Redis 或 Loki 实例；**工具资源**在平台治理中独立创建、验证和发布
- **应用发布**通过**应用工具资源绑定**为已选内置工具的每个必需资源槽冻结精确工具资源版本和约束；Agent Publication 不保存具体资源实例
- 新工具资源版本不自动替换既有**应用工具资源绑定**；应用必须显式创建新发布版本，运行时再与当前用户角色和环境、基地、车间数据范围取交集
- 内部用户调用内置工具必须同时具备目标业务应用访问和对应**内置工具使用权限**；任一条件缺失时 Tool 不得暴露或执行
- **内置工具使用权限**不能扩大 Agent Publication、应用内置工具子集、工具发布运维状态、工具资源状态或环境、基地、车间数据范围，任何一层拒绝都必须失败关闭
- **内置工具使用权限**绑定稳定工具标识而不是精确发布版本；精确版本只能由 Agent Publication 和 Application Publication 的发布链确定
- 同一稳定工具标识下的新版本不得扩大副作用、资源类型或授权边界；需要扩大安全能力时必须创建新的工具标识，使既有角色不会自动获得该能力
- 一个 **内部用户**可以绑定多个不同 Provider 或系统实例的**外部身份绑定**
- 一个**内部用户**可以在不同钉钉企业中绑定多个钉钉外部身份；同一企业中的同一外部主体只形成一个身份，不因存在多个**钉钉应用连接**而重复
- 每个“内部用户 + 钉钉企业”最多一个当前有效钉钉身份；同企业出现不同外部主体时必须显式换绑并将旧身份保留为历史，不得静默形成两个有效账号
- 停用或解绑钉钉身份对该身份所属企业的全部钉钉应用连接生效；应用级用户限制属于独立的应用访问策略，不得通过拆分或修改身份绑定实现
- 一个钉钉外部身份可以通过同一企业的多个**钉钉应用连接**被识别，身份不归属于其中某一个应用连接
- 钉钉外部身份与**钉钉应用连接**之间通过**钉钉应用观察记录**形成多对多关系，该记录只用于来源说明和排障
- **钉钉应用观察记录**随身份历史长期保存且按“身份 + 应用连接”幂等更新，只保留首次/最近观察时间，不复制消息正文、原始事件或认证材料
- 每个**钉钉应用连接**属于且只属于一个**钉钉企业**；同一企业的应用必须引用同一企业记录，不得分别填写可能漂移的企业标识
- **钉钉应用连接**必须通过连接验证或受信消息确认其 Corp ID 与所选**钉钉企业**一致；不一致时拒绝消息并产生治理告警
- 首个**钉钉应用连接**可以在企业 Corp ID 未知时进入“已连接，等待企业验证”，但验证消息只能形成安全证据，不得创建业务 Job、绑定人员身份或授予应用访问
- 首次企业验证必须从同一条受信测试消息取得且校验非空 `senderCorpId` 与 `chatbotCorpId`；验证成功后固化 Corp ID，后续应用连接只能加入同一 Corp ID 的企业
- **钉钉企业**验证成功后 Corp ID 不允许直接编辑；发现归属错误时必须停用原企业并重新接入，不能通过修改 Corp ID 将既有身份整体迁往另一企业
- **钉钉企业**名称允许管理员修改，修改结果必须统一反映在人员详情、本人外部身份和钉钉应用配置中，并审计记录修改人、修改时间及修改前后名称
- **钉钉企业生命周期**必须遵循：`PENDING_VERIFICATION` 不处理业务消息、身份绑定或应用访问；`ACTIVE` 才允许正常解析；`DISABLED` 停止该企业全部应用接入和身份解析但保留数据；`ARCHIVED` 只读保留历史且只允许在全部应用停用后进入，不得物理删除
- `DISABLED` 或 `ARCHIVED` 的钉钉企业重新启用时，不能只切换数据库状态；其应用连接必须重新建立并再次验证真实 Corp ID 后才能回到 `ACTIVE`
- 当前旧钉钉身份、`default` 企业占位标识和单一 `connector_id` 关系均视为可丢弃测试数据；新模型上线前允许清空后重建，不实施旧身份数据回填、兼容读取或旧字段双写
- 清空后钉钉企业必须通过首个应用连接的受信测试消息重新验证 Corp ID，钉钉身份必须从已验证应用产生的受信候选重新绑定，不得把旧占位值带入新模型
- 本次测试数据清理范围包含钉钉应用连接及其密钥、Stream 运行状态与租约、钉钉接入事件与 Outbox、未绑定身份候选及候选消息、钉钉外部身份、昵称审计、应用观察记录，以及业务应用对被删除钉钉连接的渠道绑定
- 本次测试数据清理不得删除平台人员、角色、登录会话、ONES 身份与个人凭据、API Capability、Agent、业务应用主体、任何 Agent Job、Tool 调用结果或投递记录，以及与钉钉无关的渠道或配置；已清理的连接在既有运行记录中只作为不可用历史来源展示
- 清理完成后管理员必须重新创建**钉钉企业**和**钉钉应用连接**、重新录入 Client ID 与 Client Secret、发送测试消息验证 Corp ID，并从新的受信候选重新绑定人员
- 钉钉测试数据清理必须由独立的一次性重建命令完成，不得写入常规数据库迁移或暴露为长期管理页面；生产环境必须永久拒绝该命令
- 重建命令必须先执行只读预检，报告目标数据库与环境、各类待删除记录数量、受影响的应用渠道绑定及明确保留的数据范围；只有用户随后提供固定确认文字且执行命令携带显式确认参数时才能继续
- 清理执行必须处于事务中，并在环境、预检快照或记录数量发生变化时拒绝执行；失败时整体回滚，成功后输出实际删除数量和保留数据复核结果
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
- 独立“我的外部身份”入口必须进入**外部身份本人模式**，并只调用从认证会话解析当前主体的自助 API
- “人员管理 → 用户详情”入口必须在具备相应治理权限后进入**外部身份治理模式**，即使管理员查看自己的人员记录也不得自动切换为本人模式
- 本人模式允许当前用户绑定、重新验证、选择或切换默认 Team 以及解绑自己的 ONES 身份和凭据
- ONES 身份卡将登录验证接口返回的用户 `name` 定义为**ONES 用户名称**，每次本人重新验证成功后刷新；管理员不得手工改写，缺失时显示“ONES 未返回用户名称”，不得使用平台人员姓名作为替代
- ONES 登录邮箱和密码不作为身份展示字段保存；密码始终不得持久化，身份卡不得展示或暗示平台保存了登录邮箱或密码
- ONES 每次验证成功后必须在身份上保存本次已验证 Team 候选的 Team ID 和 Team 名称，并以最新候选整体替换旧候选；已不再返回的 Team 不得继续作为可选项
- ONES 身份卡的默认 Team 展示为“Team 名称（Team ID）”，名称缺失时才只显示 Team ID；其他候选收纳到“可用 Team”折叠区域，不得把多个 Team ID 作为无说明标签平铺
- ONES 身份绑定状态与个人凭据状态是两个独立治理事实，不得只展示技术值 `ACTIVE`，也不得在管理详情中合并为无法解释的单一状态
- ONES 本人模式根据身份与凭据计算业务可用结果：身份启用且凭据有效为“可使用”；凭据缺失、失效或认证失败为“需要重新验证”；身份或凭据被治理停用为“已被管理员停用”
- ONES 治理模式分别展示“身份绑定状态”和“个人凭据状态”，使用中文业务标签；安全处理提示可以展示给本人，原始错误码只能进入管理员技术详情
- ONES 本人模式和治理模式的默认身份摘要统一展示 ONES 用户名称、业务可用状态、默认 Team、最近验证和最近成功使用
- ONES 默认身份摘要不得展示固定占位的“租户／实例：ones”“连接器：服务端 ONES 实例”、身份 Revision、凭据 Revision 或原始错误码
- ONES 本人模式允许展开“账户详情”，只展示本人的 ONES User ID 以及全部已验证 Team 的名称和 Team ID
- ONES 治理模式允许展开“技术详情”，额外展示外部身份记录 ID 与 Revision、个人凭据状态与 Revision、所绑定 ONES Connection 的名称与精确发布版本、最近错误码及发生时间、最近验证时间和最近成功使用时间
- 任何 ONES 身份页面都不得展示 Token、密码、密文、认证 Header 或 Verification Challenge 内部数据
- ONES“最近成功使用”只在使用该用户持久化个人凭据完成真实 ONES API 请求，且响应通过 Handler 映射和 Output Schema 校验后更新；登录绑定或重新验证只更新“最近验证”，失败尝试不得覆盖最近成功时间
- ONES 个人凭据必须另行记录最近尝试时间、最近错误码和错误发生时间，且只在管理员技术详情中展示；管理员 Capability Test 记为 `ADMIN_TEST`，Agent 运行时调用记为 `RUNTIME`
- ONES 身份字段改造必须同时补齐后端持久化与更新链路：保存 Team 名称和 ID、成功与失败使用事实，并由 Capability Test 和 Agent Runtime 的真实执行结果更新，不得只修改前端标签或从日志临时推断
- ONES 本人接口和治理接口必须分别返回各自允许的字段，前端不得通过额外读取人员、凭据内部表、日志或运行记录绕过展示边界
- 本人模式展示当前用户自己的钉钉昵称、企业名称、身份状态和最近使用信息，但钉钉身份只读，不允许本人绑定、启停或解绑
- 本人模式以钉钉昵称、企业名称、状态和最近使用构成友好摘要，只允许展开本人的钉钉用户 ID 与 Corp ID；不得展示应用观察、连接器、数据修订或治理动作
- 治理模式可以展开钉钉用户 ID、Corp ID、绑定确认时间、数据修订及按应用汇总的观察记录，但内部连接器 ID 不作为身份卡日常信息展示
- 新钉钉身份只能从已验证应用连接产生的受信候选绑定；管理员只选择目标内部用户，不得手工填写或改写 Corp ID、钉钉用户 ID、钉钉昵称或来源应用
- 钉钉身份成功解析受信消息时，以其中按受信事件发生时间排序的最新非空 `senderNick` 刷新**钉钉昵称**；身份必须同时保存昵称观察时间和来源应用连接，空值或较旧事件不得清除或回滚已有昵称，管理员不得手工改写该外部事实
- 钉钉昵称事件时间相同时必须使用稳定事件 ID 决定顺序，使重试和乱序处理保持幂等
- 钉钉昵称变化必须形成精简审计记录，只保存旧昵称、新昵称、受信事件发生时间、来源应用连接和稳定事件 ID，不复制消息正文或其他原始载荷
- 日常身份卡只展示最新钉钉昵称；昵称变更历史仅允许管理员在审计视图查看，本人模式不得展示
- 既有钉钉身份缺少**钉钉昵称**时，从该主体最新一条包含非空 `senderNick` 的受信历史事件幂等回填；没有可验证历史昵称时明确显示“尚未从钉钉获取昵称”，不得用平台人员姓名代替
- 本人模式只展示当前绑定，不展示 `unbound` 历史记录；ONES 身份与个人凭据必须通过 `external_identity_id` 精确关联，不得分别取“第一条身份”和“最新凭据”后拼接
- 管理员治理模式只显示允许的来源事实和凭据元数据；保留钉钉可信绑定、启停、解绑和候选恢复，但不得直接修改已绑定身份的租户或外部主体，也不得渲染 ONES 邮箱密码表单或代用户重新验证
- 治理模式的主区域只展示 `enabled` 或 `disabled` 的当前身份；`unbound` 身份保留为只读审计历史并收纳到默认折叠的“历史记录”，钉钉身份恢复流程可定位并展开对应历史记录
- 普通用户通过独立“我的外部身份”入口访问同一面板的本人模式，不得因此获得人员列表、角色、会话或其他用户详情权限
- “我的外部身份”和人员详情中的同一用户记录读取同一绑定事实，但分别应用本人和治理权限边界，不得形成两份外部身份或凭据状态
- 钉钉企业、应用连接和身份观察模型作为独立 OpenSpec 变更治理，不并入 API Capability 与 Handler 变更；该变更同时确认 ONES 身份卡字段的业务名称及本人／治理展示边界，但不改变既有 ONES 本人绑定和凭据治理原则
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
- Capability Code 与模型 Tool 名统一为**Capability 标识**，不再进行点号到下划线或其他运行时名称转换
- **Capability 标识**采用 `cap__<provider>__<domain>__<operation>` 结构：双下划线分隔层级，层级内使用小写 snake_case，总长不超过 128 字符
- `cap__` 前缀由受治理 API Capability 独占，现有和未来内部 Tool 不得使用该前缀
- **Capability 标识**不包含 `v1`、`v2` 等版本后缀，也不得被复用于不同业务含义；发布时必须校验全局唯一
- Capability 使用专用标识校验器，不能复用会拒绝连续下划线的通用业务 Code 校验规则
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
- 第一版不新增受治理 API Capability 的全局 Feature Flag 或管理页面
- 新能力只有完成 Connection、Capability、Agent 和 Application 的显式发布链后才进入钉钉运行时；任一环节未发布都不会影响现有内部 Tool
- 紧急回退使用具体 Capability Release 的 `DISABLED`，不得依赖环境开关绕过发布状态或删除用户绑定
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
- 第一版 Mapping Plan 只支持字段重命名、对象层级调整、受限字段路径读取、固定常量和数组逐项投影
- 第一版允许管理员显式选择字符串、整数、数字和布尔值之间的基础类型转换，并为可选缺失字段配置固定默认值
- Mapping Plan 不支持条件判断、过滤表达式、字符串拼接、日期计算、正则替换、函数、脚本或部分成功策略
- 类型转换失败、必填字段缺失、数组越界或输出 Schema 不匹配时，整个调用按契约错误失败，不得返回部分规范化结果
- `401` 使当前**外部 API 凭据**失效且不重试；`403` 表示外部授权不足但不自动使 Token 失效
- `400`、`404`、响应过大、JSON 无效和 Schema 不匹配不重试
- `QUERY` 遇到网络错误、超时、`429`、`502`、`503` 或 `504` 时最多进行两次退避重试
- 同一 Tool Call 的所有**外部调用尝试**共享 Job、Tool Call 和 Correlation 标识，并分别记录脱敏结果
- 原始外部响应只在当前 Attempt 内存中存在，映射完成后丢弃，不得进入数据库、日志、审计、错误或模型上下文
- 只有**规范化能力输出**可以提供给 Agent，并在数组、字段和总大小限制内正常写入 Tool Call 结果；Agent 最终回复按现有 Job 和会话模型正常保存
- Audit 只保存版本、主体、Team、状态、耗时、结果数量和摘要 Hash，不保存原始请求响应或认证数据
- API 能力版本必须声明**能力数据分级**，能力发布冻结该分级；`cap__ones__work_item__search` 第一版固定为 `INTERNAL`
- `INTERNAL` 规范化输出只能由具备对应业务应用和 Job 访问权的主体访问，不得复制到日志、审计或公共导出
- 本变更不对规范化结果或最终回复执行定时清理，现有 `session_policy.retention_days` 继续明确为仅保存、未执行
- 后续记忆系统若摄取 `INTERNAL` 输出或最终回复，必须继承用户、业务应用、Capability 和数据分级来源边界；记忆摄取本身不属于本变更
- 第一版通用框架只以 `cap__ones__work_item__search` 实现**ONES 工作项查询**真实验收
- **ONES 工作项查询**输入仅包含关键词、工作项类型和有界数量，输出仅包含编号、名称、类型、总数和截断状态
- 第一版通过测试专用的两个 Capability Fixture 验证“API A 规范化输出 → Agent 组织参数 → API B 输入”的组合链路，不新增第二个生产 ONES Capability
- 第一版端到端验收必须覆盖首个 ONES Connection 启动验证与发布，以及管理员正式绑定自己的 ONES 账号和默认 Team
- 第一版端到端验收必须覆盖管理员配置、测试、验证并发布 `cap__ones__work_item__search`
- 第一版端到端验收必须覆盖 Agent 选择 Capability Release 并发布，以及应用只能从所选 Agent 能力上限中选择子集后绑定钉钉应用发布
- 第一版端到端验收必须证明普通钉钉用户绑定自己的 ONES 后，查询使用该用户的 User ID、默认 Team 和 Token 返回规范化工作项
- 第一版负向验收必须证明 Agent 未配置时应用不能选择、应用未选择时模型不能调用
- 第一版负向验收必须分别覆盖用户未绑定、Token 失效、Team 权限撤销和 Release 禁用，且不得切换其他用户或 Team
- 第一版回归验收必须证明现有内部 Tool 与未升级的 Agent/Application Publication 行为不变
- 能力 Handler 遵循 `DRAFT → VERIFIED → PUBLISHED`，任何 Draft 变更都会使旧验证结果失效
- 只有最新 Draft 验证通过后才能创建**Handler 发布版本**
- Capability Draft 保存必须提交 `expected_revision` 并使用乐观锁；Revision 冲突时拒绝覆盖并要求管理员刷新后重新合并
- Verify 证据必须绑定 Draft Revision 和规范化内容 Hash，任何业务 Schema、Handler、Connection 或映射字段变化都使旧验证失效
- Publish 必须提交已验证 Revision、内容 Hash 和幂等键；相同幂等键重试返回同一 Capability Release
- Publish 在单一事务中原子创建或引用 Capability Revision、创建 Handler Revision、Mapping Plan 和 Capability Release，任一失败整体回滚
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
- HTTPS 是 API Connection 默认传输；企业内网或本地系统使用 HTTP 时必须逐个 Draft 显式记录**明文 HTTP 授权**并在发布前完成真实验证
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
- “新 Capability 需要全局开关”曾可能新增另一套运行状态；已解决为不增加开关页面，使用既有发布链渐进启用并通过 Release 禁用回退。
- “群聊调用 ONES”曾可能被理解为共享会话凭据；已解决为每条消息按当前发送人独立解析凭据，且不得回退共享账号。
- “钉钉用户访问应用”曾可能需要额外应用白名单或角色；第一版已解决为路由命中活动应用且发送人映射为启用内部用户即可访问。
- “查询用户的 ONES”曾先被解决为应用固定 Team；该决定已被取代，现在使用当前用户绑定的 ONES User ID 和默认 Team，且不自动跨 Team。
- “只读 Handler”曾被理解为只允许 HTTP GET；已解决为按业务操作语义判断，允许固定只读 GraphQL 的 POST，但禁止 mutation 和原始查询输入。
- “修改已发布 Handler”曾被理解为直接编辑当前配置；已解决为发布版本不可变，任何调整都从新 Draft 开始并重新验证发布。
- “多人编辑并发布 Capability”曾可能产生覆盖或重复 Release；已解决为 Draft 乐观锁、验证内容 Hash、幂等键和原子发布事务。
- “测试 Handler”曾考虑使用 Connection 独立验证凭据；已解决为当前授权管理员使用自己的 ONES 身份和 Token，且该 Token 不进入发布或其他用户运行时。
- “ONES 登录 API”曾可能被当作 Agent 可调用能力；已解决为 Connection Authentication Profile 的内部认证协议，永不进入 Capability Catalog。
- “应用发布冻结凭据”曾可能被理解为把 Token 写入发布快照；已解决为只冻结认证协议版本，运行时读取当前用户最新有效 Token。
- “应用能否使用 ONES”曾被理解为一个全局布尔状态；已解决为应用发布就绪与每个当前用户的能力可用状态分别计算。
- “管理员绑定 ONES”曾可能表示管理员代输普通用户密码并持有 Token；已解决为个人凭据只能本人自助创建和轮换，管理员只治理状态。
- “管理员不能操作其他用户凭据”曾可能同时禁止泄露处置；已解决为管理员可查看元数据、禁用或解绑，但不能查看 Token、绑定、代输密码或重新验证。
- “新增我的外部身份”曾可能表示重做一套绑定页面；已解决为复用现有外部身份面板，并由“我的外部身份”与“人员管理详情”两个入口分别固定本人和治理模式。
- “拥有 API 配置权限”曾可能自动允许业务调用；已解决为治理管理权限只控制配置，运行时调用资格来自 Agent 能力上限、应用能力子集和用户应用访问权。
- “Capability 还要按用户或角色单独授权”曾造成重复配置；已解决为不设独立 Capability Code `use` Grant，用户访问应用即获得该应用已选能力的调用资格。
- “输入 ONES 密码后选择 Team”曾可能要求把 Token 暂存到浏览器；已解决为服务端短时单次 Challenge 返回安全候选，确认后原子绑定。
- “切换默认 Team”曾可能表示从历史 Team 列表直接改值并影响正在执行的任务；已解决为重新验证后从当前 Team 集合选择，且只影响之后创建的 Job。
- “Job 冻结外部主体”曾可能允许已撤销权限继续执行；已解决为快照防止身份漂移，但每次调用仍实时校验主体、Team 成员资格和当前 Token。
- “不可用 Capability”曾可能仍暴露给模型并等待调用失败；已解决为暴露前隐藏并提供安全提示，执行前仍再次失败关闭检查。
- “请求/响应映射”曾可能表示管理员可编写任意模板或表达式；已解决为只支持可静态验证的类型化字段投影。
- “受限字段映射”曾未明确允许哪些转换；已解决为确定性字段/数组投影、有限基础类型转换和固定默认值，任何契约错误整体失败。
- “测试预览不脱敏”曾可能包含认证材料或原始响应；已解决为普通业务字段完整显示，但凭据字段从预览模型中直接排除，外部原始响应仍不展示。
- “一个 API 的结果作为另一个 API 输入”曾可能表示 Handler 自动直连或透传原始响应；已解决为 Agent 只使用规范化输出组织下一个公开 Input Schema，并对每次调用独立授权。
- “Handler Schema”曾可能同时表示 Agent 业务契约和外部接口结构；已解决为公开业务 Schema 属于 API 能力，Handler 只负责实现和验证该契约。
- “Capability 版本”曾可能通过修改 Code 中的 `v1`、`v2` 表示；已解决为 Code 稳定、Release Revision 递增，并按实现、Schema 或业务语义变化选择不同版本路径。
- “Capability 业务 Code 与模型 Tool 名分离”曾引入转换和碰撞处理；已解决为统一使用 `cap__` 保留命名空间中的同一个稳定标识。
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
- “第一版查询 ONES”曾可能包含多个工作项能力；已解决为通用框架只用 `cap__ones__work_item__search` 完成单 Team 只读端到端验收。
