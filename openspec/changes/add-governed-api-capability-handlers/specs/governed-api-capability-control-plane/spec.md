## ADDED Requirements

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
