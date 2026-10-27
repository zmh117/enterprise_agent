-- 只增加持久合同与断点；实际 collection 转换由显式维护命令执行。
-- postgres-only
ALTER TABLE knowledge.vector_index ADD COLUMN incremental INTEGER NOT NULL DEFAULT 0 CHECK(incremental IN (0,1));
-- sqlite-only
ALTER TABLE "knowledge.vector_index" ADD COLUMN incremental INTEGER NOT NULL DEFAULT 0 CHECK(incremental IN (0,1));
-- postgres-only
CREATE UNIQUE INDEX knowledge_incremental_base_idx ON knowledge.vector_index(knowledge_base_id) WHERE incremental=1 AND state<>'RETIRED';
-- sqlite-only
CREATE UNIQUE INDEX knowledge_incremental_base_idx ON "knowledge.vector_index"(knowledge_base_id) WHERE incremental=1 AND state<>'RETIRED';
-- postgres-only
ALTER TABLE knowledge.sync_run ADD COLUMN incremental INTEGER NOT NULL DEFAULT 0 CHECK(incremental IN (0,1));
-- sqlite-only
ALTER TABLE "knowledge.sync_run" ADD COLUMN incremental INTEGER NOT NULL DEFAULT 0 CHECK(incremental IN (0,1));
-- postgres-only
ALTER TABLE knowledge.sync_candidate ADD COLUMN processing_step TEXT NOT NULL DEFAULT 'PENDING' CHECK(processing_step IN ('PENDING','APPLIED','DONE'));
-- sqlite-only
ALTER TABLE "knowledge.sync_candidate" ADD COLUMN processing_step TEXT NOT NULL DEFAULT 'PENDING' CHECK(processing_step IN ('PENDING','APPLIED','DONE'));
-- postgres-only
ALTER TABLE knowledge.sync_candidate ADD COLUMN processing_error TEXT;
-- sqlite-only
ALTER TABLE "knowledge.sync_candidate" ADD COLUMN processing_error TEXT;
-- postgres-only
CREATE INDEX knowledge_sync_pending_idx ON knowledge.sync_candidate(run_id,processing_step,document_id);
-- sqlite-only
CREATE INDEX knowledge_sync_pending_idx ON "knowledge.sync_candidate"(run_id,processing_step,document_id);
-- postgres-only
CREATE INDEX knowledge_revision_created_idx ON knowledge.document_revision(source_project_id,source_created_at,document_id);
-- sqlite-only
CREATE INDEX knowledge_revision_created_idx ON "knowledge.document_revision"(source_project_id,source_created_at,document_id);
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.incremental IS '固定集合增量合同；1 时内容更新不更改发布配置，禁止旧代清理';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.incremental IS '文档增量处理合同标记；旧整代运行必须显式完成或取消';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.processing_step IS '文档断点：PENDING 使用块与向量检查点恢复，APPLIED 已切换当前版本待开放和清理，DONE 已完成';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.processing_error IS '文档处理固定安全错误码；失败不清除已完成步骤';
