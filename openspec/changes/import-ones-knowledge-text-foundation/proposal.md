## Why

用户已批准把现有 5,000 条 ONES 缺陷离线导出实际导入本机平台 PostgreSQL，并要求后续可接入相互关联的工单、需求及其他知识来源。需要统一知识存储身份、不可变版本和关联事实，避免按知识库复制原文或误把显示名称作为来源 ID。

## What Changes

- 在现有数据库创建 `knowledge` schema 和 source、document、document_revision、knowledge_base、knowledge_base_document、import_run、document_relation 七张表。
- 增加显式离线导入 CLI，合并详情/list，保存经过安全清洗的快照、正文、业务字段和待解析关联，记录可恢复批次并幂等导入。
- 把现有 schema 检查、中文注释和事实源清单扩展到 knowledge；仅由一次性 Migrator 执行新迁移，保留 SQLite 测试等价结构。
- 验收真实 PostgreSQL 建表、5,000 条缺陷导入及重复导入不增量；仅输出统计、摘要和机器错误码。
- 不下载附件、不 OCR、不调用外部 ONES/Embedding、不配置 Qdrant、不增加 Web/MCP/Agent 访问或角色授权。

## Capabilities

### New Capabilities

无新增 canonical 领域；知识存储的阶段一运行契约归入 platform-operations。

### Modified Capabilities

- `platform-operations`: 增加受限离线知识入库契约及多 schema 治理，扩展项目表中文注释范围。

## Impact

- backend/migrations 下一可用迁移版本、shared schema inspection/manifest、knowledge 模块、离线导入 CLI、测试与运行文档。
- 本机现有 PostgreSQL 追加独立 schema 和导入数据，不修改现有业务记录；按用户确认的正式入库指令同步更新受迁移 head 约束的服务，允许必要的短暂重启。
- 团队/实例身份未出现在导出中时，仅登记未确认来源的本地导出命名空间；不猜测或关联现有 ONES 账号。
