-- 仅新增知识向量索引协调表；不修改原九表及其数据。

-- postgres-only
CREATE TABLE knowledge.vector_index (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge.knowledge_base(id),
    profile JSONB NOT NULL,
    profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
    chunk_profile_hash TEXT NOT NULL CHECK(length(chunk_profile_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    collection_name TEXT NOT NULL UNIQUE,
    expected_document_count INTEGER NOT NULL CHECK(expected_document_count>0),
    expected_chunk_count INTEGER NOT NULL CHECK(expected_chunk_count>0),
    state TEXT NOT NULL CHECK(state IN ('BUILDING','READY','FAILED')),
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

-- postgres-only
CREATE TABLE knowledge.vector_index_item (
    index_id TEXT NOT NULL REFERENCES knowledge.vector_index(id),
    chunk_id TEXT NOT NULL REFERENCES knowledge.document_chunk(id),
    point_id TEXT NOT NULL,
    embedding_text_hash TEXT NOT NULL CHECK(length(embedding_text_hash)=64),
    state TEXT NOT NULL CHECK(state IN ('PENDING','INDEXED','FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(index_id,chunk_id),
    UNIQUE(index_id,point_id)
);

-- sqlite-only
CREATE TABLE "knowledge.vector_index" (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    knowledge_base_id TEXT NOT NULL REFERENCES "knowledge.knowledge_base"(id),
    profile TEXT NOT NULL,
    profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
    chunk_profile_hash TEXT NOT NULL CHECK(length(chunk_profile_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    collection_name TEXT NOT NULL UNIQUE,
    expected_document_count INTEGER NOT NULL CHECK(expected_document_count>0),
    expected_chunk_count INTEGER NOT NULL CHECK(expected_chunk_count>0),
    state TEXT NOT NULL CHECK(state IN ('BUILDING','READY','FAILED')),
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE "knowledge.vector_index_item" (
    index_id TEXT NOT NULL REFERENCES "knowledge.vector_index"(id),
    chunk_id TEXT NOT NULL REFERENCES "knowledge.document_chunk"(id),
    point_id TEXT NOT NULL,
    embedding_text_hash TEXT NOT NULL CHECK(length(embedding_text_hash)=64),
    state TEXT NOT NULL CHECK(state IN ('PENDING','INDEXED','FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(index_id,chunk_id),
    UNIQUE(index_id,point_id)
);

-- postgres-only
COMMENT ON TABLE knowledge.vector_index IS '知识向量索引清单；不产生业务授权';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.id IS '向量索引稳定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.code IS '显式索引版本代码';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.knowledge_base_id IS '所属受限知识库';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.profile IS '模型及运行配置快照';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.profile_hash IS '模型配置完整摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.chunk_profile_hash IS '分块配置摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.corpus_hash IS '固定语料清单摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.collection_name IS '专属 Qdrant 集合名称';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.expected_document_count IS '预期当前文档数量';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.expected_chunk_count IS '预期片段数量';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.state IS '索引构建及就绪状态';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.error_code IS '最近固定机器错误码';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.created_at IS '索引首次创建时间';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index.updated_at IS '索引最近状态更新时间';
-- postgres-only
COMMENT ON TABLE knowledge.vector_index_item IS '知识向量逐块写入检查点；不是来源事实';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index_item.index_id IS '所属向量索引';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index_item.chunk_id IS '不可变来源片段';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index_item.point_id IS '同索引内确定的 Qdrant 点标识';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index_item.embedding_text_hash IS '本次待向量化文本摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index_item.state IS '逐块检查点状态';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index_item.attempt_count IS '逐块写入尝试计数';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index_item.error_code IS '最近固定机器错误码';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index_item.created_at IS '检查点首次创建时间';
-- postgres-only
COMMENT ON COLUMN knowledge.vector_index_item.updated_at IS '检查点最近状态更新时间';
