-- 明确新 KB 范围摘要版本；0 只保留历史摘要判定，不重签、不发布旧资源。
-- postgres-only
ALTER TABLE knowledge.retrieval_revision ADD COLUMN configuration_version INTEGER NOT NULL DEFAULT 0 CHECK(configuration_version IN (0,2,3,4));
-- sqlite-only
ALTER TABLE "knowledge.retrieval_revision" ADD COLUMN configuration_version INTEGER NOT NULL DEFAULT 0 CHECK(configuration_version IN (0,2,3,4));
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.configuration_version IS '配置摘要版本；0 按历史连接模式判定 2/3，4 仅覆盖本知识库；迁移不重新验证或发布';
