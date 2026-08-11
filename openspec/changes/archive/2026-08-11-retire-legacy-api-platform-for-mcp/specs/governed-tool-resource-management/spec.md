## MODIFIED Requirements

### Requirement: 业务应用发布必须绑定具体 Resource Revision
业务应用发布 MUST NOT 绑定或保存 Resource Revision。工具资源保持独立发布；`tool-mcp` MUST 在每次 Tool Call 时按 Agent 提供且通过当前角色数据范围校验的目标、资源类型与可选 placement 解析唯一 Published Resource Revision，并记录实际版本。

#### Scenario: 资源发布新版本
- **WHEN** 某 Resource 发布新 revision 且旧 revision 已停用
- **THEN** 新 Tool Call 只可解析当前可用且唯一的 revision，既有 Job 若无法满足其冻结边界则失败关闭

#### Scenario: 应用尝试提交资源绑定
- **WHEN** Application Draft 或 Publish payload 包含 Resource Revision、slot 或 mapping
- **THEN** 系统拒绝旧字段且不保存兼容映射

### Requirement: 运行时必须原子热加载并保留 Last Known Good
`tool-mcp` SHALL 在单次调用内读取一个一致的资源 revision/Secret 快照并完成连接；系统 MUST NOT 维护 Internal API Platform activation 或 Application Last Known Good 映射。资源解析或连接失败时仅该 Tool Call 失败，不能回退到未授权旧 revision。

#### Scenario: 当前资源可解析
- **WHEN** 唯一 Published Resource Revision、active Secret 和驱动均可用
- **THEN** Tool Call 使用该一致快照执行并记录 revision

#### Scenario: 资源或 Secret 不可用
- **WHEN** revision 被禁用、Secret 缺失或连接初始化失败
- **THEN** Tool Call 以安全配置错误失败且不使用旧缓存或其他候选

## MODIFIED Requirements

### Requirement: 全量资源重置必须使用四阶段维护命令
系统 MUST 提供 `resource-reset report/prepare/apply/verify`，只清理 DB、Redis、Loki 资源及 revision；Provider、Secret、身份、RBAC、应用、Job、Delivery 和审计必须保留。命令 MUST 不再处理 Application Resource Binding、Resource Mapping、runtime generation 或 activation 表。

#### Scenario: Prepare 后状态发生变化
- **WHEN** apply 前的对象清单 digest 与 prepare 结果不一致
- **THEN** apply 必须拒绝并要求重新 report/prepare

#### Scenario: 仍有运行中的资源依赖 Job
- **WHEN** 维护排空超时且仍存在运行任务
- **THEN** prepare 必须中止，不得强杀任务或继续删除资源

#### Scenario: 用户确认精确清单
- **WHEN** apply 再次展示 operation ID、备份引用和精确资源清单并得到明确确认
- **THEN** 系统在单个受控事务中清理资源，不修改应用或创建 blocked 映射状态
