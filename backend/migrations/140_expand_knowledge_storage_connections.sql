-- 平台治理修订引用内容索引，不再外键绑定平台实例的索引表；既有数据和配置摘要不变。
-- migration: sqlite-foreign-keys-off

-- postgres-only
ALTER TABLE knowledge.retrieval_revision DROP CONSTRAINT retrieval_revision_index_id_fkey;
-- postgres-only
ALTER TABLE knowledge.retrieval_revision ADD COLUMN storage_config_json TEXT;
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.storage_config_json IS '知识内容 PostgreSQL/Qdrant 连接与平台 Secret 引用；NULL 为原部署连接，不含凭据明文';
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.index_id IS '内容存储中的 READY 索引标识；由用例校验归属，不跨实例建立外键';

-- sqlite-only
CREATE TABLE "knowledge.retrieval_revision_storage" (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES "knowledge.retrieval_resource"(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    binding_id TEXT REFERENCES "knowledge.source_binding"(id),
    index_id TEXT NOT NULL,
    profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT,
    storage_config_json TEXT,
    CHECK((published_by IS NULL AND published_at IS NULL) OR (published_by IS NOT NULL AND published_at IS NOT NULL)),
    UNIQUE(resource_id,revision),
    UNIQUE(resource_id,id)
);
-- sqlite-only
INSERT INTO "knowledge.retrieval_revision_storage"
  (id,resource_id,revision,binding_id,index_id,profile_hash,corpus_hash,config_hash,created_by,created_at,published_by,published_at)
SELECT id,resource_id,revision,binding_id,index_id,profile_hash,corpus_hash,config_hash,created_by,created_at,published_by,published_at
FROM "knowledge.retrieval_revision";
-- sqlite-only
DROP TABLE "knowledge.retrieval_revision";
-- sqlite-only
ALTER TABLE "knowledge.retrieval_revision_storage" RENAME TO "knowledge.retrieval_revision";
