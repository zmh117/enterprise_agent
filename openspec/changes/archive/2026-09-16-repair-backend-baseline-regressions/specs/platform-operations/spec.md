## ADDED Requirements

### Requirement: 表重建 migration 必须恢复仍生效的约束与索引

系统使用前向 migration 重建已有表时，MUST 在同一 migration 结果中恢复所有仍由 canonical domain 要求的唯一约束、检查约束和索引，并 MUST 验证 SQLite 与 PostgreSQL 的最终业务不变量等价。后续发现已发布 migration 遗漏约束时，系统 MUST 通过新版本前向 migration 修复，不得原地修改已应用 migration。

#### Scenario: SQLite 重建外部身份表
- **WHEN** migration 为调整某一 provider 的身份生命周期而在 SQLite 重建共享外部身份表
- **THEN** 最终 schema 仍强制执行其它 provider 已接受的主体唯一性和当前用户绑定唯一性

#### Scenario: 已发布 migration 遗漏唯一索引
- **WHEN** 当前 migration head 已发布且后续验证发现一个 canonical 唯一索引缺失
- **THEN** 系统分配新的唯一 migration 版本幂等恢复索引，不修改旧 migration 文件或 checksum

#### Scenario: 恢复唯一索引时存在冲突数据
- **WHEN** 前向 migration 创建唯一索引时检测到不满足不变量的既有数据
- **THEN** migration 整体失败且不登记新 head，不得静默删除、合并或选择任一业务记录

### Requirement: 内置初始化 fixture 必须保持跨 Publication 引用自洽

版本控制下用于本地或测试初始化的内置 fixture SHALL 保持所有 Publication ID、revision、config hash 和 snapshot 派生引用自洽。更新被引用 Publication 的冻结事实时，维护者 MUST 同步重新生成同一 fixture 图中的依赖快照，或创建新的 Publication 并显式切换引用；运行时完整性校验不得为兼容坏 fixture 而放宽。

#### Scenario: Fresh bootstrap 初始化默认 Webhook
- **WHEN** 空数据库应用当前 migration 并载入默认 Agent 与 Webhook Trigger fixture
- **THEN** Trigger Publication 冻结的 Agent publication ID、revision 和 config hash 与被引用 Agent Publication 完全一致

#### Scenario: 默认 Agent fixture 的 hash 变化
- **WHEN** 维护者更新默认 Agent Publication snapshot 并导致 config hash 变化
- **THEN** 跨 Publication 完整性测试在所有依赖 fixture 同步前失败，并且 Dispatcher 继续拒绝不一致快照
