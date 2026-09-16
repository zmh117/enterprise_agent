## Context

现有 PostgreSQL 平台迁移到 130，尚无 knowledge schema。用户批准导入本地详情/list 两个 JSONL 中的 5,000 条缺陷，延后附件、OCR、向量和 Agent 使用。两份导出按工作项 uuid 关联，详情中的 project/status/sprint 字段可能为显示名称；关联目标多数未出现在本批正文中。

## Goals / Non-Goals

**Goals:** 通用知识身份、不可变内容版本、知识库收录关系、来源关联事实、可重复和可恢复的安全离线导入，以及真实 PostgreSQL 验收。

**Non-Goals:** 实时 ONES 同步、下载文件、OCR、向量分块/索引、MCP、Web 管理、发布与授权实施、自动推断工作项关系的业务含义。

## Decisions

1. PostgreSQL 使用显式限定的 knowledge 七张表；SQLite 测试使用带点的引号表名（如 `"knowledge.document"`）表达同一逻辑对象，不改变现有 public 访问或全局 search_path。迁移使用已有 postgres-only/sqlite-only 方言标记，不新增任意 SQL 重写器。
2. 来源与知识库分离。source 命名空间稳定，document 按 source/object_type/external_id 去重，不把可变化的 defect/ticket/requirement 类型放入身份。knowledge_base_document 建立多对多收录，本阶段知识库固定为存储专用，不产生任何运行授权。
3. 本批没有可靠实例/团队标识，source 标记为离线来源未确认，禁止自动绑定现有 ONES 身份。所有主记录由用户声明为 defect，相关工作项仅保留引用，绝不按主记录类型把关联工单也生成缺陷正文。
4. 详情和 list 一次预检后导入。每条文档、版本、关联观察和批次进度在一个事务中提交；批次以文件哈希及导入配置签名识别，重新执行恢复未完成进度。先完成整批结构校验，避免损坏/重复输入造成部分误导入。来源锁防止并发导入相互覆盖。
5. 原始文件不改动。入库快照为递归安全清洗后的 JSON，剥离所有可访问 URL、Base64、敏感键及明显凭据行，富文本转安全文本，仅保留图片 ID/出现位置；日志和验收不输出正文/名称/来源 ID/异常参数。正文优先保留纯文本 desc，不把代码和日志误当 HTML 标签解析。
6. content_hash 覆盖规范化来源内容和 normalizer version；重复不建新版本，正文变化创建新 revision 并移动同文档 current 指针。旧来源更新时间不得覆盖当前版本。缺失更新时间不能被当作更新时间较新。数据库外部 ID 为 text，内部 ID 为 UUID 字符串；PostgreSQL 内容使用 JSONB 和 timestamptz。
7. document_relation 保存带精确 evidence_revision_id 的来源关联观察、原始关系类型/方向及两端外部身份；只在契约确定时映射方向，不推断因果/实现/阻塞语义。当前未证实关系集合完整，导入不自动删除历史关系；有效观察由当前文档版本限定。目标导入后补齐本地 ID，保留原始目标身份。
8. source_snapshot/attributes/completeness 保存图片与讨论未采集事实，不建立 OCR 任务。source 与 knowledge_base 的存储状态不等于 Published 资源，不绕过未来角色治理。
9. 扩展 schema snapshot、注释和 fact-source catalog 对 knowledge 限定名的识别，public 的历史 fingerprint 形状保持不变；新旧引擎迁移均测试。实库由现有 Migrator 执行追加迁移，导入 CLI 只验证 head 不执行 DDL。

## Risks / Trade-offs

- 来源身份未知 → 离线命名空间隔离，未来显式确认后才能接续在线同步。
- 关联目录/类型契约未核实 → 保存来源观察和未解析状态，不声明完整关系图。
- 正文可能包含敏感值 → 导入前清洗，全部命令禁止输出原始异常和数据行；受限存储，不开放查询接口。
- 新 schema 影响跨引擎校验 → 明确限定名和 SQLite 引号镜像，不修改已经应用的 migration。
- 大批内容事务过长 → 逐条事务与数据库批次进度，跨批次同来源排他锁。
- 旧镜像严格检查平台 head → 实际入库前须准备新镜像并取得短暂停服授权；不能仅增加迁移后让旧 API readiness 失败。

## Migration Plan

先合成数据测试和隔离 PostgreSQL 测试，再预检本机 head。代码检查发现 API 就绪检查及服务启动均要求精确迁移 head，无法保证只迁移就维持旧服务就绪；正式迁移前先确认相关服务更新/短暂停服权限，再准备镜像、执行新迁移、更新服务并导入。验收内容计数、类型、版本、收录、关系、字段映射、注释和幂等性，确认服务就绪恢复。不修改已有业务数据、配置、Agent 发布或授权。失败停止导入并保留可恢复批次；不自动 drop schema、清空业务库或回滚已应用迁移。

## Open Questions

真实 ONES 来源实例/团队及未来数据授权关系仍待后续阶段确认，不阻止当前受限离线导入。
