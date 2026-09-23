## MODIFIED Requirements

### Requirement: Agent 定义按多 Agent 模型持久化
系统 SHALL 持久化多个 Agent 定义，每个定义具有稳定 code、名称、说明、项目范围、状态、当前发布指针和创建后不可变的 `runtime_kind`。系统 MUST 在 deployment bootstrap 中仅幂等初始化固定 `python-v1` 的默认诊断 Agent，并 SHALL 只允许受权管理员创建 `python-v1` 业务 Agent。Definition、Publication 与 Job 的 runtime kind MUST 由数据库约束限定为 `python-v1`；系统不得新建、编辑、发布、回滚或执行其它 runtime kind 的 Agent，也不得通过修改同一 Agent 的 runtime kind 完成 Runtime 切换。

#### Scenario: 默认Python Agent初始化
- **WHEN** 系统完成 migration 和 Agent bootstrap
- **THEN** 系统存在稳定 code 为 `default-diagnostic-agent` 且 runtime kind 为 `python-v1` 的 Agent
- **AND** 系统不创建任何其它 runtime kind 的 Agent

#### Scenario: 创建Python Agent
- **WHEN** 具备权限的管理员提交唯一合法 code、名称、项目编码和 `python-v1`
- **THEN** 系统创建 classification 为 `business`、status 为 `enabled` 的 Agent Definition
- **AND** Definition 的 runtime kind 固定为 `python-v1`

#### Scenario: 客户端创建非Python Agent
- **WHEN** 客户端提交任何非 `python-v1` runtime kind
- **THEN** 系统拒绝请求且不创建 Definition 或 Draft

#### Scenario: 重复运行Agent bootstrap
- **WHEN** 已存在固定 Agent、用户 Draft 或 Publication 后再次运行 Agent bootstrap
- **THEN** 系统不覆盖既有名称、配置、版本、Publication 或业务应用引用
- **AND** 固定 code 对应的 runtime kind 不一致时 bootstrap 失败关闭

### Requirement: Agent 草稿与发布快照分离
系统 SHALL 为 Python Agent 保存可编辑草稿 revision，并 MUST 在发布时创建包含完整有效配置、不可变 `python-v1` runtime kind、schema version 和 config hash 的不可变 publication snapshot。草稿不得覆盖 Definition 的 runtime kind。

#### Scenario: 编辑已发布Python Agent草稿
- **WHEN** 管理员修改已发布 Python Agent 的业务指令或工具分配
- **THEN** 系统只创建或更新该 Agent 的新草稿 revision，现有 publication 与 runtime kind 保持不变

#### Scenario: 发布合法Python草稿
- **WHEN** 具备发布权限的管理员发布通过校验的 Python Agent 草稿
- **THEN** 系统创建包含 `python-v1` 的新不可变 publication，并更新该 Agent 的当前发布指针

#### Scenario: 草稿伪造Runtime
- **WHEN** 草稿 payload 的 runtime kind 不是 `python-v1` 或与 Agent Definition 不一致
- **THEN** 系统拒绝校验和发布且不创建 publication

### Requirement: Agent创建必须原子生成初始草稿
系统 MUST 在同一数据库事务中创建 `python-v1` Agent Definition 与 r1 Draft。初始 Draft SHALL 使用平台固定的非敏感默认配置和所选项目范围，MUST NOT 接受客户端指定 Publication、状态、classification、created_by、任意模型凭据或 Runtime 覆盖，并 MUST NOT 自动发布或改变运行路由。

#### Scenario: 成功创建Agent
- **WHEN** 受权管理员提交合法、唯一且 runtime kind 为 `python-v1` 的 Agent 创建请求
- **THEN** 系统原子创建 Definition 和归属该 Definition 的 r1 Draft
- **AND** `current_publication_id` 为空且不存在因本次创建产生的业务应用引用

#### Scenario: Agent code重复
- **WHEN** 两个请求串行或并发提交同一 Agent code
- **THEN** 至多一个请求创建 Definition 与 r1 Draft
- **AND** 其他请求返回稳定 `agent_code_conflict`，不产生孤立 Definition 或 Draft

#### Scenario: 创建请求包含平台控制字段
- **WHEN** 客户端提交 status、classification、current publication、created_by、Draft config 或其他未声明字段
- **THEN** API 拒绝请求且不写入任何 Agent 记录

#### Scenario: 创建请求使用非法Runtime
- **WHEN** 客户端提交任何非 `python-v1` runtime kind
- **THEN** API 返回字段级校验错误且不创建 Definition 或 Draft

## ADDED Requirements

### Requirement: Agent管理界面只管理Python Runtime
当前 Agent 创建、草稿、发布、回滚与执行 SHALL 只支持 `python-v1`，管理界面 MUST NOT 提供 Runtime 选择项。合法 Python 历史协议或工具策略版本可由管理读取标记为只读。当前 Publication 完整性校验 MUST 拒绝不受支持或与 Definition 不一致的 runtime kind，且不得通过改写标签进入当前执行链。

#### Scenario: 创建Python Agent
- **WHEN** 管理员具备权限并提交合法创建请求
- **THEN** Definition 和初始 Draft 使用 python-v1；页面不提供 Runtime 选择项。

#### Scenario: Runtime不受支持
- **WHEN** Publication 的 runtime kind 非 python-v1 或与 Definition 不一致
- **THEN** 完整性校验失败关闭，不能通过改标签进入当前执行链。

## REMOVED Requirements

### Requirement: Agent管理界面只管理Python Runtime并保留原始Runtime身份
**Reason**: 迁移 119 已禁止数据库出现非 `python-v1` 的 Definition/Publication/Job，“保留 TypeScript 原始 Runtime 身份”不再对应任何可能存在的数据。
**Migration**: 由 ADDED 的“Agent管理界面只管理Python Runtime”替代；Python 历史协议只读标记与完整性失败关闭语义保持不变。
