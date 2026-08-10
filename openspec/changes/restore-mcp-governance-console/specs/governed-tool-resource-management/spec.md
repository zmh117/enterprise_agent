## ADDED Requirements

### Requirement: MCP Resource Web 管理使用两态投影
系统 SHALL 在 MCP 配置中为 Database、Redis 和 Loki Resource 提供列表、详情、新建、编辑、启用和停用，页面主状态 MUST 只显示“启用”或“停用”。两态投影 MUST NOT 删除或绕过 Draft、验证、不可变 Revision、精确 Deployment、Generation 和 Last Known Good。

#### Scenario: 新建 Resource
- **WHEN** 管理员提交受支持 kind、合法安全字段和可用 Credential
- **THEN** 系统创建稳定 Resource 身份和候选 Draft，验证通过前页面显示“停用”

#### Scenario: 启用 Resource
- **WHEN** 候选 Revision 的字段、Secret、连接和只读检查均通过
- **THEN** 系统创建不可变 Revision、原子激活精确 Deployment/Generation，并在页面显示“启用”

#### Scenario: 启用失败
- **WHEN** 候选的 Secret 或技术验证失败
- **THEN** 系统保持“停用”或保留原 Last Known Good，返回脱敏错误且不产生部分有效状态

### Requirement: 编辑 Resource 必须生成新不可变版本
系统 SHALL 将 Web 编辑转换为新 Draft/Revision，MUST NOT 原地修改已发布 Revision。启用资源的编辑只有在新 Generation 完整装载后才能原子切换，失败时 MUST 保留旧有效 Generation。

#### Scenario: 编辑启用资源成功
- **WHEN** 管理员基于当前 revision 编辑启用资源且新候选完整验证成功
- **THEN** 系统创建新 Revision 并原子切换，新 Job 使用新 Generation，历史 Job 保留旧冻结引用

#### Scenario: 并发编辑冲突
- **WHEN** 管理员使用过期 expected revision 保存 Resource
- **THEN** 系统拒绝保存并要求刷新，不覆盖较新 Draft、Revision 或 Deployment

### Requirement: 停用 Resource 阻止新的运行依赖
系统 SHALL 在停用 Resource 后阻止新 Tool Publication 绑定和新 Job 解析该 Resource，且 MUST 保留历史 Revision、Deployment、Generation、Job 和审计事实。

#### Scenario: 停用存在活动依赖的 Resource
- **WHEN** 管理员确认停用被当前 Publication 引用的 Resource
- **THEN** 系统显示受影响对象、停用新的解析资格并使相关新调用 fail-closed，不改写历史 Job

### Requirement: Tool Publication 绑定精确 Resource Deployment
需要数据资源的 MCP Tool Publication SHALL 绑定零个或一个兼容的精确 Resource Deployment，并 MUST 在保存和运行时重新校验 Tool kind、Resource kind、启用状态、对象范围和 revision。该绑定 MUST NOT 承载字段映射、转换规则、自由查询或通配解析。

#### Scenario: 保存精确绑定
- **WHEN** 管理员选择与 Tool 兼容且已启用的 Resource Deployment
- **THEN** 系统保存精确 Deployment ID 并让新 Job 冻结对应 Revision/Generation

#### Scenario: Resource 后续发布新版本
- **WHEN** Resource 激活新 Revision 但 Tool Publication 没有重新发布或按契约刷新
- **THEN** 运行时遵循冻结 Publication/Deployment 语义，不解析客户端提供的浮动 latest

### Requirement: Resource 页面展示安全有效状态摘要
页面 SHALL 在两态主状态之外只读展示候选验证、当前有效 Revision/Generation、最近装载时间、依赖摘要和脱敏错误，且 MUST 明确区分“配置已保存”与“当前运行有效”。

#### Scenario: 新版本装载失败
- **WHEN** 启用 Resource 的新候选验证通过但运行装载失败
- **THEN** 页面显示旧有效版本仍在使用、新候选失败及安全错误，不误报新配置已生效

