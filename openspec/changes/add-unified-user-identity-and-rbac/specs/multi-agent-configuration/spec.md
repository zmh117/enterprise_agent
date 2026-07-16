## ADDED Requirements

### Requirement: Agent 定义按多 Agent 模型持久化
系统 SHALL 持久化多个 Agent 定义，每个定义具有稳定 code、名称、说明、项目范围、状态和当前发布指针。

#### Scenario: 默认诊断 Agent 初始化
- **WHEN** 系统完成 migration 和 seed
- **THEN** 系统存在稳定 code 为 `default-diagnostic-agent` 的默认只读诊断 Agent

#### Scenario: 后端读取指定 Agent
- **WHEN** API 或运行时按 Agent code 请求配置
- **THEN** repository 按通用多 Agent 模型返回对应定义，而不是依赖单例配置表

### Requirement: Agent 草稿与发布快照分离
系统 SHALL 为 Agent 保存可编辑草稿 revision，并 MUST 在发布时创建包含完整有效配置、schema version 和 config hash 的不可变 publication snapshot。

#### Scenario: 编辑已发布 Agent 草稿
- **WHEN** 管理员修改已发布 Agent 的业务指令或工具分配
- **THEN** 系统只创建或更新新的草稿 revision，现有 publication 保持不变

#### Scenario: 发布合法草稿
- **WHEN** 具备发布权限的管理员发布通过校验的草稿
- **THEN** 系统创建新的不可变 publication，并更新该 Agent 的当前发布指针

### Requirement: Agent 发布配置区分可编辑业务层和强制安全层
系统 SHALL 允许草稿配置业务指令、模型策略、执行限制、只读工具、Skill、默认 routing 和 Channel/Delivery 绑定，但 MUST NOT 允许配置覆盖平台安全规则、用户权限、只读工具策略、SDK 写工具禁用或 secret 明文。

#### Scenario: 管理员保存业务指令
- **WHEN** 管理员修改默认 Agent 的诊断目标和报告偏好
- **THEN** 系统把内容保存到业务指令层，并在运行时叠加强制安全层

#### Scenario: 草稿尝试开放写工具
- **WHEN** 草稿包含 Bash、Write、Edit、写数据库、Redis mutation 或未注册 executable tool
- **THEN** 系统拒绝校验和发布

### Requirement: Agent job 固定发布版本
系统 SHALL 在创建 job 的数据库事务中保存 Agent definition、publication ID、revision 和 config hash。worker 和 retry MUST 使用 job 固定的 publication，而不是重新读取当前发布指针或草稿。

#### Scenario: 发布后创建 job
- **WHEN** 默认 Agent 当前 publication 有效且用户提交请求
- **THEN** job 在发布队列前固定该 publication ID、revision 和 hash

#### Scenario: job 排队期间发布新版本
- **WHEN** job 已固定版本后管理员发布新的 Agent revision
- **THEN** 已排队 job 继续使用原版本，新 job 使用新版本

#### Scenario: job 重试
- **WHEN** job 因瞬时错误进入 retry
- **THEN** 重试仍使用原 publication snapshot

### Requirement: Agent 发布支持校验和回滚
系统 SHALL 在发布前校验引用的模型策略、工具、Skill、connector、项目和安全边界，并 MUST 通过切换当前发布指针回滚到历史 publication，不修改历史快照。

#### Scenario: 发布引用禁用工具
- **WHEN** 草稿分配已禁用或非只读工具
- **THEN** 系统拒绝发布并返回字段级校验错误

#### Scenario: 回滚默认 Agent
- **WHEN** 具备发布权限的管理员选择一个历史有效 publication 回滚
- **THEN** 系统把它设为新 job 的当前版本、记录审计，并保持历史 publication 不变

### Requirement: 未发布或无效 Agent 必须 fail closed
系统 SHALL 在目标 Agent 没有启用的有效 publication、publication hash 不一致或 snapshot schema 不受支持时拒绝创建或执行新 job。

#### Scenario: 默认 Agent 尚未发布
- **WHEN** Channel 请求选择默认 Agent但它没有有效 publication
- **THEN** 系统返回安全配置错误且不发布 Agent job
