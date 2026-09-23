-- 候选向量代际归属与可信空库；不创建 collection、不清理任何索引。
-- migration: sqlite-foreign-keys-off
-- postgres-only
ALTER TABLE knowledge.vector_index DROP CONSTRAINT vector_index_expected_document_count_check;
-- postgres-only
ALTER TABLE knowledge.vector_index DROP CONSTRAINT vector_index_expected_chunk_count_check;
-- postgres-only
ALTER TABLE knowledge.vector_index ADD CONSTRAINT vector_index_expected_document_count_check CHECK(expected_document_count>=0);
-- postgres-only
ALTER TABLE knowledge.vector_index ADD CONSTRAINT vector_index_expected_chunk_count_check CHECK(expected_chunk_count>=0);
-- postgres-only
ALTER TABLE knowledge.vector_index ADD CONSTRAINT knowledge_vector_complete_counts CHECK((expected_document_count=0 AND expected_chunk_count=0) OR (expected_document_count>0 AND expected_chunk_count>=expected_document_count));
-- postgres-only
ALTER TABLE knowledge.vector_index ADD COLUMN sync_run_id TEXT REFERENCES knowledge.sync_run(id);
-- postgres-only
ALTER TABLE knowledge.vector_index ADD COLUMN source_id TEXT REFERENCES knowledge.source(id);
-- postgres-only
ALTER TABLE knowledge.vector_index ADD COLUMN unreferenced_at TIMESTAMPTZ;
-- postgres-only
ALTER TABLE knowledge.vector_index ADD CONSTRAINT knowledge_vector_sync_source_required CHECK(sync_run_id IS NULL OR source_id IS NOT NULL);
-- postgres-only
ALTER TABLE knowledge.vector_index DROP CONSTRAINT vector_index_state_check;
-- postgres-only
ALTER TABLE knowledge.vector_index ADD CONSTRAINT vector_index_state_check CHECK(state IN ('BUILDING','READY','FAILED','RETIRED'));

-- sqlite-only
CREATE TABLE "knowledge.vector_index_generation" (
 id TEXT PRIMARY KEY,
 code TEXT NOT NULL UNIQUE,
 knowledge_base_id TEXT NOT NULL REFERENCES "knowledge.knowledge_base"(id),
 profile TEXT NOT NULL,
 profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
 chunk_profile_hash TEXT NOT NULL CHECK(length(chunk_profile_hash)=64),
 corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
 collection_name TEXT NOT NULL UNIQUE,
 expected_document_count INTEGER NOT NULL CHECK(expected_document_count>=0),
 expected_chunk_count INTEGER NOT NULL CHECK(expected_chunk_count>=0),
 state TEXT NOT NULL CHECK(state IN ('BUILDING','READY','FAILED','RETIRED')),
 error_code TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 sync_run_id TEXT REFERENCES "knowledge.sync_run"(id),
 source_id TEXT REFERENCES "knowledge.source"(id),
 unreferenced_at TEXT,
 CHECK(sync_run_id IS NULL OR source_id IS NOT NULL),
 CHECK((expected_document_count=0 AND expected_chunk_count=0) OR (expected_document_count>0 AND expected_chunk_count>=expected_document_count))
);
-- sqlite-only
INSERT INTO "knowledge.vector_index_generation" (id,code,knowledge_base_id,profile,profile_hash,chunk_profile_hash,corpus_hash,collection_name,expected_document_count,expected_chunk_count,state,error_code,created_at,updated_at)
SELECT id,code,knowledge_base_id,profile,profile_hash,chunk_profile_hash,corpus_hash,collection_name,expected_document_count,expected_chunk_count,state,error_code,created_at,updated_at FROM "knowledge.vector_index";
-- sqlite-only
DROP TABLE "knowledge.vector_index";
-- sqlite-only
ALTER TABLE "knowledge.vector_index_generation" RENAME TO "knowledge.vector_index";

-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.sync_run_id IS '明确的同步代际归属；历史和手工索引为空，禁止自动清理';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.source_id IS '候选索引固定来源，空成员代际仍保留来源身份';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.unreferenced_at IS '确认失去引用的时间；清理须再次校验当前与上一成功代际并等待至少十分钟';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.expected_document_count IS '冻结文档数量；可信空成员代际允许为零';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.expected_chunk_count IS '冻结片段数量；仅零文档时允许零片段';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.state IS '构建、就绪、失败或已清理派生 collection；清理不删除索引审计事实';
