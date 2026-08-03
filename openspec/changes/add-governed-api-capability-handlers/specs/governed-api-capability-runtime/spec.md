## ADDED Requirements

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
