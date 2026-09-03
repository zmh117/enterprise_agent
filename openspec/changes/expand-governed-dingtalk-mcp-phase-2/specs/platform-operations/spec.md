## ADDED Requirements

### Requirement: Phase 2 Provider 配置必须固定且按工具就绪
平台 SHALL 继续以代码固定 `dingtalk-mcp` 与 Provider operation 注册表运行，不读取 `ACTIVE_PROFILES` 或动态 YAML。Connector Secret 只由基础设施解析；工作通知 Tool 还 MUST 要求 Connector 具有合法非敏感 `work_notification_agent_id`，机器人 Tool MUST 具有可解析 robot code 和当前来源路由。

#### Scenario: Connector 缺少工作通知 Agent ID
- **WHEN** Publication 选择工作通知发送或状态 Tool，但 Connector 没有合法正整数 Agent ID
- **THEN** 发布、激活或运行就绪检查失败关闭并给出稳定配置提示

#### Scenario: 环境变量包含官方 Profile
- **WHEN** Compose 或进程环境设置 `ACTIVE_PROFILES`
- **THEN** 固定服务忽略该变量且 readiness 展示的工具数不发生变化

#### Scenario: mutation 应用缺少确认卡模板
- **WHEN** 业务应用选择任一 `confirmation_policy=external_action_card_v1` 的 Tool，但其已启用钉钉来源 Connector 未配置 `external_action_confirmation` 或合同版本不兼容
- **THEN** 发布或激活失败关闭并指出缺少外部操作确认卡片模板；纯只读 Tool 不受该配置缺失影响

### Requirement: 钉钉权限不足必须形成精确降级事实
系统 SHALL 为 contacts、department、tasks、calendar、notable、robot 和 notice 的固定 Provider 操作维护所需权限说明，并把权限不足分类为对应 Tool/Profile 的稳定非重试错误。单个 Profile 权限不足 MUST NOT 使已满足依赖的其它 Tool 绕过授权或被误报为不可用。

#### Scenario: Calendar 权限缺失
- **WHEN** 钉钉应用缺少当前 calendar Tool 所需权限
- **THEN** 该调用返回稳定权限错误并记录安全 Provider attempt，其它已授权 Profile 保持独立

#### Scenario: mutation 写权限缺失
- **WHEN** 用户已确认但 Provider 明确拒绝对应写权限
- **THEN** Intent 进入 FAILED 而不是自动重试或改用其它 endpoint/Credential

### Requirement: 外部操作 worker 必须按固定 operation 注册表就绪
external action worker SHALL 在启动和 health/readiness 中验证所有已发布 DingTalk mutation 的 Tool/operation/handler 一一对应，且现有 `dingtalk_create_todo` 和旧 Intent 仍可分派。未知、重复、缺失或 schema/policy 不一致 MUST 使 mutation readiness 失败关闭。

#### Scenario: 新 Tool 没有执行 handler
- **WHEN** Manifest 注册 mutation Tool 但 operation registry 没有唯一 handler
- **THEN** worker readiness 为 degraded，平台不得发布或激活该 Tool

#### Scenario: 旧创建待办 Intent 在升级后执行
- **WHEN** 升级前已批准的合法 `dingtalk_create_todo` Intent 被新版 worker claim
- **THEN** worker 使用兼容 handler 完成既有语义，不要求重新创建 Intent

### Requirement: Phase 2 上线必须验证真实读写链路
上线证据 SHALL 使用全新 Job 和当前 Publication/角色快照，至少覆盖每个只读 Profile 的真实成功或明确权限拒绝，以及待办、日历、AI 表格记录、机器人消息和工作通知 mutation 的确认同意与拒绝。验收 MUST 关联 Job、Tool Call、Action Intent、卡片、Provider attempt 和终态，并不得保存 Secret 或无界业务正文。

#### Scenario: 只读 Profile 验收
- **WHEN** 运维执行联系人、部门、待办、日历、AI 表格和通知状态的代表性真实查询
- **THEN** 证据区分成功、外部无数据和明确权限不足，不以 health 代替 Tool 调用

#### Scenario: mutation 拒绝验收
- **WHEN** 原用户在任一新 mutation 确认卡选择拒绝
- **THEN** 证据显示 Intent 为 REJECTED、Provider 写入 attempt 为零且卡片进入不会执行终态

#### Scenario: mutation 同意验收
- **WHEN** 原用户确认代表性的待办、日历、AI 表格、机器人消息或工作通知操作
- **THEN** 证据可从 Tool Call 追溯到唯一 Provider attempt 与真实外部结果
