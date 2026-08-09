## MODIFIED Requirements

### Requirement: 发布前执行跨组件完整校验
系统 MUST 在创建 Business Application Publication 前校验应用状态、Draft、Agent Publication、MCP Tool Publication 子集、Tool Schema hash/scope、Resource Deployment/Revision、Channel、Trigger、Actor、Delivery、项目范围、Runtime contract 和策略约束。任何依赖无效时 MUST 拒绝整个发布。

#### Scenario: 发布合法草稿
- **WHEN** enabled 应用引用有效 Agent、其允许的 MCP Tool 子集、active Resource、合法入口/投递和策略
- **THEN** 系统将 revision 标记为校验通过并允许创建不可变 Publication

#### Scenario: 引用已禁用或不存在组件
- **WHEN** Draft 引用不存在、停用、hash 不匹配、范围冲突或 schema 不兼容的组件
- **THEN** 系统返回按字段/组件分类的全部安全错误且不创建部分 Publication

#### Scenario: 引用旧 Capability
- **WHEN** 请求包含已删除 Capability/Handler/Connection
- **THEN** 系统拒绝并且不把它映射为任何 MCP Tool

### Requirement: 发布创建不可变且可验证的应用快照
系统 SHALL 在单一事务创建不可变 Application Publication，冻结应用元数据、Agent Publication、MCP Tool Publication、Resource Deployment/Revision、Channel/Trigger/Delivery、策略、Runtime contract、各 revision/hash 和 canonical SHA-256。快照 MUST 不包含 Secret、Token、认证 Header 或连接信息。

#### Scenario: 创建应用发布快照
- **WHEN** 合法 revision 首次发布
- **THEN** 系统保存完整非敏感组件版本、schema version、hash、来源 revision 和发布主体

#### Scenario: 组件后续产生新版本
- **WHEN** Agent、Tool、Resource 或 Channel 后续产生新版本
- **THEN** 已有 Application Publication 保持原精确引用，只有新 Application Publication 可采用新版本

#### Scenario: 检测快照篡改
- **WHEN** canonical hash 不一致或 schema/Runtime contract 不受支持
- **THEN** 系统拒绝解析、激活和 Job 创建，并记录脱敏完整性失败审计

### Requirement: 发布与环境激活相互分离
系统 SHALL 允许 Publication 在不影响环境的情况下创建，并 MUST 通过显式、带 expected revision 的 Deployment 操作激活。激活 MUST 重新校验 Agent、Tool、Resource、Channel、Runtime readiness 和 Trigger 冲突。

#### Scenario: 仅发布不激活
- **WHEN** 管理员发布 revision
- **THEN** Publication 进入历史但环境 Deployment 和 Resolver 保持不变

#### Scenario: 激活到测试环境
- **WHEN** 管理员以正确 expected revision 激活仍有效 Publication
- **THEN** test Deployment 原子切换，production 不受影响

#### Scenario: Tool 在发布后已停用
- **WHEN** 激活时某 MCP Tool Publication 已停用
- **THEN** 激活失败且现有 Deployment 保持不变

### Requirement: Resolver确定性读取活动应用
系统 SHALL 按 application/environment 和规范化 Trigger 键解析唯一活动 Publication，并 MUST 返回固定 Agent、Runtime contract、MCP Tool/Resource、Channel、策略与完整性摘要。未激活、停用、冲突、撤权或完整性失败 MUST 返回明确非重试配置错误，不得选择其他应用或 Tool。

#### Scenario: 按应用解析活动发布
- **WHEN** 调用方读取 enabled 应用在 test 的有效配置
- **THEN** Resolver 返回唯一 Publication 及精确组件摘要，不包含 Secret 或外部凭据

#### Scenario: 两个应用使用不同 Tool 子集
- **WHEN** 同一 Agent 被两个路由唯一的活动应用引用
- **THEN** 每个路由只返回其 Application Publication 固定 Tool 子集

#### Scenario: 没有有效部署
- **WHEN** 应用未激活、停用、Tool 撤权或完整性失败
- **THEN** Resolver 失败关闭且不回退默认应用

### Requirement: 历史publication可以显式重新激活
系统 SHALL 允许有权限用户重新激活仍通过当前依赖和完整性校验的历史 Publication，并 MUST 支持显式停用环境。重新激活 MUST 不修改历史快照。

#### Scenario: 回退到历史版本
- **WHEN** 用户选择仍合法的历史 Publication 并激活
- **THEN** Deployment 原子指向历史版本并审计旧/新 ID

#### Scenario: 历史版本的 Tool 已撤权
- **WHEN** 历史 Publication 引用当前已停用的 Tool/Resource
- **THEN** 系统拒绝激活并要求创建新 Draft，而不是忽略失效依赖

### Requirement: 发布和解析过程不得保存或暴露凭据
系统 MUST 只在 Application snapshot、Deployment、Resolver、API和审计中保存非敏感组件 ID/revision/hash 和 configured 状态，MUST NOT 保存或返回模型 Key、MCP Token、Provider Token、Secret ref/value、完整 URL、密码或连接材料。

#### Scenario: 发布包含需凭据组件
- **WHEN** 应用引用模型、ONES、钉钉或数据资源
- **THEN** snapshot 只保存非敏感版本和绑定标识，凭据由实际运行边界解析

#### Scenario: 查看发布历史
- **WHEN** 管理员读取 Publication 详情
- **THEN** API 返回版本、hash、组件和审计摘要，不返回任何可重放认证材料
