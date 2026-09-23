-- 允许缺少描述的工作项保留标题来源证据；不改已有块、指纹或权限。
-- migration: sqlite-foreign-keys-off

-- postgres-only
ALTER TABLE knowledge.document_chunk DROP CONSTRAINT document_chunk_source_field_check;
-- postgres-only
ALTER TABLE knowledge.document_chunk ADD CONSTRAINT document_chunk_source_field_check CHECK(source_field IN ('body_text','title','attributes.solution_text'));
-- postgres-only
ALTER TABLE knowledge.document_chunk DROP CONSTRAINT document_chunk_check3;
-- postgres-only
ALTER TABLE knowledge.document_chunk ADD CONSTRAINT document_chunk_check3 CHECK((chunk_kind='problem' AND source_field IN ('body_text','title')) OR (chunk_kind='solution' AND source_field='attributes.solution_text'));
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.source_field IS '证据所属规范化字段；标题稀疏块独立追溯，不伪造正文';

-- sqlite-only
CREATE TABLE "knowledge.document_chunk_typed" (
    id TEXT PRIMARY KEY,
    chunk_set_id TEXT NOT NULL REFERENCES "knowledge.document_chunk_set"(id),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    chunk_kind TEXT NOT NULL CHECK(chunk_kind IN ('problem','solution')),
    source_field TEXT NOT NULL CHECK(source_field IN ('body_text','title','attributes.solution_text')),
    source_start INTEGER NOT NULL CHECK(source_start>=0),
    source_end INTEGER NOT NULL CHECK(source_end>source_start),
    evidence_text TEXT NOT NULL,
    embedding_text TEXT NOT NULL,
    char_count INTEGER NOT NULL CHECK(char_count>0 AND char_count<=1200 AND char_count=length(evidence_text) AND char_count=source_end-source_start),
    embedding_char_count INTEGER NOT NULL CHECK(embedding_char_count>0 AND embedding_char_count<=1800 AND embedding_char_count=length(embedding_text)),
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    embedding_hash TEXT NOT NULL CHECK(length(embedding_hash)=64),
    quality_flags TEXT NOT NULL,
    UNIQUE(chunk_set_id, ordinal),
    CHECK((chunk_kind='problem' AND source_field IN ('body_text','title')) OR (chunk_kind='solution' AND source_field='attributes.solution_text'))
);
-- sqlite-only
INSERT INTO "knowledge.document_chunk_typed" (id,chunk_set_id,ordinal,chunk_kind,source_field,source_start,source_end,evidence_text,embedding_text,char_count,embedding_char_count,evidence_hash,embedding_hash,quality_flags)
SELECT id,chunk_set_id,ordinal,chunk_kind,source_field,source_start,source_end,evidence_text,embedding_text,char_count,embedding_char_count,evidence_hash,embedding_hash,quality_flags FROM "knowledge.document_chunk";
-- sqlite-only
DROP TABLE "knowledge.document_chunk";
-- sqlite-only
ALTER TABLE "knowledge.document_chunk_typed" RENAME TO "knowledge.document_chunk";
