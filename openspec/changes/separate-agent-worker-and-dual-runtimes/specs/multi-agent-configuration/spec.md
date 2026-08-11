## MODIFIED Requirements

### Requirement: Agent 定义按多 Agent 模型持久化
系统 SHALL 持久化多个 Agent 定义，每个定义具有稳定 code、名称、说明、项目范围、状态、当前发布指针和创建后不可变的 `runtime_kind`。系统 MUST 初始化固定 `python-v1` 的默认诊断 Agent 和固定 `typescript-v1` 的 TypeScript 诊断 Agent，且不得通过修改同一 Agent 的 runtime kind 完成 Runtime 切换。

#### Scenario: 两个内置Agent初始化
- **WHEN** 系统完成 migration 和 seed
- **THEN** 系统存在稳定 code 为 `default-diagnostic-agent` 且 runtime kind 为 `python-v1` 的 Agent
- **AND** 存在稳定 code 为 `typescript-diagnostic-agent` 且 runtime kind 为 `typescript-v1` 的 Agent

#### Scenario: 后端读取指定Agent
- **WHEN** API 或运行时按 Agent code 请求配置
- **THEN** repository 按通用多 Agent 模型返回对应定义及 runtime kind，而不是依赖单例配置表

#### Scenario: 修改既有Agent的Runtime
- **WHEN** 管理员尝试把既有 Agent Definition 的 runtime kind 从 Python 改为 TypeScript 或反向修改
- **THEN** 系统拒绝修改并提示选择或创建另一 Agent

### Requirement: Agent 草稿与发布快照分离
系统 SHALL 为 Agent 保存可编辑草稿 revision，并 MUST 在发布时创建包含完整有效配置、不可变 runtime kind、schema version 和 config hash 的不可变 publication snapshot。草稿不得覆盖 Definition 的 runtime kind。

#### Scenario: 编辑已发布Agent草稿
- **WHEN** 管理员修改任一内置 Agent 的业务指令或工具分配
- **THEN** 系统只创建或更新该 Agent 的新草稿 revision，现有 publication 与 runtime kind 保持不变

#### Scenario: 发布合法草稿
- **WHEN** 具备发布权限的管理员发布通过校验的 Python 或 TypeScript Agent 草稿
- **THEN** 系统创建包含对应 runtime kind 的新不可变 publication，并更新该 Agent 的当前发布指针

#### Scenario: 草稿伪造Runtime
- **WHEN** 草稿 payload 的 runtime kind 与 Agent Definition 不一致
- **THEN** 系统拒绝校验和发布且不创建 publication

### Requirement: Agent job 固定发布版本
系统 SHALL 在创建 Job 的数据库事务中保存 Agent definition、publication ID、revision、config hash、runtime kind 和 Runtime 协议版本。Worker 和 retry MUST 使用 Job 固定的 publication 与 Runtime，不得重新读取当前发布指针、草稿或迁移门禁，也不得在故障时跨 Runtime fallback。

#### Scenario: 发布后创建Job
- **WHEN** Application 选择的 Agent Publication 有效且用户提交请求
- **THEN** Job 在发布队列前固定该 publication ID、revision、hash、runtime kind 和协议版本

#### Scenario: Job排队期间发布新版本
- **WHEN** Job 已固定版本后管理员发布新的 Agent revision
- **THEN** 已排队 Job 继续使用原版本和 Runtime，新 Job 才使用新 Publication

#### Scenario: Job重试
- **WHEN** Job 因瞬时错误进入 retry
- **THEN** 重试仍使用原 publication snapshot、runtime kind、协议版本和 invocation 规则

#### Scenario: 固定Runtime不可用
- **WHEN** Job 固定的 Runtime 暂时不可连接
- **THEN** Worker 按固定错误分类重试或终止，不自动调用另一 Runtime

## ADDED Requirements

### Requirement: Agent管理界面必须支持两个Runtime Agent
Agent 管理 API 与前端 SHALL 列出 Python、TypeScript 两个内置 Agent，并允许具备权限的管理员分别编辑草稿、校验、发布、查看历史和回滚；页面 MUST 清楚展示只读 runtime kind。

#### Scenario: 管理员发布TypeScript Agent
- **WHEN** 管理员进入 `typescript-diagnostic-agent` 并提交合法草稿
- **THEN** 页面允许完成校验和发布并显示新 Publication 及 `typescript-v1` 标签

#### Scenario: 管理员查看Python Agent历史
- **WHEN** 管理员选择 `default-diagnostic-agent`
- **THEN** 页面展示其 Python runtime 标签、草稿和历史 Publication，而不是把非默认 Agent 强制设为只读
