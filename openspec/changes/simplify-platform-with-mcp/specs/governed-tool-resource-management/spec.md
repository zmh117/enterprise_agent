## ADDED Requirements

### Requirement: MCP Resource Deployment 必须绑定精确 Resource Revision
每个 `server_code + resource_code` 在一个环境中 MUST 至多存在一个活动 MCP Resource Deployment，且 MUST 指向一个精确 Published Resource Revision；新 Job 与 Tool Call MUST 冻结 Deployment ID 和 Resource Revision ID，不得解析浮动 `latest`。

#### Scenario: 发布资源新 Revision
- **WHEN** 管理员验证并激活数据库 Resource Revision 2
- **THEN** 新 Job 冻结 Revision 2，已有 Job 不自动改写其精确 Revision 事实

#### Scenario: 取消发布
- **WHEN** 管理员通过 CLI 禁用活动 Deployment
- **THEN** 新调用和重试立即失败关闭，已经发送的单次上游请求可以完成

## MODIFIED Requirements

### Requirement: 工具资源必须通过草稿、验证和发布生命周期
DB、Redis、Loki Resource MUST 具有稳定身份、可编辑 Draft、技术验证结果、不可变 Published Revision 和精确 MCP Resource Deployment；正常 CLI 路径为 `plan → apply Draft → verify → publish Revision → activate Deployment`，`apply` MUST NOT 隐式发布。

#### Scenario: 发布已验证草稿
- **WHEN** 授权发布者通过 CLI 发布字段、Secret、连接和只读检查均通过的 Draft
- **THEN** 系统创建新的不可变 Revision、原子激活精确 Deployment，并记录发布者、内容 Hash 和审计

#### Scenario: 发布未验证草稿
- **WHEN** Draft 尚未验证或验证结果已因内容变化失效
- **THEN** 系统拒绝发布和激活

### Requirement: 运行时必须原子热加载并保留 Last Known Good
Data MCP SHALL 根据活动 Deployment、精确 Resource Revision 和 Secret active version 完整构建不可变 generation 后原子切换；加载失败 MAY 保留同一 Resource Revision 的 Last Known Good，但 MUST NOT 使用另一历史 Revision 替代 Job 冻结事实。

#### Scenario: 新 generation 加载成功
- **WHEN** 新活动 Revision 的 Secret 与驱动均可解析
- **THEN** 进行中请求继续使用原 generation，新请求使用新 generation

#### Scenario: Secret 轮换加载失败
- **WHEN** 同一 Resource Revision 的新 Secret 版本初始化失败且存在精确 LKG
- **THEN** Runtime 保留该 Revision 的 LKG，将资源标为 degraded并记录脱敏错误

#### Scenario: 精确 Revision 没有 LKG
- **WHEN** Job 需要的 Revision 从未成功装载
- **THEN** 仅相关 Tool Call 被阻断，Runtime 不浮动到其他 Revision

## REMOVED Requirements

### Requirement: 业务应用发布必须绑定具体 Resource Revision
**Reason**: 复杂 Application Tool Resource Composition 随旧平台数据直接删除，资源精确性改由 MCP Resource Deployment 和 Job 快照承担。

**Migration**: 不转换旧绑定；DB、Redis、Loki 通过新声明式文件和 CLI 从空状态发布。

### Requirement: 工具资源管理界面必须展示实际生效状态
**Reason**: 前端收缩为身份、历史和调试，不再承载资源运维。

**Migration**: 使用 `platformctl resource status` 查看 Draft、Published、Effective、Deployment 与安全错误。

### Requirement: 全量资源重置必须使用四阶段维护命令
**Reason**: 旧资源数据在本次破坏性切换中直接删除，不需要保留旧 Reset、备份引用或兼容历史。

**Migration**: 不执行旧 reset；切换后只允许通过新 CLI 从空状态创建资源。
