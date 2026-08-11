## ADDED Requirements

### Requirement: 最终项目 Schema 必须具有完整中文注释
系统 MUST 通过向前迁移为 PostgreSQL `public` schema 中最终保留的每张项目自有表和每个字段设置非空中文注释；注释 SHALL 描述领域含义、关联对象、状态、版本、时间或安全边界，不得使用统一无语义占位文本。`schema_migration` 迁移账本、PostgreSQL 系统表和第三方扩展表不属于项目注释范围。

#### Scenario: 已有数据库升级
- **WHEN** 已执行到前一 schema head 的 PostgreSQL 数据库升级
- **THEN** 所有最终保留的项目表和字段都具有非空中文 comment，业务数据、约束和索引保持不变

#### Scenario: 新迁移增加表或字段
- **WHEN** 后续迁移新增项目自有表或字段但没有同步声明注释
- **THEN** schema 注释覆盖测试失败并阻止发布

#### Scenario: SQLite 运行迁移
- **WHEN** 测试或本地环境使用 SQLite 执行同一迁移目录
- **THEN** PostgreSQL `COMMENT ON` 语句被兼容跳过，最终 SQLite schema 仍与静态注释清单进行完整性对照
