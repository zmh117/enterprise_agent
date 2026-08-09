## MODIFIED Requirements

### Requirement: Agent 定义按多 Agent 模型持久化
系统 SHALL 持久化和管理多个 Agent 定义，每个定义具有稳定 code、名称、说明、项目范围、生命周期状态、revision 和当前 Publication 指针。管理 API/Web MUST 列出用户有权读取的 Agent，并 MUST 支持创建、编辑、停用和无活动引用时归档，不能回退为单例默认配置。

#### Scenario: 默认诊断 Agent 初始化
- **WHEN** 系统完成 migration 和 seed
- **THEN** 系统存在稳定 code 为 `default-diagnostic-agent` 的默认只读诊断 Agent

#### Scenario: 创建第二个 Agent
- **WHEN** 有创建权限的管理员提交唯一 code、合法项目范围和基础元数据
- **THEN** 系统创建独立 Agent 定义与初始 Draft，不自动发布、激活或改变现有 Job

#### Scenario: 用户读取 Agent 列表
- **WHEN** 已登录用户打开 Agent 管理页
- **THEN** API 只返回其项目/Agent read 权限覆盖的定义和安全 Publication 摘要

### Requirement: Agent 草稿与发布快照分离
系统 SHALL 为每个 Agent 保存可编辑 Draft revision，并 MUST 在发布时创建包含完整有效业务配置、模型连接、MCP Tool 最大集合、schema version 和 config hash 的不可变 Publication。Agent 编辑、Tool 变更或模型变更 MUST NOT 修改既有 Publication。

#### Scenario: 编辑已发布 Agent 草稿
- **WHEN** 管理员修改已发布 Agent 的业务指令、模型策略或 Tool 分配
- **THEN** 系统创建新的 Draft revision，当前和历史 Publication 保持不变

#### Scenario: 发布合法草稿
- **WHEN** 具备发布权限的管理员发布通过校验的 Draft
- **THEN** 系统创建新的不可变 Publication，并显式更新 Agent 当前发布指针

### Requirement: Agent 发布配置区分可编辑业务层和强制安全层
系统 SHALL 允许 Draft 配置业务角色/指令、已注册模型连接、执行限制、代码目录中的只读 MCP Tool 最大集合、Skill 和受控默认绑定，但 MUST NOT 允许覆盖平台安全规则、主体权限、Tool scope、Resource Deployment、SDK settings isolation、内置写工具禁用或 Secret 明文。

#### Scenario: 管理员保存业务指令
- **WHEN** 管理员修改诊断目标和报告偏好
- **THEN** 系统将内容保存在业务指令层，并在 Runtime 外层叠加强制安全规则

#### Scenario: 草稿尝试开放写工具
- **WHEN** Draft 包含 Bash、Write、Edit、任意 HTTP/SQL/Redis/LogQL、目录外 Tool 或未注册 executable tool
- **THEN** 系统拒绝校验和发布

#### Scenario: 草稿选择 MCP Tool
- **WHEN** 管理员选择代码目录中的只读 Tool Publication
- **THEN** Agent Publication 冻结该 Tool 的 ID、revision 和 Schema hash，不复制可编辑执行定义

### Requirement: Agent job 固定发布版本
系统 SHALL 在创建 Job 的数据库事务中保存 Agent definition、Publication ID、revision、config hash 和 Runtime contract version。Worker 和 retry MUST 使用 Job 固定 Publication 与 Runtime，不重新读取当前指针、Draft 或自动切换 Python/TypeScript 实现。

#### Scenario: 发布后创建 job
- **WHEN** 目标 Agent 当前 Publication 有效且用户提交请求
- **THEN** Job 在发布队列前固定 Publication 与 Runtime contract version

#### Scenario: job 排队期间发布新版本
- **WHEN** Job 已固定版本后管理员发布新 Agent revision
- **THEN** 已排队 Job 继续使用原版本，新 Job 使用新版本

#### Scenario: job 重试
- **WHEN** Job 因瞬时错误进入 retry
- **THEN** retry 仍使用原 Publication、MCP Binding 和 Runtime version

### Requirement: Agent 发布支持校验和回滚
系统 SHALL 在发布前校验模型连接、MCP Tool Publication、Skill、项目、Runtime contract 和安全边界，并 MUST 通过显式切换当前 Publication 指针回滚到仍满足当前依赖的历史 Publication。回滚 MUST 不修改历史快照，也 MUST 不自动修改任何 Business Application Publication/Deployment。

#### Scenario: 发布引用停用 Tool
- **WHEN** Draft 分配已停用、Schema hash 不匹配或非只读 Tool Publication
- **THEN** 系统拒绝发布并返回字段级安全错误

#### Scenario: 回滚 Agent
- **WHEN** 具备发布权限的管理员选择一个当前仍有效的历史 Publication
- **THEN** 系统将它设为非 Application 路径的新 Job 当前版本并记录审计，历史快照保持不变

#### Scenario: Application 仍引用旧版本
- **WHEN** Agent 当前指针已切换但活动 Application Publication 固定另一版本
- **THEN** Application 路由继续使用其固定版本，页面提示需要显式发布并激活新应用版本

### Requirement: 未发布或无效 Agent 必须 fail closed
系统 SHALL 在目标 Agent 没有启用的有效 Publication、Publication/hash/Runtime schema 不一致、模型连接或 MCP Tool 依赖失效时拒绝创建或执行新 Job，不得回退到默认 Agent、当前 Draft、全局模型配置或平台全部 Tool。

#### Scenario: Agent 尚未发布
- **WHEN** Channel/Application 请求选择没有有效 Publication 的 Agent
- **THEN** 系统返回安全配置错误且不发布 Agent Job

#### Scenario: Publication 依赖已撤权
- **WHEN** 固定 Tool、模型连接或 Runtime contract 在执行前不再有效
- **THEN** Job 失败关闭并记录安全原因，不使用其他 Agent 或 Tool 替代
