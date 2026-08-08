## ADDED Requirements

### Requirement: Claude runtime consumes the job-fixed Agent publication
系统 SHALL 在执行 job 时读取 job 固定的不可变 Agent publication snapshot，并 MUST 使用其中的业务指令、模型策略、执行限制、Skill 和允许工具配置。runtime MUST NOT 读取活动草稿或执行时重新选择当前发布版本。

#### Scenario: Job executes published configuration
- **WHEN** worker 执行固定了默认诊断 Agent publication 的 job
- **THEN** AgentContextBuilder 和 RealClaudeCodeAgentClient 使用该 snapshot 构建运行上下文

#### Scenario: Publication changes during execution
- **WHEN** 管理员在 job 运行期间发布新版本
- **THEN** 当前 job 继续使用固定 snapshot，新版本不改变本次 prompt、工具或执行限制

### Requirement: 可编辑业务指令不能覆盖强制安全规则
系统 SHALL 把 publication 中的业务指令作为受控配置层，并 MUST 在其外层强制叠加平台安全规则、只读工具限制、数据权限和 SDK 内置写工具禁用。

#### Scenario: 业务指令包含越权文本
- **WHEN** 已发布业务指令要求忽略权限、执行 Bash、修改数据库或泄漏 secret
- **THEN** runtime 拒绝无效 publication 或保持平台安全规则优先，且不执行越权动作

### Requirement: Agent publication 只能引用已注册模型策略
系统 SHALL 允许 Agent publication 选择已注册且启用的模型策略与执行参数，但 MUST NOT 在 Agent snapshot 中保存 API key、认证 token、任意 secret 明文或不受管 provider URL。

#### Scenario: 默认 Agent 选择模型策略
- **WHEN** 管理员为默认 Agent 选择一个引用 DB-backed runtime config/secret 的模型策略
- **THEN** publication 保存非敏感策略引用，runtime 在基础设施层解析实际凭证
