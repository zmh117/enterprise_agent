## MODIFIED Requirements

### Requirement: Web必须提供默认Agent Profile管理入口
系统 SHALL 在管理 Web 增加“Agent 配置 / Agent Profile”菜单、Profile 列表、创建入口和详情页，并 MUST 使用真实管理 API 展示草稿、当前 Publication、Effective Config、校验结果和 Publication 历史。具备 Agent 全局编辑权限的管理员 SHALL 能够创建 Agent；系统 MUST NOT 提供删除、复制或修改既有 Agent code 与 Runtime kind 的动作。

#### Scenario: 管理员打开Agent Profile列表
- **WHEN** 具备 Agent 读取权限的管理员打开 Agent Profile 菜单
- **THEN** 页面从后端加载 Agent 定义、当前 Publication、Runtime kind 和管理权限
- **AND** 每个 Agent 按当前用户权限显示可编辑或只读状态

#### Scenario: Agent列表为空
- **WHEN** 后端返回空 Agent 列表
- **THEN** 页面展示明确空状态而不是空白网格
- **AND** 具备 Agent 全局编辑权限的管理员可以从空状态打开新建表单

#### Scenario: 管理员打开新建Agent表单
- **WHEN** 具备 Agent 全局编辑权限的管理员点击“新建 Agent”
- **THEN** 页面允许填写 code、名称、说明、项目编码并选择 Python 或 TypeScript Runtime
- **AND** 页面明确提示 code 与 Runtime 创建后不可修改且创建不会自动发布

#### Scenario: 无编辑权限的用户查看列表
- **WHEN** 仅具备 Agent 读取权限的用户打开 Agent Profile 列表
- **THEN** 页面不提供可提交的新建动作
- **AND** 后端继续拒绝该用户直接提交的创建请求

### Requirement: Agent Profile模型连接操作必须授权和审计
系统 SHALL 复用统一 RBAC：读取 Profile 需要 Agent read/edit 权限，创建 Agent 需要 `agent:*:edit` 全局权限，保存草稿需要目标 Agent edit 权限，发布和回滚需要目标 Agent publish 权限，创建或轮换 Key 及执行真实连接测试需要 Secret 管理权限。所有写操作和连接测试 MUST 记录不含敏感值的审计事件。

#### Scenario: 无Secret权限的用户更新Key
- **WHEN** 仅具有 Agent edit 权限的用户提交 Key 创建、轮换或连接测试请求
- **THEN** 系统拒绝请求且不访问外部模型服务

#### Scenario: 无全局编辑权限的用户创建Agent
- **WHEN** 用户具备某个既有 Agent 的编辑权限但不具备 `agent:*:edit` 全局权限并提交创建请求
- **THEN** 系统拒绝请求且不写入 Agent Definition 或 Draft
- **AND** 权限拒绝通过统一 RBAC 审计记录

#### Scenario: 创建Agent审计
- **WHEN** 管理员成功创建 Agent
- **THEN** 审计记录 actor、Agent code、Runtime kind、项目编码和初始 Draft revision
- **AND** 审计不包含模型凭据、Secret、Prompt 或业务消息

#### Scenario: 发布审计
- **WHEN** 管理员发布包含模型连接的 Agent Publication
- **THEN** 审计记录 Agent code、Publication ID、模型连接 revision、config hash、模型和脱敏 Provider Host
- **AND** 审计不包含 Key、Secret ref、Prompt 或模型响应

### Requirement: Agent 定义按多 Agent 模型持久化
系统 SHALL 持久化多个 Agent 定义，每个定义具有稳定 code、名称、说明、项目范围、状态、当前发布指针和创建后不可变的 `runtime_kind`。系统 MUST 在 deployment bootstrap 中幂等初始化固定 `python-v1` 的默认诊断 Agent 和固定 `typescript-v1` 的 TypeScript 诊断 Agent，并 SHALL 允许受权管理员创建使用任一受支持 Runtime 的业务 Agent；系统不得通过修改同一 Agent 的 runtime kind 完成 Runtime 切换。

#### Scenario: 两个内置Agent初始化
- **WHEN** 全新数据库完成 migration、管理员 bootstrap 和 Agent bootstrap
- **THEN** 系统存在稳定 code 为 `default-diagnostic-agent` 且 runtime kind 为 `python-v1` 的 Agent
- **AND** 存在稳定 code 为 `typescript-diagnostic-agent` 且 runtime kind 为 `typescript-v1` 的 Agent
- **AND** 两个 Agent 均具有可编辑初始 Draft，但 bootstrap 不自动创建 Publication 或业务应用绑定

#### Scenario: 重复运行Agent bootstrap
- **WHEN** 已存在固定 Agent、用户 Draft 或 Publication 后再次运行 Agent bootstrap
- **THEN** 系统不覆盖既有名称、配置、版本、Publication 或业务应用引用
- **AND** 固定 code 对应的 Runtime kind 不一致时 bootstrap 失败关闭

#### Scenario: 后端读取指定Agent
- **WHEN** API 或运行时按 Agent code 请求配置
- **THEN** repository 按通用多 Agent 模型返回对应定义及 runtime kind，而不是依赖单例配置表

#### Scenario: 创建Python Agent
- **WHEN** 具备权限的管理员提交唯一合法 code、名称、项目编码和 `python-v1`
- **THEN** 系统创建 classification 为 `business`、status 为 `enabled` 的 Agent Definition
- **AND** Definition 的 runtime kind 固定为 `python-v1`

#### Scenario: 创建TypeScript Agent
- **WHEN** 具备权限的管理员提交唯一合法 code、名称、项目编码和 `typescript-v1`
- **THEN** 系统创建 classification 为 `business`、status 为 `enabled` 的 Agent Definition
- **AND** Definition 的 runtime kind 固定为 `typescript-v1`

#### Scenario: 修改既有Agent的Runtime
- **WHEN** 管理员尝试把既有 Agent Definition 的 runtime kind 从 Python 改为 TypeScript 或反向修改
- **THEN** 系统拒绝修改并提示选择或创建另一 Agent

## ADDED Requirements

### Requirement: Agent创建必须原子生成初始草稿
系统 MUST 在同一数据库事务中创建 Agent Definition 与 r1 Draft。初始 Draft SHALL 使用平台固定的非敏感默认配置和所选项目范围，MUST NOT 接受客户端指定 Publication、状态、classification、created_by、任意模型凭据或 Runtime 覆盖，并 MUST NOT 自动发布或改变运行路由。

#### Scenario: 成功创建Agent
- **WHEN** 受权管理员提交合法且唯一的 Agent 创建请求
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
- **WHEN** 客户端提交 `python-v1` 与 `typescript-v1` 之外的 runtime kind
- **THEN** API 返回字段级校验错误且不创建 Definition 或 Draft
