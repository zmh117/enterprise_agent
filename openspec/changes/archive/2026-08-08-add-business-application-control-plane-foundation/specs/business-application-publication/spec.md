## ADDED Requirements

### Requirement: 发布前执行跨组件完整校验
系统 MUST 在创建 Business Application Publication 前校验应用状态、草稿完整性、Agent Publication、Workflow Publication、Channel Connector、Trigger、Actor、Delivery、Capability、项目范围和策略约束。

#### Scenario: 发布合法草稿
- **WHEN** enabled应用的草稿引用有效且范围兼容的已发布组件，并且所有策略通过校验
- **THEN** 系统将该 revision 标记为校验通过并允许创建 publication

#### Scenario: 引用已禁用或不存在的组件
- **WHEN** 草稿引用不存在、已禁用、完整性校验失败或项目范围冲突的组件
- **THEN** 系统拒绝发布并返回按字段和组件分类的校验结果
- **AND** 不创建部分 publication

#### Scenario: 未解析Capability
- **WHEN** 草稿包含当前 Capability Catalog 无法解析的编码或版本
- **THEN** 系统拒绝发布并指出未解析的 Capability
- **AND** 不把该编码映射为现有数据库、Redis或Loki内部工具

### Requirement: 发布创建不可变且可验证的应用快照
系统 SHALL 为每次成功发布创建不可变 snapshot，冻结应用元数据、组件 Publication ID、组件 revision/version、组件 hash、Trigger、Delivery、Capability引用和策略，并 MUST 保存 snapshot schema version 与 canonical SHA-256。

#### Scenario: 创建应用发布快照
- **WHEN** 合法 revision 首次发布
- **THEN** 系统在单一事务中创建 publication、保存 snapshot 与 hash 并记录发布审计
- **AND** publication 关联其来源 revision 和发布主体

#### Scenario: 组件后续产生新版本
- **WHEN** 被引用 Agent 或 Workflow 后续发布新版本
- **THEN** 已有应用 publication 仍引用原 Publication ID、revision 和 hash
- **AND** 只有新的应用 revision 和 publication 才能采用新组件

#### Scenario: 检测快照篡改
- **WHEN** 读取 publication 时重新计算的 canonical hash 与保存值不一致或 schema version 不受支持
- **THEN** 系统拒绝解析、激活或返回其作为有效配置
- **AND** 记录不包含快照敏感内容的完整性失败审计

### Requirement: 发布与环境激活相互分离
系统 SHALL 允许 publication 在不影响任何环境的情况下创建，并 MUST 通过显式 deployment 操作将一个有效 publication 激活到指定环境。

#### Scenario: 仅发布不激活
- **WHEN** 管理员成功发布一个应用 revision
- **THEN** publication 出现在历史中但所有环境 deployment 保持原值
- **AND** Resolver 不会因为发布本身自动选择该版本

#### Scenario: 激活到测试环境
- **WHEN** 有 activate 权限的用户将有效 publication 激活到 test 环境并携带正确 expected revision
- **THEN** 系统原子更新该应用 test deployment
- **AND** production环境 deployment 不受影响

### Requirement: 环境激活拒绝Trigger路由冲突
系统 MUST 在激活时使用 environment、trigger type、connector ID 和规范化 routing key 检查所有活动 deployment，并 SHALL 拒绝导致非确定性路由的冲突。

#### Scenario: 激活唯一Trigger
- **WHEN** publication 的每个 Trigger 在目标环境都没有被其他活动应用占用
- **THEN** 系统允许激活并建立唯一解析投影

#### Scenario: 两个应用争用同一路由键
- **WHEN** 另一个已激活应用已经占用相同 environment、trigger type、connector ID 和 routing key
- **THEN** 系统拒绝激活并返回冲突应用的安全标识
- **AND** 目标环境现有 deployment 保持不变

### Requirement: Resolver确定性读取活动应用
系统 SHALL 提供按 application code 与 environment，以及按规范化Trigger键解析活动 publication 的只读端口，并 MUST 对停用、未激活、冲突和完整性失败返回明确配置错误。

#### Scenario: 按应用解析活动发布
- **WHEN** 调用方查询一个enabled应用在test环境的有效配置
- **THEN** Resolver返回唯一publication、Agent/Workflow引用、Trigger、Delivery、Capability引用、策略和完整性摘要
- **AND** 响应不包含Secret或外部系统凭据

#### Scenario: 按Trigger解析活动应用
- **WHEN** 调用方使用唯一的environment、trigger type、connector ID和routing key查询
- **THEN** Resolver返回唯一业务应用及其活动publication

#### Scenario: 没有有效部署
- **WHEN** 应用在目标环境未激活、已停用或publication完整性失败
- **THEN** Resolver返回非重试配置错误
- **AND** 不回退到任意其他业务应用

### Requirement: 历史publication可以显式重新激活
系统 SHALL 允许有权限的用户把仍然有效的历史 publication 重新激活到环境以实现回退，并 MUST 支持显式停用环境 deployment。

#### Scenario: 回退到历史版本
- **WHEN** 用户选择一个通过当前完整性和依赖校验的历史 publication 并激活
- **THEN** deployment原子指向该历史 publication
- **AND** 系统记录旧、新publication ID和操作人

#### Scenario: 停用环境部署
- **WHEN** 用户对当前deployment执行deactivate并提供正确expected revision
- **THEN** 系统将该环境标记为未激活并移除活动路由投影
- **AND** publication历史保持不变

### Requirement: 发布和解析过程不得保存或暴露凭据
系统 MUST 只在应用 snapshot、deployment、Resolver结果和审计中保存非敏感组件标识与Secret引用，MUST NOT 保存或返回真实密码、Token、Webhook Secret、完整敏感URL或底层数据源连接。

#### Scenario: 发布包含connector引用的应用
- **WHEN** 应用引用需要凭据的钉钉、Webhook或未来API平台connector
- **THEN** snapshot只保存connector ID和非敏感策略
- **AND** 凭据继续由connector或Credential边界解析

#### Scenario: 查看发布历史
- **WHEN** 管理员读取publication列表或详情
- **THEN** API返回版本、hash、组件引用、环境和审计摘要
- **AND** 不返回任何Secret值或可直接访问外部系统的认证材料
