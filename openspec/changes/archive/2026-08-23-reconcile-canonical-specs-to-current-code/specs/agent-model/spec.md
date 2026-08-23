## MODIFIED Requirements

### Requirement: Agent 定义按多 Agent 模型持久化
系统 SHALL 持久化多个 Agent 定义，每个定义具有稳定 code、名称、说明、项目范围、状态、当前发布指针和创建后不可变的 `runtime_kind`。系统 MUST 在 deployment bootstrap 中仅幂等初始化固定 `python-v1` 的默认诊断 Agent，并 SHALL 只允许受权管理员创建 `python-v1` 业务 Agent。退役前已经持久化的 `typescript-v1` Definition、Publication、终态 Job 和审计事实 MUST 保留原始 runtime kind 并只读展示；系统不得新建、编辑、发布、回滚或执行 TypeScript Agent，也不得通过修改同一 Agent 的 runtime kind 完成 Runtime 切换。

#### Scenario: 默认Python Agent初始化
- **WHEN** 系统完成 migration 和 Agent bootstrap
- **THEN** 系统存在稳定 code 为 `default-diagnostic-agent` 且 runtime kind 为 `python-v1` 的 Agent
- **AND** 系统不创建 `typescript-diagnostic-agent` 或其它 `typescript-v1` Agent

#### Scenario: 创建Python Agent
- **WHEN** 具备权限的管理员提交唯一合法 code、名称、项目编码和 `python-v1`
- **THEN** 系统创建 classification 为 `business`、status 为 `enabled` 的 Agent Definition
- **AND** Definition 的 runtime kind 固定为 `python-v1`

#### Scenario: 旧客户端创建TypeScript Agent
- **WHEN** 旧客户端提交 `typescript-v1` 或其它非 `python-v1` runtime kind
- **THEN** 系统拒绝请求且不创建 Definition 或 Draft

#### Scenario: 读取历史TypeScript Agent
- **WHEN** 管理员查看退役前已存在的 `typescript-v1` Agent
- **THEN** API 返回其原始只读 Definition、Publication 和 runtime 标签
- **AND** 不允许编辑、发布、回滚为当前版本或用于新执行

#### Scenario: 重复运行Agent bootstrap
- **WHEN** 已存在固定 Agent、用户 Draft 或 Publication 后再次运行 Agent bootstrap
- **THEN** 系统不覆盖既有名称、配置、版本、Publication 或业务应用引用
- **AND** 固定 code 对应的 runtime kind 不一致时 bootstrap 失败关闭

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
- **WHEN** 客户端提交 `typescript-v1` 或其它非 `python-v1` runtime kind
- **THEN** API 返回字段级校验错误且不创建 Definition 或 Draft
