## ADDED Requirements

### Requirement: 活动迁移目录必须从最终 Schema 基线开始
系统 MUST 使用 `100_baseline_v1.sql` 作为第一代活动 schema 基线；空 SQLite 或 PostgreSQL 数据库 MUST 直接得到与旧 001–042 完整迁移链最终状态等价的表、字段、约束、索引和适用的 PostgreSQL 中文注释，后续迁移版本 MUST 从 101 单调递增。

#### Scenario: 全新 PostgreSQL 数据库迁移
- **WHEN** Migrator 面对没有项目表和迁移记录的 PostgreSQL 数据库
- **THEN** 系统只执行活动基线及其后的迁移，并得到完整最终 schema 与 100% 项目表字段中文注释覆盖

#### Scenario: 全新 SQLite 数据库迁移
- **WHEN** 测试或本地流程对空 SQLite 数据库执行活动迁移目录
- **THEN** 系统建立与 PostgreSQL 领域结构等价的 SQLite schema，并安全跳过 PostgreSQL 专用注释语句

### Requirement: Legacy Migration Manifest 必须冻结被替换的迁移身份
仓库 MUST 保存 001–042 每个迁移的版本、文件名和 checksum，以及整个旧目录的 catalog digest 与最终 schema fingerprint；旧 SQL 不再参与活动迁移解析，legacy manifest 一旦发布 MUST NOT 被原地改写。

#### Scenario: 旧账本完全匹配 manifest
- **WHEN** Migrator 读取一个精确执行到 042 的旧账本
- **THEN** 系统逐项验证版本、名称、checksum 和 catalog digest 后才允许进入基线等价验证

#### Scenario: Manifest 或旧账本发生漂移
- **WHEN** 任一旧迁移记录缺失、重复、名称变化、checksum 不同或 manifest digest 不一致
- **THEN** Migrator 失败关闭且不得登记基线或执行后续迁移

### Requirement: 精确 042 数据库必须通过 Baseline Adoption 无损接轨
对账本精确到 042 的数据库，Migrator MUST 验证最终 schema fingerprint、PostgreSQL 注释覆盖和关键保留数据不变量，并在单一事务中登记 100 基线等价事实；系统 MUST 保留旧 ledger 记录且 MUST NOT 重放基线 DDL、清空业务数据或重置 revision。

#### Scenario: 042 数据库成功采纳基线
- **WHEN** 旧 ledger、schema、注释和数据不变量全部匹配
- **THEN** 系统记录来源 head、legacy catalog digest、schema fingerprint、100 基线 checksum 和采纳时间，并允许后续 101+ migration

#### Scenario: 042 Schema 存在漂移
- **WHEN** 账本为 042 但表、字段、约束、索引、注释或关键保留对象不符合基线
- **THEN** Baseline Adoption 失败且数据库保持原账本和原数据不变

#### Scenario: 重复执行已采纳数据库
- **WHEN** Migrator 再次处理已经登记 100 等价事实且没有新迁移的数据库
- **THEN** 系统幂等退出，不重复插入采纳记录或修改业务数据

### Requirement: 非 042 Legacy Head 必须失败关闭
活动 Migrator MUST 拒绝直接处理 001–041、空洞 ledger、无 ledger 的非空 schema 或未知旧 head，并 SHALL 提示操作人使用旧版本镜像先升级到精确 042；系统不得猜测缺失 migration 或把部分 schema 当作完整基线。

#### Scenario: 数据库只执行到 041
- **WHEN** 新 Migrator 发现合法但未达到 042 的旧账本
- **THEN** 系统不执行 100，并返回先使用旧版本升级到 042 的安全提示

#### Scenario: 非空数据库没有账本
- **WHEN** 新 Migrator 发现项目表存在但没有可验证的旧 ledger
- **THEN** 系统失败关闭，不依据表名近似匹配自动采纳基线

### Requirement: 空库编排必须在启动业务服务前完成管理员 Bootstrap
Compose 和受支持的部署脚本 MUST 按“schema migration、初始管理员 bootstrap、Runtime grants”的顺序执行；任一步失败时 Migrator 服务 MUST 非零退出，API、Worker、Runtime 和 Channel 服务不得启动。

#### Scenario: 空库完成完整初始化
- **WHEN** 部署流程首次处理空数据库
- **THEN** schema 达到当前 head、初始管理员可登录、Runtime grants 已应用后业务服务才启动

#### Scenario: 管理员 Bootstrap 失败
- **WHEN** 初始管理员缺少必需安全输入或身份写入失败
- **THEN** Compose migrator 失败且依赖 `service_completed_successfully` 的服务保持未启动
