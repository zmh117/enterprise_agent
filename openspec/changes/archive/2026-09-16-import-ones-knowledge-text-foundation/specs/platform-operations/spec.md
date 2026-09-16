## ADDED Requirements

### Requirement: 知识存储通过统一来源身份和独立收录关系管理
系统 SHALL 在同一平台 PostgreSQL 的 knowledge schema 中保存 source、document、document_revision、knowledge_base、knowledge_base_document、import_run 和 document_relation。来源工作项身份 MUST 独立于知识库和可变工作项类型，内容版本 MUST 可追溯，收录 MUST NOT 自动产生 Agent 或用户读取授权。

#### Scenario: 同一来源内容被多个知识库收录
- **WHEN** 相同来源工作项进入两个知识库
- **THEN** 系统复用稳定 document 和内容版本并建立不同收录关系，不复制来源文档

#### Scenario: 来源团队未确认
- **WHEN** 本地导出缺少可信团队或实例身份
- **THEN** 系统仅记录来源未确认的离线命名空间，不猜测或接续现有 ONES 身份

### Requirement: ONES 离线文本导入必须预检并可恢复且幂等
导入 CLI MUST 校验详情/list 完整关联、重复身份、数据形状及显式输入数量；MUST 分开 ID 和显示名称，保留受限安全快照、正文、业务属性、采集完整性及版本。批次 MUST 具有输入摘要、明确进度和安全失败事实；相同输入重放 MUST NOT 增加重复文档或版本，旧来源版本 MUST NOT 覆盖新版本。导入 MUST NOT 下载附件、调用 ONES/Embedding/OCR、写 Qdrant 或发布资源。

#### Scenario: 导入五千条已声明缺陷
- **WHEN** 用户指定预检通过的详情/list 导出且声明主记录都是缺陷
- **THEN** 系统保存五千条 defect 文档和收录，相关工单引用不得被生成为缺陷正文

#### Scenario: 中途停止后重放
- **WHEN** 导入在已提交部分文档后中断并使用同一输入再次运行
- **THEN** 系统从持久批次进度恢复，已完成记录不重复写入

#### Scenario: 安全边界
- **WHEN** 来源字段包含可访问 URL、Base64 或明显凭据
- **THEN** 系统在入库前移除敏感片段，命令结果与日志只提供安全统计和错误码，原始输入不修改

### Requirement: 工作项关联必须保留外部身份和来源证据
系统 MUST 保存原始关联类型/方向、来源快照及两端外部身份；关联目标尚未导入时 MUST 保持内部目标 ID 未解析，不创建虚假正文。目标后续导入时 SHALL 补齐引用。未确认完整的关联集合 MUST NOT 用于推断关系删除或推断因果语义。

#### Scenario: 目标正文尚未入库
- **WHEN** 缺陷引用一个未导入的工单
- **THEN** 系统保留工单外部身份和原始关联观察，并标识未解析状态

#### Scenario: 重复或过时关联观察
- **WHEN** 同一来源版本的关系再次被导入或旧文件被重放
- **THEN** 系统幂等保存，不把旧观察伪装成当前完整关系集合

### Requirement: 知识 schema 必须纳入现有迁移与事实源治理
knowledge DDL MUST 仅通过一次性 Migrator 的版本化事务执行。结构、约束、索引、注释和事实源清单 MUST 覆盖 public 与 knowledge；SQLite 测试 SHALL 保持等价领域对象且不得影响现有表。导入器 MUST 只检查 schema head，不执行迁移。

#### Scenario: 新 schema 建表后验收
- **WHEN** 新迁移执行完成
- **THEN** PostgreSQL 真实存在七张 knowledge 表且结构检查、中文注释覆盖和事实源清单能够识别全部对象

## MODIFIED Requirements

### Requirement: 最终项目 Schema 必须具有完整中文注释
系统 MUST 通过向前迁移为 PostgreSQL public 和 knowledge schema 中最终保留的每张项目自有表和每个字段设置非空中文注释；注释 SHALL 描述领域含义、关联对象、状态、版本、时间或安全边界，不得使用统一无语义占位文本。schema_migration 迁移账本、PostgreSQL 系统表和第三方扩展表不属于项目注释范围。

#### Scenario: 已有数据库升级
- **WHEN** 已执行到前一 schema head 的 PostgreSQL 数据库升级
- **THEN** 所有最终保留的项目表和字段都具有非空中文 comment，业务数据、约束和索引保持不变

#### Scenario: 新迁移增加表或字段
- **WHEN** 后续迁移新增项目自有表或字段但没有同步声明注释
- **THEN** schema 注释覆盖测试失败并阻止发布

#### Scenario: SQLite 运行迁移
- **WHEN** 测试或本地环境使用 SQLite 执行同一迁移目录
- **THEN** PostgreSQL COMMENT ON 语句被兼容跳过，最终 SQLite schema 仍与静态注释清单进行完整性对照
