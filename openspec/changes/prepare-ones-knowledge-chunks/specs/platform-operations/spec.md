## ADDED Requirements

### Requirement: 知识清洗分块必须作为来源版本的可追溯派生结果
系统 MUST 在 knowledge.document_chunk_set 与 knowledge.document_chunk 保存来源版本及规则配置对应的完整派生结果，MUST NOT 覆盖 document_revision。每个片段 MUST 区分 evidence_text 与 embedding_text，保存版本、摘要、顺序、类型及明确坐标系的来源位置。

#### Scenario: 追溯片段事实
- **WHEN** 校验任意已生成片段
- **THEN** evidence_text 等于同一集合 normalized_fields 中所声明字段的字符区间切片，并可通过 document_revision_id 回溯原版本

#### Scenario: 来源版本或分块规则更新
- **WHEN** 当前来源版本或分块配置变化
- **THEN** 系统创建新的派生集合而不覆盖历史结果，历史结果不得被静默当作当前文档块

### Requirement: 文本分块必须保留短文完整性和长文覆盖
v1 SHALL 优先完整保留不超过 1,200 字符的正文，长文按结构边界拆分，证据块不超过 1,200 字符且重叠不超过 120。系统 MUST 保留正文非空白内容、错误码和代码缩进，不得靠截断尾部满足预算；有效解决方案 SHALL 独立分块，明确状态占位及与正文完全重复的方案 SHALL 标记原因而不生成重复方案块。

#### Scenario: 短缺陷
- **WHEN** 规范化正文不超过 1,200 字符
- **THEN** 正文生成一个完整问题块，不强行切碎；有效方案可另行生成方案块

#### Scenario: 超长日志或代码
- **WHEN** 完整结构超过单块预算
- **THEN** 优先按行分块，极端长行可有标记地硬切，所有非空白字符仍有证据覆盖

#### Scenario: 只有图片或占位解决方案
- **WHEN** 来源包含未采集图片或明确状态占位方案
- **THEN** 系统记录质量标记，不推断图片内容、根因或不存在的解决步骤

### Requirement: 待向量化文本必须有界且不增加事实
embedding_text MUST 由已存在字段与 evidence_text 通过版本化模板确定性生成，v1 上限为 1,800 字符。上下文裁剪 MUST 标记且不得裁剪证据。系统 MUST 明确字符预算不代表已验证 Embedding 模型 token 上限；本阶段 MUST NOT 调用模型、下载附件、写 Qdrant、发布 MCP 或扩大权限。

#### Scenario: 方案块补足上下文
- **WHEN** 生成一个方案块的 embedding_text
- **THEN** 可添加原有标题、模块与问题片段，不生成来源中不存在的摘要或结论

### Requirement: 知识派生批处理必须幂等可恢复且不泄漏正文
CLI MUST 使用有界分页处理当前有效收录，默认只读预检，显式提交才写入。单个文档集合和全部块 MUST 在同一事务完成；重复运行 MUST 校验并复用既有完整结果，失败重跑 MUST NOT 重复写入已成功结果。日志 MUST 仅包含安全统计、标记及固定错误码，示例 MUST 使用合成内容。

#### Scenario: 中断后重跑
- **WHEN** 部分文档已提交后进程中断
- **THEN** 重跑复用已完成且内容匹配的集合，继续其余文档，不留下半组可用结果

#### Scenario: 文档失效或移出知识库
- **WHEN** 文档不再 active、收录不再 included 或当前版本改变
- **THEN** 写入前复查失败或跳过该次陈旧输入，不将旧集合宣称为当前有效块

#### Scenario: 正式全量验收
- **WHEN** 对批准的 5,000 条缺陷完成提交及重放
- **THEN** 报告文档覆盖、块数/长度/类型、质量标记与失败数，验证来源七表未变、块来源位置正确且重放不增量

## MODIFIED Requirements

### Requirement: 知识 schema 必须纳入现有迁移与事实源治理
knowledge DDL MUST 仅通过一次性 Migrator 的版本化事务执行。结构、约束、索引、注释和事实源清单 MUST 覆盖 public 与 knowledge；SQLite 测试 SHALL 保持等价领域对象且不得影响现有表。导入器及分块器 MUST 只检查 schema head，不执行迁移。

#### Scenario: 新 schema 建表后验收
- **WHEN** 新迁移执行完成
- **THEN** PostgreSQL 基础七表及 document_chunk_set、document_chunk 均真实存在，结构检查、中文注释覆盖和事实源清单能够识别全部对象
