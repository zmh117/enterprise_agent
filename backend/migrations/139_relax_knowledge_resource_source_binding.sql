-- 来源绑定仅保留历史追溯；新草稿按本地数据/索引验证，不伪造 ONES 来源确认。
-- migration: sqlite-foreign-keys-off

-- postgres-only
ALTER TABLE knowledge.retrieval_revision ALTER COLUMN binding_id DROP NOT NULL;
-- postgres-only
COMMENT ON COLUMN knowledge.retrieval_revision.binding_id IS '历史来源绑定引用；新版本为空，配置摘要直接固定本地来源和数据身份';

-- sqlite-only
CREATE TABLE "knowledge.retrieval_revision_local" (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES "knowledge.retrieval_resource"(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    binding_id TEXT REFERENCES "knowledge.source_binding"(id),
    index_id TEXT NOT NULL REFERENCES "knowledge.vector_index"(id),
    profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT,
    CHECK((published_by IS NULL AND published_at IS NULL) OR (published_by IS NOT NULL AND published_at IS NOT NULL)),
    UNIQUE(resource_id,revision),
    UNIQUE(resource_id,id)
);
-- sqlite-only
INSERT INTO "knowledge.retrieval_revision_local"
  (id,resource_id,revision,binding_id,index_id,profile_hash,corpus_hash,config_hash,created_by,created_at,published_by,published_at)
SELECT id,resource_id,revision,binding_id,index_id,profile_hash,corpus_hash,config_hash,created_by,created_at,published_by,published_at
FROM "knowledge.retrieval_revision";
-- sqlite-only
DROP TABLE "knowledge.retrieval_revision";
-- sqlite-only
ALTER TABLE "knowledge.retrieval_revision_local" RENAME TO "knowledge.retrieval_revision";
