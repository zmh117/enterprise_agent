## ADDED Requirements

### Requirement: Baseline Adoption 部署必须先验证并保留恢复证据
当受支持的现有数据库从 legacy migration generation 采纳当前 schema baseline 时，系统 MUST 在业务服务使用新代码前完成只读 preflight、可恢复逻辑备份、one-shot Migrator adoption 和结果核验；普通业务服务、手工 SQL 和只读验证工具 MUST NOT 写入 migration ledger 或 adoption metadata。

#### Scenario: 现有部署满足受支持的 adoption 来源
- **WHEN** preflight 发现数据库 ledger、checksum、schema、注释和关键数据不变量与受支持的 legacy head 完全一致
- **THEN** 系统报告来源 head、目标 baseline、镜像或构建身份以及不含业务原文的核验摘要
- **THEN** adoption 只有在逻辑备份完成且业务写入已停止后才可由 one-shot Migrator 执行

#### Scenario: Adoption 前置条件不满足
- **WHEN** legacy ledger、checksum、schema、注释、关键数据不变量或备份核验任一失败
- **THEN** Migrator 失败关闭且不得登记 baseline marker 或 adoption metadata
- **THEN** 依赖 schema readiness 的业务服务不得以新代码启动

#### Scenario: Adoption 成功后验收
- **WHEN** one-shot Migrator 完成 adoption 且没有后续 migration 待应用
- **THEN** 验收同时核对 schema head、唯一 adoption metadata、关键表计数、配置 revision 摘要和业务服务 readiness
- **THEN** 验收结果不得包含 Secret、Token、密码或原始业务消息

#### Scenario: Adoption 后验收失败
- **WHEN** adoption 后任一数据、schema、配置或应用闭环核验失败
- **THEN** 系统保持切换前备份、旧镜像和旧数据环境可恢复，不自动删除或覆盖它们
- **THEN** 只有尚未执行后续 migration 的 adoption-only 数据库可以使用受控 rollback；其他情况必须恢复逻辑备份

### Requirement: 内置 Runtime Config Definition 对账必须语义幂等
系统 SHALL 在受控初始化或显式管理同步中对账代码内置 runtime config definition，并 MUST 以规范化后的 key、类型、默认值、敏感性、bootstrap 边界、适用服务集合、描述和状态判断语义变化。语义相同的重复对账 MUST NOT 更新记录、递增 revision、改变 `updated_at` 或生成变化审计。

#### Scenario: 重复注册完全相同的内置定义
- **WHEN** 相同构建重复启动或管理员重复同步同一组内置定义
- **THEN** 第一次已存在后的对账返回 unchanged
- **THEN** definition 行、聚合 runtime config revision/hash 和配置审计均保持不变

#### Scenario: 内置定义发生真实变化
- **WHEN** 新构建改变一个内置 definition 的任一规范化语义字段
- **THEN** 系统只更新对应 definition 并将其 revision 递增一次
- **THEN** 聚合 runtime config revision/hash 发生变化，显式管理同步记录不含敏感值的差异摘要

#### Scenario: 多个服务并发初始化
- **WHEN** 多个服务同时对账相同的内置 definition 集合
- **THEN** 唯一 key 最终只对应一条语义正确的记录
- **THEN** 每个真实创建或更新最多计入一次 revision 变化，其余竞争者重读后返回 unchanged 或安全重试

### Requirement: Runtime Config 只读路径不得隐式注册定义
Runtime config definition 列表、effective snapshot、ready diagnostics 和其他只读请求 MUST NOT 创建或更新 definition。若受控初始化没有完成，读取路径 SHALL 返回安全的缺失或 degraded 诊断，不得通过 GET、snapshot 构建或健康检查自我修复数据库。

#### Scenario: 管理员重复读取 Definition 列表
- **WHEN** 管理员连续调用 definition 列表 API 且数据库内容未变化
- **THEN** 两次响应读取同一事实，数据库写入计数、definition revision、`updated_at` 和配置审计均不变化

#### Scenario: Snapshot 发现缺少内置 Definition
- **WHEN** effective snapshot 或 ready diagnostics 发现预期内置 definition 尚未由受控初始化注册
- **THEN** 系统返回不泄漏敏感信息的 missing-definition 或 degraded 诊断
- **THEN** 读取事务不得插入 definition 或修改任何 runtime config revision

### Requirement: Runtime Config 聚合版本必须反映真实持久化变化
系统 SHALL 为 runtime config definition、value 和相关 Secret metadata 提供稳定的聚合 revision 与内容 hash。任一受支持的真实持久化变化 MUST 改变聚合版本标识；无变化对账和纯读取 MUST 保持聚合版本标识不变。调用方 MUST 将该标识视为不透明并发与观测令牌，不得依赖其具体数值。

#### Scenario: 修改低 revision 的配置值
- **WHEN** 某个 runtime config value 发生真实更新，即使其他 definition 具有更高的单行 revision
- **THEN** 聚合 revision 与有效配置 hash 按其影响发生变化，不得因取最大单行 revision 而掩盖本次更新

#### Scenario: 重复构建相同 Snapshot
- **WHEN** 数据库 definition、value 和相关 Secret metadata 均未变化而重复构建 snapshot
- **THEN** 聚合 revision 和内容 hash 保持稳定
- **THEN** 构建 snapshot 不产生数据库写入或配置审计
