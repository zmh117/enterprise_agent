-- 知识文本派生：只增加两表，不修改已有七表及其数据。

-- postgres-only
CREATE TABLE knowledge.document_chunk_set (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    document_revision_id TEXT NOT NULL,
    source_content_hash TEXT NOT NULL CHECK(length(source_content_hash)=64),
    profile_version TEXT NOT NULL,
    profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
    profile_config JSONB NOT NULL,
    normalized_fields JSONB NOT NULL,
    quality JSONB NOT NULL,
    chunk_count INTEGER NOT NULL CHECK(chunk_count>0),
    output_hash TEXT NOT NULL CHECK(length(output_hash)=64),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(document_revision_id, profile_hash),
    FOREIGN KEY(document_id, document_revision_id) REFERENCES knowledge.document_revision(document_id, id)
);

-- postgres-only
CREATE TABLE knowledge.document_chunk (
    id TEXT PRIMARY KEY,
    chunk_set_id TEXT NOT NULL REFERENCES knowledge.document_chunk_set(id),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    chunk_kind TEXT NOT NULL CHECK(chunk_kind IN ('problem','solution')),
    source_field TEXT NOT NULL CHECK(source_field IN ('body_text','attributes.solution_text')),
    source_start INTEGER NOT NULL CHECK(source_start>=0),
    source_end INTEGER NOT NULL CHECK(source_end>source_start),
    evidence_text TEXT NOT NULL,
    embedding_text TEXT NOT NULL,
    char_count INTEGER NOT NULL CHECK(char_count>0 AND char_count<=1200 AND char_count=length(evidence_text) AND char_count=source_end-source_start),
    embedding_char_count INTEGER NOT NULL CHECK(embedding_char_count>0 AND embedding_char_count<=1800 AND embedding_char_count=length(embedding_text)),
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    embedding_hash TEXT NOT NULL CHECK(length(embedding_hash)=64),
    quality_flags JSONB NOT NULL,
    UNIQUE(chunk_set_id, ordinal),
    CHECK((chunk_kind='problem' AND source_field='body_text') OR (chunk_kind='solution' AND source_field='attributes.solution_text'))
);

-- postgres-only
CREATE INDEX idx_knowledge_chunk_set_document ON knowledge.document_chunk_set(document_id, document_revision_id);

-- sqlite-only
CREATE TABLE "knowledge.document_chunk_set" (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    document_revision_id TEXT NOT NULL,
    source_content_hash TEXT NOT NULL CHECK(length(source_content_hash)=64),
    profile_version TEXT NOT NULL,
    profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
    profile_config TEXT NOT NULL,
    normalized_fields TEXT NOT NULL,
    quality TEXT NOT NULL,
    chunk_count INTEGER NOT NULL CHECK(chunk_count>0),
    output_hash TEXT NOT NULL CHECK(length(output_hash)=64),
    created_at TEXT NOT NULL,
    UNIQUE(document_revision_id, profile_hash),
    FOREIGN KEY(document_id, document_revision_id) REFERENCES "knowledge.document_revision"(document_id, id)
);

-- sqlite-only
CREATE TABLE "knowledge.document_chunk" (
    id TEXT PRIMARY KEY,
    chunk_set_id TEXT NOT NULL REFERENCES "knowledge.document_chunk_set"(id),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    chunk_kind TEXT NOT NULL CHECK(chunk_kind IN ('problem','solution')),
    source_field TEXT NOT NULL CHECK(source_field IN ('body_text','attributes.solution_text')),
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
    CHECK((chunk_kind='problem' AND source_field='body_text') OR (chunk_kind='solution' AND source_field='attributes.solution_text'))
);

-- sqlite-only
CREATE INDEX idx_knowledge_chunk_set_document ON "knowledge.document_chunk_set"(document_id, document_revision_id);

-- postgres-only
COMMENT ON TABLE knowledge.document_chunk_set IS '来源版本与分块配置对应的完整派生集合；不覆盖原版本';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.id IS '派生集合稳定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.document_id IS '所属知识文档标识';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.document_revision_id IS '来源不可变内容版本';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.source_content_hash IS '来源版本内容摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.profile_version IS '分块规则版本';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.profile_hash IS '规则与模板配置摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.profile_config IS '确定性规则及字符预算；不是模型 token 配置';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.normalized_fields IS '完整规范化字段；片段字符坐标指向此快照';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.quality IS '清洗变化及方案排除原因和缺失证据标记';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.chunk_count IS '完整集合内片段数';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.output_hash IS '规范化字段与有序片段的完整输出摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk_set.created_at IS '派生结果首次提交时间';

-- postgres-only
COMMENT ON TABLE knowledge.document_chunk IS '可定位的事实片段及待向量化文本；不代表已索引或已授权';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.id IS '由集合和顺序派生的稳定片段标识';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.chunk_set_id IS '所属完整派生集合';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.ordinal IS '集合内零起始顺序';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.chunk_kind IS '问题证据或有效解决方案证据';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.source_field IS '集合 normalized_fields 的来源字段名';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.source_start IS '规范化字段 Unicode 字符起点；包含';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.source_end IS '规范化字段 Unicode 字符终点；不包含';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.evidence_text IS '精确来源字段切片；不含生成的事实';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.embedding_text IS '版本化上下文加证据；尚未调用向量模型';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.char_count IS '证据 Unicode 字符数；不是 token 数';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.embedding_char_count IS '待向量化文本 Unicode 字符数';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.evidence_hash IS '证据文本摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.embedding_hash IS '待向量化文本摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.quality_flags IS '未采集证据及硬切或上下文裁剪标记';

