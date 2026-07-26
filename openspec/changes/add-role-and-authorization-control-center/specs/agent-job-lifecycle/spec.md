## MODIFIED Requirements

### Requirement: Agent job status transitions are controlled
系统 SHALL 通过 job application service 控制 Agent job 状态转换，并至少支持 PENDING、RUNNING、SUCCEEDED、FAILED 和 TIMEOUT。Worker 在把 PENDING job 转为 RUNNING 前 MUST 使用 job 固定的业务应用上下文和当前用户授权重新校验；授权已撤销、角色已到期或应用访问不再成立时 MUST 以非重试权限失败终止，不得调用模型或业务能力。

#### Scenario: Worker claims pending job
- **WHEN** Agent worker 接收一个 PENDING job 且执行前授权仍有效
- **THEN** 系统把 job 转为 RUNNING、记录开始时间和授权决策

#### Scenario: Permission changed before worker claim
- **WHEN** job 排队期间用户的应用授权被撤销或成员关系到期
- **THEN** Worker 不调用模型或工具，把 job 标记为 FAILED 并记录非重试的中文安全原因

#### Scenario: Worker completes job
- **WHEN** Agent worker 产生有效最终报告
- **THEN** 系统把 job 从 RUNNING 转为 SUCCEEDED 并记录完成时间

#### Scenario: Worker hits timeout
- **WHEN** Agent worker 超过配置的执行超时时间
- **THEN** 系统把 job 转为 TIMEOUT 并记录安全超时原因

## ADDED Requirements

### Requirement: 运行中的业务能力调用重新校验当前授权
系统 SHALL 在运行中每次业务能力调用前重新校验当前角色成员状态、业务应用能力和数据范围。权限变化导致的拒绝 MUST NOT 重试，也不得访问目标数据源。

#### Scenario: 执行中撤销数据范围
- **WHEN** job 运行期间管理员撤销目标基地范围，随后 Agent 请求该基地能力
- **THEN** 系统在调用 Internal API Platform 前拒绝请求并记录授权变化

