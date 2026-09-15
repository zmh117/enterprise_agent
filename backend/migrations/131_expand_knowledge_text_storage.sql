-- 知识文本存储基础；所有 DDL 由平台 Migrator 执行。
-- postgres-only
CREATE SCHEMA knowledge;
-- postgres-only
REVOKE ALL ON SCHEMA knowledge FROM PUBLIC;

-- postgres-only
CREATE TABLE knowledge.source (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    source_system TEXT NOT NULL,
    origin_state TEXT NOT NULL CHECK(origin_state IN ('offline_unverified','verified')),
    identity_metadata JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

-- postgres-only
CREATE TABLE knowledge.knowledge_base (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('storage_only','archived')),
    created_at TIMESTAMPTZ NOT NULL
);

-- postgres-only
CREATE TABLE knowledge.import_run (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES knowledge.source(id),
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge.knowledge_base(id),
    input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
    input_manifest JSONB NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('running','failed','completed')),
    total_count INTEGER NOT NULL CHECK(total_count>=0),
    processed_count INTEGER NOT NULL DEFAULT 0 CHECK(processed_count>=0 AND processed_count<=total_count),
    created_count INTEGER NOT NULL DEFAULT 0 CHECK(created_count>=0),
    revised_count INTEGER NOT NULL DEFAULT 0 CHECK(revised_count>=0),
    unchanged_count INTEGER NOT NULL DEFAULT 0 CHECK(unchanged_count>=0),
    stale_count INTEGER NOT NULL DEFAULT 0 CHECK(stale_count>=0),
    error_code TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    UNIQUE(source_id, knowledge_base_id, input_hash),
    CHECK(processed_count=created_count+revised_count+unchanged_count+stale_count)
);

-- postgres-only
CREATE TABLE knowledge.document (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES knowledge.source(id),
    source_object_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_number TEXT NOT NULL,
    document_kind TEXT NOT NULL CHECK(document_kind IN ('defect','ticket','requirement','article')),
    current_revision_id TEXT,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','unavailable','deleted')),
    created_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    UNIQUE(source_id, source_object_type, external_id),
    UNIQUE(source_id, source_object_type, external_id, id)
);

-- postgres-only
CREATE TABLE knowledge.document_revision (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES knowledge.document(id),
    revision_no INTEGER NOT NULL CHECK(revision_no>0),
    import_run_id TEXT NOT NULL REFERENCES knowledge.import_run(id),
    title TEXT NOT NULL,
    body_text TEXT NOT NULL,
    source_project_id TEXT NOT NULL,
    source_project_name TEXT NOT NULL,
    source_status_id TEXT,
    source_status_name TEXT,
    source_created_at TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    source_update_stamp_raw BIGINT,
    source_snapshot JSONB NOT NULL,
    attributes JSONB NOT NULL,
    completeness JSONB NOT NULL,
    normalizer_version TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    ingested_at TIMESTAMPTZ NOT NULL,
    UNIQUE(document_id, revision_no),
    UNIQUE(document_id, id)
);

-- postgres-only
CREATE TABLE knowledge.knowledge_base_document (
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge.knowledge_base(id),
    document_id TEXT NOT NULL REFERENCES knowledge.document(id),
    state TEXT NOT NULL CHECK(state IN ('included','removed')),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(knowledge_base_id, document_id)
);

-- postgres-only
CREATE TABLE knowledge.document_relation (
    id TEXT PRIMARY KEY,
    evidence_document_id TEXT NOT NULL REFERENCES knowledge.document(id),
    evidence_revision_id TEXT NOT NULL,
    relation_key TEXT NOT NULL CHECK(length(relation_key)=64),
    from_source_id TEXT NOT NULL REFERENCES knowledge.source(id),
    from_object_type TEXT NOT NULL,
    from_external_id TEXT NOT NULL,
    from_document_id TEXT,
    to_source_id TEXT NOT NULL REFERENCES knowledge.source(id),
    to_object_type TEXT NOT NULL,
    to_external_id TEXT NOT NULL,
    to_document_id TEXT,
    source_relation_type TEXT NOT NULL,
    source_direction TEXT NOT NULL,
    mapping_state TEXT NOT NULL CHECK(mapping_state IN ('unmapped','mapped')),
    observed_at TIMESTAMPTZ NOT NULL,
    UNIQUE(evidence_revision_id, relation_key),
    FOREIGN KEY(evidence_document_id, evidence_revision_id) REFERENCES knowledge.document_revision(document_id, id),
    FOREIGN KEY(from_source_id, from_object_type, from_external_id, from_document_id) REFERENCES knowledge.document(source_id, source_object_type, external_id, id),
    FOREIGN KEY(to_source_id, to_object_type, to_external_id, to_document_id) REFERENCES knowledge.document(source_id, source_object_type, external_id, id)
);

-- postgres-only
ALTER TABLE knowledge.document ADD CONSTRAINT knowledge_document_current_revision_fk FOREIGN KEY(id, current_revision_id) REFERENCES knowledge.document_revision(document_id, id) DEFERRABLE INITIALLY DEFERRED;

-- postgres-only
CREATE INDEX knowledge_document_kind_idx ON knowledge.document (source_id, document_kind);

-- postgres-only
CREATE INDEX knowledge_revision_project_idx ON knowledge.document_revision (source_project_id, source_updated_at);

-- postgres-only
CREATE INDEX knowledge_membership_document_idx ON knowledge.knowledge_base_document (document_id);

-- postgres-only
CREATE INDEX knowledge_relation_target_idx ON knowledge.document_relation (to_source_id, to_object_type, to_external_id);

-- postgres-only
CREATE INDEX knowledge_relation_source_idx ON knowledge.document_relation (from_source_id, from_object_type, from_external_id);

-- sqlite-only
CREATE TABLE "knowledge.source" (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    source_system TEXT NOT NULL,
    origin_state TEXT NOT NULL CHECK(origin_state IN ('offline_unverified','verified')),
    identity_metadata TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE "knowledge.knowledge_base" (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('storage_only','archived')),
    created_at TEXT NOT NULL
);

-- sqlite-only
CREATE TABLE "knowledge.import_run" (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
    knowledge_base_id TEXT NOT NULL REFERENCES "knowledge.knowledge_base"(id),
    input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
    input_manifest TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('running','failed','completed')),
    total_count INTEGER NOT NULL CHECK(total_count>=0),
    processed_count INTEGER NOT NULL DEFAULT 0 CHECK(processed_count>=0 AND processed_count<=total_count),
    created_count INTEGER NOT NULL DEFAULT 0 CHECK(created_count>=0),
    revised_count INTEGER NOT NULL DEFAULT 0 CHECK(revised_count>=0),
    unchanged_count INTEGER NOT NULL DEFAULT 0 CHECK(unchanged_count>=0),
    stale_count INTEGER NOT NULL DEFAULT 0 CHECK(stale_count>=0),
    error_code TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(source_id, knowledge_base_id, input_hash),
    CHECK(processed_count=created_count+revised_count+unchanged_count+stale_count)
);

-- sqlite-only
CREATE TABLE "knowledge.document" (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
    source_object_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_number TEXT NOT NULL,
    document_kind TEXT NOT NULL CHECK(document_kind IN ('defect','ticket','requirement','article')),
    current_revision_id TEXT,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('active','unavailable','deleted')),
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(source_id, source_object_type, external_id),
    UNIQUE(source_id, source_object_type, external_id, id),
    FOREIGN KEY(id, current_revision_id) REFERENCES "knowledge.document_revision"(document_id, id) DEFERRABLE INITIALLY DEFERRED
);

-- sqlite-only
CREATE TABLE "knowledge.document_revision" (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES "knowledge.document"(id),
    revision_no INTEGER NOT NULL CHECK(revision_no>0),
    import_run_id TEXT NOT NULL REFERENCES "knowledge.import_run"(id),
    title TEXT NOT NULL,
    body_text TEXT NOT NULL,
    source_project_id TEXT NOT NULL,
    source_project_name TEXT NOT NULL,
    source_status_id TEXT,
    source_status_name TEXT,
    source_created_at TEXT,
    source_updated_at TEXT,
    source_update_stamp_raw BIGINT,
    source_snapshot TEXT NOT NULL,
    attributes TEXT NOT NULL,
    completeness TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
    ingested_at TEXT NOT NULL,
    UNIQUE(document_id, revision_no),
    UNIQUE(document_id, id)
);

-- sqlite-only
CREATE TABLE "knowledge.knowledge_base_document" (
    knowledge_base_id TEXT NOT NULL REFERENCES "knowledge.knowledge_base"(id),
    document_id TEXT NOT NULL REFERENCES "knowledge.document"(id),
    state TEXT NOT NULL CHECK(state IN ('included','removed')),
    created_at TEXT NOT NULL,
    PRIMARY KEY(knowledge_base_id, document_id)
);

-- sqlite-only
CREATE TABLE "knowledge.document_relation" (
    id TEXT PRIMARY KEY,
    evidence_document_id TEXT NOT NULL REFERENCES "knowledge.document"(id),
    evidence_revision_id TEXT NOT NULL,
    relation_key TEXT NOT NULL CHECK(length(relation_key)=64),
    from_source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
    from_object_type TEXT NOT NULL,
    from_external_id TEXT NOT NULL,
    from_document_id TEXT,
    to_source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
    to_object_type TEXT NOT NULL,
    to_external_id TEXT NOT NULL,
    to_document_id TEXT,
    source_relation_type TEXT NOT NULL,
    source_direction TEXT NOT NULL,
    mapping_state TEXT NOT NULL CHECK(mapping_state IN ('unmapped','mapped')),
    observed_at TEXT NOT NULL,
    UNIQUE(evidence_revision_id, relation_key),
    FOREIGN KEY(evidence_document_id, evidence_revision_id) REFERENCES "knowledge.document_revision"(document_id, id),
    FOREIGN KEY(from_source_id, from_object_type, from_external_id, from_document_id) REFERENCES "knowledge.document"(source_id, source_object_type, external_id, id),
    FOREIGN KEY(to_source_id, to_object_type, to_external_id, to_document_id) REFERENCES "knowledge.document"(source_id, source_object_type, external_id, id)
);

-- sqlite-only
CREATE INDEX knowledge_document_kind_idx ON "knowledge.document" (source_id, document_kind);

-- sqlite-only
CREATE INDEX knowledge_revision_project_idx ON "knowledge.document_revision" (source_project_id, source_updated_at);

-- sqlite-only
CREATE INDEX knowledge_membership_document_idx ON "knowledge.knowledge_base_document" (document_id);

-- sqlite-only
CREATE INDEX knowledge_relation_target_idx ON "knowledge.document_relation" (to_source_id, to_object_type, to_external_id);

-- sqlite-only
CREATE INDEX knowledge_relation_source_idx ON "knowledge.document_relation" (from_source_id, from_object_type, from_external_id);

COMMENT ON TABLE knowledge.source IS '知识来源身份；离线来源未确认时不得用于在线同步或授权';
COMMENT ON COLUMN knowledge.source.id IS '内部来源身份';
COMMENT ON COLUMN knowledge.source.code IS '稳定来源编码，独立于导入文件与知识库';
COMMENT ON COLUMN knowledge.source.display_name IS '来源中文显示名';
COMMENT ON COLUMN knowledge.source.source_system IS '来源系统标识，如 ones';
COMMENT ON COLUMN knowledge.source.origin_state IS '来源身份核验状态';
COMMENT ON COLUMN knowledge.source.identity_metadata IS '不含凭据的实例及团队元数据，未确认时为空';
COMMENT ON COLUMN knowledge.source.created_at IS '来源登记时间';

COMMENT ON TABLE knowledge.knowledge_base IS '知识库收录身份；本阶段仅存储，不构成已发布资源或数据访问授权';
COMMENT ON COLUMN knowledge.knowledge_base.id IS '知识库内部身份';
COMMENT ON COLUMN knowledge.knowledge_base.code IS '知识库稳定编码';
COMMENT ON COLUMN knowledge.knowledge_base.display_name IS '知识库中文显示名';
COMMENT ON COLUMN knowledge.knowledge_base.description IS '知识库内容边界说明';
COMMENT ON COLUMN knowledge.knowledge_base.state IS '存储状态，不表示资源发布';
COMMENT ON COLUMN knowledge.knowledge_base.created_at IS '创建时间';

COMMENT ON TABLE knowledge.import_run IS '离线导入批次及事务性检查点，不保存原始失败行或异常正文';
COMMENT ON COLUMN knowledge.import_run.id IS '导入批次身份';
COMMENT ON COLUMN knowledge.import_run.source_id IS '本批来源身份';
COMMENT ON COLUMN knowledge.import_run.knowledge_base_id IS '本批收录的知识库';
COMMENT ON COLUMN knowledge.import_run.input_hash IS '输入文件摘要和配置的联合签名';
COMMENT ON COLUMN knowledge.import_run.input_manifest IS '输入文件哈希及规范化配置，不含绝对路径和正文';
COMMENT ON COLUMN knowledge.import_run.state IS '导入运行状态';
COMMENT ON COLUMN knowledge.import_run.total_count IS '预检通过的输入记录数';
COMMENT ON COLUMN knowledge.import_run.processed_count IS '已事务提交的记录检查点';
COMMENT ON COLUMN knowledge.import_run.created_count IS '新增文档数';
COMMENT ON COLUMN knowledge.import_run.revised_count IS '新增已有文档版本数';
COMMENT ON COLUMN knowledge.import_run.unchanged_count IS '相同内容记录数';
COMMENT ON COLUMN knowledge.import_run.stale_count IS '未覆盖当前版本的旧记录数';
COMMENT ON COLUMN knowledge.import_run.error_code IS '白名单失败机器码，不含来源数据';
COMMENT ON COLUMN knowledge.import_run.started_at IS '首次开始时间';
COMMENT ON COLUMN knowledge.import_run.updated_at IS '最近检查点更新时间';
COMMENT ON COLUMN knowledge.import_run.completed_at IS '全部处理完成时间';

COMMENT ON TABLE knowledge.document IS '跨知识库复用的来源文档稳定身份，类型变化不改变身份';
COMMENT ON COLUMN knowledge.document.id IS '文档内部身份';
COMMENT ON COLUMN knowledge.document.source_id IS '来源命名空间';
COMMENT ON COLUMN knowledge.document.source_object_type IS '来源对象类型，如 ones_work_item';
COMMENT ON COLUMN knowledge.document.external_id IS '来源稳定 ID，不假定为标准 UUID';
COMMENT ON COLUMN knowledge.document.external_number IS '来源显示编号，不作为唯一身份';
COMMENT ON COLUMN knowledge.document.document_kind IS '业务内容分类';
COMMENT ON COLUMN knowledge.document.current_revision_id IS '当前不可变版本，必须属于同一文档';
COMMENT ON COLUMN knowledge.document.lifecycle_state IS '来源内容可用状态';
COMMENT ON COLUMN knowledge.document.created_at IS '首次入库时间';
COMMENT ON COLUMN knowledge.document.last_seen_at IS '最后一次有效导入观察时间';

COMMENT ON TABLE knowledge.document_revision IS '受限来源快照和规范化内容的不可变版本；不含可访问 URL 或认证信息';
COMMENT ON COLUMN knowledge.document_revision.id IS '内容版本身份';
COMMENT ON COLUMN knowledge.document_revision.document_id IS '所属文档';
COMMENT ON COLUMN knowledge.document_revision.revision_no IS '文档内递增版本号';
COMMENT ON COLUMN knowledge.document_revision.import_run_id IS '生成本版本的导入批次';
COMMENT ON COLUMN knowledge.document_revision.title IS '安全清洗后的来源标题';
COMMENT ON COLUMN knowledge.document_revision.body_text IS '规范化正文，保留原文本的步骤和代码';
COMMENT ON COLUMN knowledge.document_revision.source_project_id IS '真实来源项目 ID，由 list 显式补回';
COMMENT ON COLUMN knowledge.document_revision.source_project_name IS '来源项目显示名称，不作为授权 ID';
COMMENT ON COLUMN knowledge.document_revision.source_status_id IS '来源状态 ID';
COMMENT ON COLUMN knowledge.document_revision.source_status_name IS '来源状态显示名';
COMMENT ON COLUMN knowledge.document_revision.source_created_at IS '规范化来源创建时间';
COMMENT ON COLUMN knowledge.document_revision.source_updated_at IS '规范化来源更新时间';
COMMENT ON COLUMN knowledge.document_revision.source_update_stamp_raw IS '导出原始微秒更新时间戳';
COMMENT ON COLUMN knowledge.document_revision.source_snapshot IS '安全清洗后的来源快照，不是字节级原件';
COMMENT ON COLUMN knowledge.document_revision.attributes IS '具有显式映射的业务属性和未映射字段';
COMMENT ON COLUMN knowledge.document_revision.completeness IS '详情、讨论、附件与 OCR 的独立采集状态';
COMMENT ON COLUMN knowledge.document_revision.normalizer_version IS '字段和安全清洗规则版本';
COMMENT ON COLUMN knowledge.document_revision.content_hash IS '规范化内容和规则版本的摘要';
COMMENT ON COLUMN knowledge.document_revision.ingested_at IS '本版本入库时间';

COMMENT ON TABLE knowledge.knowledge_base_document IS '知识库与来源文档的多对多收录关系，不扩大来源访问权限';
COMMENT ON COLUMN knowledge.knowledge_base_document.knowledge_base_id IS '收录知识库';
COMMENT ON COLUMN knowledge.knowledge_base_document.document_id IS '被收录文档';
COMMENT ON COLUMN knowledge.knowledge_base_document.state IS '收录状态';
COMMENT ON COLUMN knowledge.knowledge_base_document.created_at IS '首次收录时间';

COMMENT ON TABLE knowledge.document_relation IS '绑定来源快照的原始工作项关联观察，未解析目标不创建虚假正文';
COMMENT ON COLUMN knowledge.document_relation.id IS '关系观察内部身份';
COMMENT ON COLUMN knowledge.document_relation.evidence_document_id IS '提供关联证据的文档';
COMMENT ON COLUMN knowledge.document_relation.evidence_revision_id IS '提供关联证据的精确版本';
COMMENT ON COLUMN knowledge.document_relation.relation_key IS '原始端点与类型方向的幂等摘要';
COMMENT ON COLUMN knowledge.document_relation.from_source_id IS '来源观察起点命名空间';
COMMENT ON COLUMN knowledge.document_relation.from_object_type IS '起点来源对象类型';
COMMENT ON COLUMN knowledge.document_relation.from_external_id IS '起点来源外部身份';
COMMENT ON COLUMN knowledge.document_relation.from_document_id IS '起点本地文档身份';
COMMENT ON COLUMN knowledge.document_relation.to_source_id IS '来源观察目标命名空间';
COMMENT ON COLUMN knowledge.document_relation.to_object_type IS '目标来源对象类型';
COMMENT ON COLUMN knowledge.document_relation.to_external_id IS '目标来源外部身份';
COMMENT ON COLUMN knowledge.document_relation.to_document_id IS '目标本地文档身份，未导入时为空';
COMMENT ON COLUMN knowledge.document_relation.source_relation_type IS '原始关系类型 ID，未映射时不得推断含义';
COMMENT ON COLUMN knowledge.document_relation.source_direction IS '来源相对方向原值，如 link_out_desc';
COMMENT ON COLUMN knowledge.document_relation.mapping_state IS '来源关系含义是否经过明确映射';
COMMENT ON COLUMN knowledge.document_relation.observed_at IS '本地观察时间，不是 ONES 在线核验时间';
