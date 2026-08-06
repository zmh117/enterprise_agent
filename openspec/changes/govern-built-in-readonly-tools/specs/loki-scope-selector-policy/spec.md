## ADDED Requirements

### Requirement: Loki Resource 只允许 global 或 environment 连接范围
系统 SHALL 允许 Loki Resource Revision 声明 global scope 或一个精确 Environment scope，并 MUST NOT 把 Base、Workshop 或 cloud/edge placement 作为 Loki 连接资源范围。

#### Scenario: 当前统一 Loki
- **WHEN** 一个 Loki 实例采集多个 Environment 的日志
- **THEN** 管理员可把该 Resource Revision 发布为 global，并通过不同 Scope Policy 收窄各 Environment

#### Scenario: 每环境独立 Loki
- **WHEN** 某 Environment 使用自己的 Loki 实例
- **THEN** 管理员可把该 Resource Revision 发布为该精确 Environment scope

#### Scenario: 提交车间或 placement 范围
- **WHEN** Loki Resource Draft 提交 Workshop scope、cloud placement 或 edge placement
- **THEN** 系统拒绝配置

### Requirement: Loki 连接测试必须提供有界级联标签发现
管理员成功测试 Loki Resource Draft 的 URL、tenant、Secret、超时和连接后，系统 SHALL 在同一受控测试上下文中提供有界 label key 发现；选择 key 后 SHALL 允许按此前已选精确条件查询该 key 的有界 value 列表。

#### Scenario: 测试成功返回 label keys
- **WHEN** 授权管理员点击测试且 Loki 连接成功
- **THEN** API 返回去重、排序、截断标记和上限内的 label key 列表，不返回日志正文

#### Scenario: 级联查询 label values
- **WHEN** 管理员已选择 `customer=sanjiu-test1` 后查询下一个 key 的 values
- **THEN** 系统用该精确条件收窄有界发现请求并返回 value 列表

#### Scenario: 发现请求越界
- **WHEN** 请求包含任意 LogQL、正则、负向匹配、超出允许时间窗或超过数量/字节上限
- **THEN** 系统拒绝或截断并返回安全摘要

#### Scenario: 未通过连接测试直接发现
- **WHEN** Draft 内容变化导致测试证据失效或当前管理员没有有效测试上下文
- **THEN** 系统拒绝标签发现并要求重新测试

### Requirement: 标签发现结果不得成为隐式运行配置
标签 key/value 发现结果 SHALL 仅作为当前 Draft 和测试会话的填写辅助证据；系统 MUST NOT 自动保存完整标签目录、自动创建 Scope Policy 或在运行时查询发现目录来扩大范围。

#### Scenario: 管理员关闭未保存页面
- **WHEN** 标签发现成功但管理员没有保存 Policy Draft
- **THEN** 系统不创建可发布 selector，发现缓存按受控期限失效

#### Scenario: Loki 后续出现新 label value
- **WHEN** Published Scope Policy 创建后 Loki 出现新的 label value
- **THEN** 既有 Policy 和 Application Publication 不自动改变

### Requirement: Loki Scope Selector Policy 必须使用精确 AND 条件
每个 Loki Scope Selector Policy Draft MUST 绑定一个精确 Loki Resource Revision、一个平台 Environment 和可选 Base，并 SHALL 包含一个或多个唯一 key 的精确非空 `key=value` 条件；条件只允许 AND，禁止重复 key、OR、否定、正则、通配和任意 LogQL。

#### Scenario: 保存环境 selector
- **WHEN** 管理员为 Environment `sanjiu-test1` 保存 `customer=sanjiu-test1`
- **THEN** 系统保存规范化的一个精确条件和业务范围映射

#### Scenario: 保存环境加基地 selector
- **WHEN** 管理员为 Environment `sanjiu-test1`、Base `guanlan` 保存 `customer=sanjiu-test1 AND workshop=guanlan`
- **THEN** 系统保存两个唯一 key 的精确条件，并明确物理 `workshop` value 映射逻辑 Base

#### Scenario: 多个基地使用一个 OR 策略
- **WHEN** 管理员尝试用 OR 在一个 Policy 中包含 `guanlan` 与 `tianjin`
- **THEN** 系统拒绝并要求为每个 Base 建立独立命名 Policy

#### Scenario: 提交重复或模糊条件
- **WHEN** Draft 含重复 key、正则、`!=`、`=~`、空 value 或任意 LogQL 片段
- **THEN** 系统拒绝保存或验证

### Requirement: Scope Policy 必须独立验证并不可变发布
系统 SHALL 为 Loki Scope Selector Policy 管理 Draft、机器验证证据和不可变 Published Revision；验证 MUST 绑定 Resource Revision、规范化条件 hash、Verifier Version 和有界响应摘要，内容或资源变化后旧证据失效。

#### Scenario: 验证 selector 有匹配
- **WHEN** 受限查询成功并命中日志流
- **THEN** 系统保存匹配数量、截断标记、hash 和时间，不保存无界日志正文

#### Scenario: 验证 selector 零匹配
- **WHEN** 受限查询被 Loki 正常接受但当前没有匹配流
- **THEN** 验证可以成功并携带 zero-match warning，Publish 不得自动移除任何条件

#### Scenario: 发布后修改条件
- **WHEN** 管理员尝试修改 Published Policy Revision
- **THEN** 系统拒绝并要求复制为新 Draft、重新验证和发布

### Requirement: Application Publication 必须冻结精确 Loki 资源与 Scope Policy
Application Publication MUST 为每个 Loki slot 和有效 Environment 冻结精确 Loki Resource Revision、Scope Policy ID/revision/hash；一个有效 Environment MUST NOT 同时命中 global 与 environment Loki 或多个 Scope Policy。

#### Scenario: global Loki 服务两个环境
- **WHEN** 一个应用使用同一 global Loki 查询两个 Environment
- **THEN** Publication 为每个 Environment 分别冻结指向同一 Resource Revision 的独立 Scope Policy

#### Scenario: 环境切换独立 Loki
- **WHEN** 管理员为某 Environment 发布新的独立 Loki Resource
- **THEN** 既有 Publication 仍使用原 global Mapping，只有新 Application Publication 可显式切换

#### Scenario: 同一环境配置重叠
- **WHEN** 同一 Loki slot 的 global 与 environment Mapping 或两个 Policy 同时覆盖一个 Environment
- **THEN** Application Publish 拒绝歧义配置

### Requirement: Published Scope Policy 必须作为不可覆盖的运行时 selector
运行时 MUST 从 Job Snapshot 注入 Published Scope Policy 的全部精确条件；Agent 只能添加 Tool Manifest 明确允许的诊断过滤条件，最终 selector 必须为强制条件与附加条件的 AND，且附加条件不得覆盖或冲突同名强制 key。

#### Scenario: Agent 添加允许的 logtype
- **WHEN** Manifest 允许 `logtype` 诊断过滤且 Agent 请求一个精确 value
- **THEN** 运行时把该条件与强制 Environment/Base selector 进行 AND 合并

#### Scenario: Agent 覆盖 customer
- **WHEN** Agent 请求不同的 `customer`、tenant 或删除强制条件
- **THEN** 平台拒绝调用或忽略冲突输入并始终使用冻结范围，不得扩大查询

#### Scenario: 请求任意 LogQL selector
- **WHEN** Agent 输入包含 OR、负向匹配、正则或任意 selector 字符串
- **THEN** 平台在访问 Loki 前拒绝请求

### Requirement: Loki 不得宣称 Workshop 或 placement 授权隔离
第一阶段 Loki 授权范围 SHALL 止于 Environment 和可选 Base；`role`、`replica`、`app`、`logtype` 只能作为受控诊断过滤，MUST NOT 被解释为用户角色、Resource Placement 或可靠 Workshop 身份。

#### Scenario: Job 目标包含 GL001
- **WHEN** Job 业务目标为某 Base 下 Workshop GL001
- **THEN** Loki 查询仍使用该 Environment/Base 的强制 Scope Policy，不自动注入 `workshop=GL001` 或 `replica=GL001`

#### Scenario: 日志 label role 为 edge
- **WHEN** Loki 流包含 `role=edge`
- **THEN** 系统只把它作为采集侧诊断属性，不据此授予 edge 权限或改变 Resource Placement

### Requirement: 空结果健康必须与生命周期分离
系统 SHALL 监测 Published Scope Policy 的查询结果并可标记 `EMPTY` 或 `DEGRADED` 健康状态；长期零匹配 MUST NOT 自动 disable、archive、切换 Policy 或放宽 selector。

#### Scenario: Published Policy 长期零匹配
- **WHEN** 多次受控健康探测均被 Loki 接受但返回零流
- **THEN** 管理端显示 EMPTY/DEGRADED 和最后证据，运行时继续按原 selector 返回空结果

#### Scenario: Loki 上游不可用
- **WHEN** 健康探测因连接、认证或超时失败
- **THEN** 系统标记安全的上游健康错误，与“成功但为空”区分，并且不泄露 Secret
