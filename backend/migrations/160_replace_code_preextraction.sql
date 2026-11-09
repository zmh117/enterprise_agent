-- 按需代码知识：旧数据须先经清单退役，迁移不自动清理业务内容或源码目录。
-- migration: sqlite-foreign-keys-off
-- postgres-only
CREATE TEMP TABLE code_retirement_guard (remaining INTEGER NOT NULL CHECK(remaining=0));
-- sqlite-only
CREATE TEMP TABLE code_retirement_guard (remaining INTEGER NOT NULL CHECK(remaining=0));
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_transition_failure;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_transition_failure";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_transition_source;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_transition_source";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_transition;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_transition";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_state;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_state";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_event;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_event";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_machine;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_machine";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_object;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_object";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_history_check;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_history_check";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_relation;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_relation";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_member;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_member";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_dependency;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_dependency";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_demand;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_demand";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_unit;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_unit";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_build;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_build";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_snapshot;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_snapshot";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_commit;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_commit";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_source_file;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_source_file";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_source_snapshot;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_source_snapshot";
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_binding WHERE enabled<>0 OR demand_enabled<>0 OR active_snapshot_id IS NOT NULL;
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_binding" WHERE enabled<>0 OR demand_enabled<>0 OR active_snapshot_id IS NOT NULL;
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.code_checkout_job WHERE state IN ('QUEUED','RUNNING');
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.code_checkout_job" WHERE state IN ('QUEUED','RUNNING');
-- postgres-only
INSERT INTO code_retirement_guard SELECT count(*) FROM knowledge.document WHERE document_kind IN ('object','state_machine','state','operation','rule','transition') OR source_id IN (SELECT source_id FROM knowledge.code_binding);
-- sqlite-only
INSERT INTO code_retirement_guard SELECT count(*) FROM "knowledge.document" WHERE document_kind IN ('object','state_machine','state','operation','rule','transition') OR source_id IN (SELECT source_id FROM "knowledge.code_binding");
-- postgres-only
DROP TABLE code_retirement_guard;
-- sqlite-only
DROP TABLE code_retirement_guard;
-- postgres-only
ALTER TABLE knowledge.knowledge_base ADD COLUMN kind TEXT NOT NULL DEFAULT 'ones' CHECK(kind IN ('ones','code'));
-- sqlite-only
ALTER TABLE "knowledge.knowledge_base" ADD COLUMN kind TEXT NOT NULL DEFAULT 'ones' CHECK(kind IN ('ones','code'));
-- postgres-only
ALTER TABLE knowledge.knowledge_base ADD COLUMN code_indexing_paused BOOLEAN NOT NULL DEFAULT false CHECK(kind='code' OR code_indexing_paused=false);
-- sqlite-only
ALTER TABLE "knowledge.knowledge_base" ADD COLUMN code_indexing_paused INTEGER NOT NULL DEFAULT 0 CHECK(kind='code' OR code_indexing_paused=0);
-- postgres-only
UPDATE knowledge.knowledge_base SET kind='code' WHERE id IN (SELECT knowledge_base_id FROM knowledge.code_binding);
-- sqlite-only
UPDATE "knowledge.knowledge_base" SET kind='code' WHERE id IN (SELECT knowledge_base_id FROM "knowledge.code_binding");
-- postgres-only
DROP TABLE knowledge.code_transition_failure;
-- sqlite-only
DROP TABLE "knowledge.code_transition_failure";
-- postgres-only
DROP TABLE knowledge.code_transition_source;
-- sqlite-only
DROP TABLE "knowledge.code_transition_source";
-- postgres-only
DROP TABLE knowledge.code_transition;
-- sqlite-only
DROP TABLE "knowledge.code_transition";
-- postgres-only
DROP TABLE knowledge.code_state;
-- sqlite-only
DROP TABLE "knowledge.code_state";
-- postgres-only
DROP TABLE knowledge.code_event;
-- sqlite-only
DROP TABLE "knowledge.code_event";
-- postgres-only
DROP TABLE knowledge.code_machine;
-- sqlite-only
DROP TABLE "knowledge.code_machine";
-- postgres-only
DROP TABLE knowledge.code_object;
-- sqlite-only
DROP TABLE "knowledge.code_object";
-- postgres-only
DROP TABLE knowledge.code_history_check;
-- sqlite-only
DROP TABLE "knowledge.code_history_check";
-- postgres-only
DROP TABLE knowledge.code_relation;
-- sqlite-only
DROP TABLE "knowledge.code_relation";
-- postgres-only
DROP TABLE knowledge.code_member;
-- sqlite-only
DROP TABLE "knowledge.code_member";
-- postgres-only
DROP TABLE knowledge.code_dependency;
-- sqlite-only
DROP TABLE "knowledge.code_dependency";
-- postgres-only
DROP TABLE knowledge.code_demand;
-- sqlite-only
DROP TABLE "knowledge.code_demand";
-- postgres-only
DROP TABLE knowledge.code_unit;
-- sqlite-only
DROP TABLE "knowledge.code_unit";
-- postgres-only
DROP TABLE knowledge.code_build;
-- sqlite-only
DROP TABLE "knowledge.code_build";
-- postgres-only
DROP TABLE knowledge.code_snapshot;
-- sqlite-only
DROP TABLE "knowledge.code_snapshot";
-- postgres-only
DROP TABLE knowledge.code_commit;
-- sqlite-only
DROP TABLE "knowledge.code_commit";
-- postgres-only
DROP TABLE knowledge.code_source_file;
-- sqlite-only
DROP TABLE "knowledge.code_source_file";
-- postgres-only
DROP TABLE knowledge.code_source_snapshot;
-- sqlite-only
DROP TABLE "knowledge.code_source_snapshot";
-- postgres-only
DROP TABLE knowledge.code_binding;
-- sqlite-only
DROP TABLE "knowledge.code_binding";
-- postgres-only
DROP TABLE knowledge.code_checkout_job;
-- sqlite-only
DROP TABLE "knowledge.code_checkout_job";
-- postgres-only
CREATE UNIQUE INDEX code_invocation_job_identity_idx ON agent_runtime_invocation(job_id,invocation_id);
-- sqlite-only
CREATE UNIQUE INDEX code_invocation_job_identity_idx ON agent_runtime_invocation(job_id,invocation_id);
-- postgres-only
ALTER TABLE knowledge.document DROP CONSTRAINT document_document_kind_check;
-- postgres-only
ALTER TABLE knowledge.document ADD CONSTRAINT document_document_kind_check CHECK(document_kind IN ('defect','ticket','requirement','article','code_answer'));
-- postgres-only
ALTER TABLE knowledge.document ADD CONSTRAINT knowledge_document_source_identity UNIQUE(id,source_id);
-- postgres-only
ALTER TABLE knowledge.document_revision ALTER COLUMN import_run_id DROP NOT NULL;
-- postgres-only
ALTER TABLE knowledge.document_revision ALTER COLUMN source_project_id DROP NOT NULL;
-- postgres-only
ALTER TABLE knowledge.document_revision ALTER COLUMN source_project_name DROP NOT NULL;
-- postgres-only
ALTER TABLE knowledge.document_revision ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'import' CHECK(origin_kind IN ('import','code_analysis'));
-- postgres-only
ALTER TABLE knowledge.document_revision ADD COLUMN code_analysis_id TEXT UNIQUE;
-- postgres-only
ALTER TABLE knowledge.document_revision ADD CONSTRAINT knowledge_revision_origin CHECK((origin_kind='import' AND import_run_id IS NOT NULL AND code_analysis_id IS NULL AND source_project_id IS NOT NULL AND source_project_name IS NOT NULL) OR (origin_kind='code_analysis' AND import_run_id IS NULL AND code_analysis_id IS NOT NULL AND source_project_id IS NULL AND source_project_name IS NULL));
-- postgres-only
ALTER TABLE knowledge.document_chunk DROP CONSTRAINT document_chunk_chunk_kind_check;
-- postgres-only
ALTER TABLE knowledge.document_chunk DROP CONSTRAINT document_chunk_check3;
-- postgres-only
ALTER TABLE knowledge.document_chunk ADD CONSTRAINT document_chunk_chunk_kind_check CHECK(chunk_kind IN ('problem','solution','business_answer'));
-- postgres-only
ALTER TABLE knowledge.document_chunk ADD CONSTRAINT document_chunk_check3 CHECK((chunk_kind='problem' AND source_field IN ('body_text','title')) OR (chunk_kind='solution' AND source_field='attributes.solution_text') OR (chunk_kind='business_answer' AND source_field='body_text'));
-- postgres-only
ALTER TABLE knowledge.document_chunk ADD COLUMN context_json JSONB NOT NULL DEFAULT '{}';
-- postgres-only
ALTER TABLE knowledge.retrieval_revision ALTER COLUMN index_id DROP NOT NULL;
-- postgres-only
ALTER TABLE knowledge.retrieval_revision DROP CONSTRAINT retrieval_revision_configuration_version_check;
-- postgres-only
ALTER TABLE knowledge.retrieval_revision ADD CONSTRAINT retrieval_revision_configuration_version_check CHECK(configuration_version IN (0,2,3,4,5));
-- sqlite-only
CREATE TABLE "knowledge.document_on_demand" (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
 source_object_type TEXT NOT NULL,
 external_id TEXT NOT NULL,
 external_number TEXT NOT NULL,
 document_kind TEXT NOT NULL CHECK(document_kind IN ('defect','ticket','requirement','article','code_answer')),
 current_revision_id TEXT,
 lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('pending','active','unavailable','deleted')),
 created_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL,
 source_observed_stamp_raw INTEGER CHECK(source_observed_stamp_raw IS NULL OR source_observed_stamp_raw>0),
 UNIQUE(id,source_id),
 UNIQUE(source_id,source_object_type,external_id),
 UNIQUE(source_id,source_object_type,external_id,id),
 FOREIGN KEY(id,current_revision_id) REFERENCES "knowledge.document_revision"(document_id,id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(lifecycle_state<>'pending' OR current_revision_id IS NULL)
);
-- sqlite-only
INSERT INTO "knowledge.document_on_demand" (id,source_id,source_object_type,external_id,external_number,document_kind,current_revision_id,lifecycle_state,created_at,last_seen_at,source_observed_stamp_raw) SELECT id,source_id,source_object_type,external_id,external_number,document_kind,current_revision_id,lifecycle_state,created_at,last_seen_at,source_observed_stamp_raw FROM "knowledge.document";
-- sqlite-only
DROP TABLE "knowledge.document";
-- sqlite-only
ALTER TABLE "knowledge.document_on_demand" RENAME TO "knowledge.document";
-- sqlite-only
CREATE INDEX knowledge_document_kind_idx ON "knowledge.document"(source_id,document_kind);
-- sqlite-only
CREATE TABLE "knowledge.document_revision_on_demand" (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES "knowledge.document"(id),
    revision_no INTEGER NOT NULL CHECK(revision_no>0),
    import_run_id TEXT REFERENCES "knowledge.import_run"(id),
    title TEXT NOT NULL,
    body_text TEXT NOT NULL,
    source_project_id TEXT,
    source_project_name TEXT,
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
    origin_kind TEXT NOT NULL DEFAULT 'import' CHECK(origin_kind IN ('import','code_analysis')),
    code_analysis_id TEXT UNIQUE REFERENCES "knowledge.code_analysis"(id),
    CHECK((origin_kind='import' AND import_run_id IS NOT NULL AND code_analysis_id IS NULL AND source_project_id IS NOT NULL AND source_project_name IS NOT NULL) OR (origin_kind='code_analysis' AND import_run_id IS NULL AND code_analysis_id IS NOT NULL AND source_project_id IS NULL AND source_project_name IS NULL)),
    UNIQUE(document_id, revision_no),
    UNIQUE(document_id, id)
);
-- sqlite-only
INSERT INTO "knowledge.document_revision_on_demand" (id,document_id,revision_no,import_run_id,title,body_text,source_project_id,source_project_name,source_status_id,source_status_name,source_created_at,source_updated_at,source_update_stamp_raw,source_snapshot,attributes,completeness,normalizer_version,content_hash,ingested_at) SELECT id,document_id,revision_no,import_run_id,title,body_text,source_project_id,source_project_name,source_status_id,source_status_name,source_created_at,source_updated_at,source_update_stamp_raw,source_snapshot,attributes,completeness,normalizer_version,content_hash,ingested_at FROM "knowledge.document_revision";
-- sqlite-only
DROP TABLE "knowledge.document_revision";
-- sqlite-only
ALTER TABLE "knowledge.document_revision_on_demand" RENAME TO "knowledge.document_revision";
-- sqlite-only
CREATE INDEX knowledge_revision_project_idx ON "knowledge.document_revision" (source_project_id, source_updated_at);
-- sqlite-only
CREATE INDEX knowledge_revision_created_idx ON "knowledge.document_revision"(source_project_id,source_created_at,document_id);
-- sqlite-only
CREATE TABLE "knowledge.document_chunk_on_demand" (
    id TEXT PRIMARY KEY,
    chunk_set_id TEXT NOT NULL REFERENCES "knowledge.document_chunk_set"(id),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    chunk_kind TEXT NOT NULL CHECK(chunk_kind IN ('problem','solution','business_answer')),
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
    context_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(chunk_set_id, ordinal),
    CHECK((chunk_kind='problem' AND source_field IN ('body_text','title')) OR (chunk_kind='solution' AND source_field='attributes.solution_text') OR (chunk_kind='business_answer' AND source_field='body_text'))
);
-- sqlite-only
INSERT INTO "knowledge.document_chunk_on_demand" (id,chunk_set_id,ordinal,chunk_kind,source_field,source_start,source_end,evidence_text,embedding_text,char_count,embedding_char_count,evidence_hash,embedding_hash,quality_flags) SELECT id,chunk_set_id,ordinal,chunk_kind,source_field,source_start,source_end,evidence_text,embedding_text,char_count,embedding_char_count,evidence_hash,embedding_hash,quality_flags FROM "knowledge.document_chunk";
-- sqlite-only
DROP TABLE "knowledge.document_chunk";
-- sqlite-only
ALTER TABLE "knowledge.document_chunk_on_demand" RENAME TO "knowledge.document_chunk";
-- sqlite-only
CREATE TABLE "knowledge.retrieval_revision_on_demand" (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES "knowledge.retrieval_resource"(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    binding_id TEXT REFERENCES "knowledge.source_binding"(id),
    index_id TEXT,
    profile_hash TEXT NOT NULL CHECK(length(profile_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by TEXT,
    published_at TEXT,
    storage_config_json TEXT, configuration_version INTEGER NOT NULL DEFAULT 0 CHECK(configuration_version IN (0,2,3,4,5)),
    CHECK((published_by IS NULL AND published_at IS NULL) OR (published_by IS NOT NULL AND published_at IS NOT NULL)),
    UNIQUE(resource_id,revision),
    UNIQUE(resource_id,id)
);
-- sqlite-only
INSERT INTO "knowledge.retrieval_revision_on_demand" (id,resource_id,revision,binding_id,index_id,profile_hash,corpus_hash,config_hash,created_by,created_at,published_by,published_at,storage_config_json) SELECT id,resource_id,revision,binding_id,index_id,profile_hash,corpus_hash,config_hash,created_by,created_at,published_by,published_at,storage_config_json FROM "knowledge.retrieval_revision";
-- sqlite-only
DROP TABLE "knowledge.retrieval_revision";
-- sqlite-only
ALTER TABLE "knowledge.retrieval_revision_on_demand" RENAME TO "knowledge.retrieval_revision";
-- postgres-only
CREATE TABLE knowledge.code_repository (
 source_id TEXT PRIMARY KEY REFERENCES knowledge.source(id),
 repository_uuid UUID NOT NULL,
 branch_path TEXT NOT NULL,
 repository_root_url TEXT NOT NULL,
 verified_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(repository_uuid,branch_path)
);
-- sqlite-only
CREATE TABLE "knowledge.code_repository" (
 source_id TEXT PRIMARY KEY REFERENCES "knowledge.source"(id),
 repository_uuid TEXT NOT NULL,
 branch_path TEXT NOT NULL,
 repository_root_url TEXT NOT NULL,
 verified_at TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(repository_uuid,branch_path)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_repository IS '已确认 SVN 仓库与分支来源';
-- postgres-only
COMMENT ON COLUMN knowledge.code_repository.source_id IS '固定仓库 UUID 与分支的来源标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_repository.repository_uuid IS '真实 SVN info 核实的仓库 UUID';
-- postgres-only
COMMENT ON COLUMN knowledge.code_repository.branch_path IS '仓库根相对分支路径，根分支为空串';
-- postgres-only
COMMENT ON COLUMN knowledge.code_repository.repository_root_url IS '经登记核实的仓库根 URL，不含认证信息';
-- postgres-only
COMMENT ON COLUMN knowledge.code_repository.verified_at IS '最近完成身份或工作副本核验的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_repository.created_at IS '记录首次创建的 UTC 时间';
-- postgres-only
CREATE TABLE knowledge.code_checkout (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES knowledge.code_repository(source_id),
 root_key TEXT NOT NULL,
 relative_dir TEXT NOT NULL,
 physical_key TEXT UNIQUE,
 selected_paths_json JSONB NOT NULL DEFAULT '[]',
 state TEXT NOT NULL CHECK(state IN ('preparing','ready','invalid','retired')),
 verified_revision BIGINT CHECK(verified_revision>=0),
 generation BIGINT NOT NULL DEFAULT 0 CHECK(generation>=0),
 writer_operation_id TEXT,
 verified_at TIMESTAMPTZ,
 invalid_reason TEXT,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 UNIQUE(id,source_id),
 UNIQUE(root_key,relative_dir),
 CHECK(state<>'ready' OR (physical_key IS NOT NULL AND verified_revision IS NOT NULL AND verified_at IS NOT NULL))
);
-- sqlite-only
CREATE TABLE "knowledge.code_checkout" (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES "knowledge.code_repository"(source_id),
 root_key TEXT NOT NULL,
 relative_dir TEXT NOT NULL,
 physical_key TEXT UNIQUE,
 selected_paths_json TEXT NOT NULL DEFAULT '[]',
 state TEXT NOT NULL CHECK(state IN ('preparing','ready','invalid','retired')),
 verified_revision BIGINT CHECK(verified_revision>=0),
 generation BIGINT NOT NULL DEFAULT 0 CHECK(generation>=0),
 writer_operation_id TEXT,
 verified_at TEXT,
 invalid_reason TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(id,source_id),
 UNIQUE(root_key,relative_dir),
 CHECK(state<>'ready' OR (physical_key IS NOT NULL AND verified_revision IS NOT NULL AND verified_at IS NOT NULL)),
 FOREIGN KEY(id,writer_operation_id) REFERENCES "knowledge.code_svn_operation"(checkout_id,id) DEFERRABLE INITIALLY DEFERRED
);
-- postgres-only
COMMENT ON TABLE knowledge.code_checkout IS '受管工作副本和唯一写占用';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.id IS '本记录稳定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.source_id IS '固定仓库 UUID 与分支的来源标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.root_key IS '部署登记的检出根键，不保存宿主绝对路径';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.relative_dir IS '检出根下的规范相对目录';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.physical_key IS '执行器核实的真实目录身份摘要；初次检出待建目录可空，ready 必填';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.selected_paths_json IS '已完整检出的文件与目录范围，不是全仓文件清单';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.state IS '工作副本状态：准备、可分析、失效或退役';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.verified_revision IS '已核实工作副本 operative revision，非最后修改版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.generation IS '当前目录修改代次，新读者不得递增';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.writer_operation_id IS '占有目录独占修改权的 SVN 操作标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.verified_at IS '最近完成身份或工作副本核验的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.invalid_reason IS '工作副本不可分析的固定安全错误码';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.created_at IS '记录首次创建的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_checkout.updated_at IS '本记录最近更新的 UTC 时间';
-- postgres-only
CREATE TABLE knowledge.code_resource_config (
 revision_id TEXT PRIMARY KEY REFERENCES knowledge.retrieval_revision(id),
 source_id TEXT REFERENCES knowledge.code_repository(source_id),
 checkout_id TEXT,
 svn_access_ref TEXT,
 allowed_paths_json JSONB NOT NULL DEFAULT '[]',
 UNIQUE(revision_id,source_id),
 CHECK(checkout_id IS NULL OR source_id IS NOT NULL),
 FOREIGN KEY(checkout_id,source_id) REFERENCES knowledge.code_checkout(id,source_id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_resource_config" (
 revision_id TEXT PRIMARY KEY REFERENCES "knowledge.retrieval_revision"(id),
 source_id TEXT REFERENCES "knowledge.code_repository"(source_id),
 checkout_id TEXT,
 svn_access_ref TEXT,
 allowed_paths_json TEXT NOT NULL DEFAULT '[]',
 UNIQUE(revision_id,source_id),
 CHECK(checkout_id IS NULL OR source_id IS NOT NULL),
 FOREIGN KEY(checkout_id,source_id) REFERENCES "knowledge.code_checkout"(id,source_id)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_resource_config IS '代码知识库资源配置修订扩展';
-- postgres-only
COMMENT ON COLUMN knowledge.code_resource_config.revision_id IS '对应共享内容或资源配置修订的标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_resource_config.source_id IS '固定仓库 UUID 与分支的来源标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_resource_config.checkout_id IS '绑定的受管真实工作副本标识，与来源复合校验';
-- postgres-only
COMMENT ON COLUMN knowledge.code_resource_config.svn_access_ref IS '部署登记的 SVN 访问凭据引用，不保存凭据值';
-- postgres-only
COMMENT ON COLUMN knowledge.code_resource_config.allowed_paths_json IS '本配置允许分析的来源相对路径集合';
-- postgres-only
CREATE TABLE knowledge.code_analysis (
 id TEXT PRIMARY KEY,
 job_id TEXT NOT NULL REFERENCES agent_job(id),
 invocation_id TEXT NOT NULL,
 owner_instance_id TEXT NOT NULL,
 knowledge_base_id TEXT NOT NULL REFERENCES knowledge.knowledge_base(id),
 config_revision_id TEXT NOT NULL,
 checkout_id TEXT NOT NULL,
 source_id TEXT NOT NULL,
 requested_revision BIGINT NOT NULL CHECK(requested_revision>=0),
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
 exact_search_id TEXT NOT NULL,
 question_hash TEXT NOT NULL CHECK(length(question_hash)=64),
 authorization_hash TEXT NOT NULL CHECK(length(authorization_hash)=64),
 state TEXT NOT NULL CHECK(state IN ('preparing','reading','validating','completed','partial','conflicted','failed','cancelled')),
 generation BIGINT CHECK(generation>=0),
 read_acquired_at TIMESTAMPTZ,
 read_revoked_at TIMESTAMPTZ,
 reads_quiesced_at TIMESTAMPTZ,
 read_released_at TIMESTAMPTZ,
 lease_until TIMESTAMPTZ,
 deadline_at TIMESTAMPTZ NOT NULL,
 saved_revision_id TEXT,
 save_request_hash TEXT CHECK(save_request_hash IS NULL OR length(save_request_hash)=64),
 report_json JSONB NOT NULL DEFAULT '{}',
 closed_at TIMESTAMPTZ,
 error_code TEXT,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 UNIQUE(id,checkout_id,source_id),
 FOREIGN KEY(job_id,invocation_id) REFERENCES agent_runtime_invocation(job_id,invocation_id),
 FOREIGN KEY(checkout_id,source_id) REFERENCES knowledge.code_checkout(id,source_id),
 FOREIGN KEY(config_revision_id,source_id) REFERENCES knowledge.code_resource_config(revision_id,source_id),
 CHECK(read_acquired_at IS NULL OR (generation IS NOT NULL AND lease_until IS NOT NULL)),
 CHECK(read_released_at IS NULL OR (read_acquired_at IS NOT NULL AND reads_quiesced_at IS NOT NULL)),
 CHECK(closed_at IS NULL OR read_acquired_at IS NULL OR read_released_at IS NOT NULL),
 CHECK(state NOT IN ('reading','validating') OR (read_acquired_at IS NOT NULL AND read_released_at IS NULL))
);
-- sqlite-only
CREATE TABLE "knowledge.code_analysis" (
 id TEXT PRIMARY KEY,
 job_id TEXT NOT NULL REFERENCES agent_job(id),
 invocation_id TEXT NOT NULL,
 owner_instance_id TEXT NOT NULL,
 knowledge_base_id TEXT NOT NULL REFERENCES "knowledge.knowledge_base"(id),
 config_revision_id TEXT NOT NULL,
 checkout_id TEXT NOT NULL,
 source_id TEXT NOT NULL,
 requested_revision BIGINT NOT NULL CHECK(requested_revision>=0),
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
 exact_search_id TEXT NOT NULL,
 question_hash TEXT NOT NULL CHECK(length(question_hash)=64),
 authorization_hash TEXT NOT NULL CHECK(length(authorization_hash)=64),
 state TEXT NOT NULL CHECK(state IN ('preparing','reading','validating','completed','partial','conflicted','failed','cancelled')),
 generation BIGINT CHECK(generation>=0),
 read_acquired_at TEXT,
 read_revoked_at TEXT,
 reads_quiesced_at TEXT,
 read_released_at TEXT,
 lease_until TEXT,
 deadline_at TEXT NOT NULL,
 saved_revision_id TEXT REFERENCES "knowledge.code_answer_revision"(revision_id) DEFERRABLE INITIALLY DEFERRED,
 save_request_hash TEXT CHECK(save_request_hash IS NULL OR length(save_request_hash)=64),
 report_json TEXT NOT NULL DEFAULT '{}',
 closed_at TEXT,
 error_code TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(id,checkout_id,source_id),
 FOREIGN KEY(job_id,invocation_id) REFERENCES agent_runtime_invocation(job_id,invocation_id),
 FOREIGN KEY(checkout_id,source_id) REFERENCES "knowledge.code_checkout"(id,source_id),
 FOREIGN KEY(config_revision_id,source_id) REFERENCES "knowledge.code_resource_config"(revision_id,source_id),
 CHECK(read_acquired_at IS NULL OR (generation IS NOT NULL AND lease_until IS NOT NULL)),
 CHECK(read_released_at IS NULL OR (read_acquired_at IS NOT NULL AND reads_quiesced_at IS NOT NULL)),
 CHECK(closed_at IS NULL OR read_acquired_at IS NULL OR read_released_at IS NOT NULL),
 CHECK(state NOT IN ('reading','validating') OR (read_acquired_at IS NOT NULL AND read_released_at IS NULL))
);
-- postgres-only
COMMENT ON TABLE knowledge.code_analysis IS '原问答任务的分析和独立共享读占用';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.id IS '本记录稳定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.job_id IS '原标准问答 Job 标识，不创建独立提取任务';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.invocation_id IS '当前 Runtime 调用标识，与 Job 组成复合引用';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.owner_instance_id IS '实际执行实例标识，用于拒绝旧执行器提交';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.knowledge_base_id IS '当前问答或索引任务所属知识库';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.config_revision_id IS '准入时固定的代码资源配置修订';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.checkout_id IS '绑定的受管真实工作副本标识，与来源复合校验';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.source_id IS '固定仓库 UUID 与分支的来源标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.requested_revision IS '用户明确指定的目标 SVN 数字版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.request_key IS '服务端绑定调用者与操作身份的幂等键';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.request_hash IS '规范请求和执行身份摘要，同键不同请求拒绝';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.exact_search_id IS '原 Job 成功相等版本检索的审计标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.question_hash IS '规范化业务问题的 SHA256 摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.authorization_hash IS '准入时冻结的来源授权范围摘要，不能替代当前授权';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.state IS '原 Job 分析阶段；是否阻止更新另以读占用时间字段判定';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.generation IS '当前目录修改代次，新读者不得递增';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.read_acquired_at IS '本分析开始阻止目录写入的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.read_revoked_at IS '本分析停止接受新源码读取的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.reads_quiesced_at IS '已确认本分析在途源码读取全部停止的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.read_released_at IS '实际停止后释放本分析读占用的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.lease_until IS '执行租约截止；到期不代表旧进程已经停止';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.deadline_at IS '受原 Job 总预算约束的不可延长截止';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.saved_revision_id IS '本分析新建或幂等复用的代码答案内容修订';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.save_request_hash IS '已提交答案保存请求摘要，防不同内容伪装重放';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.report_json IS '脱敏的结论、覆盖与未知项；部分结论不进入确定答案索引';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.closed_at IS '确认相关执行停止且已释放占用后的关闭时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.error_code IS '固定机器错误码，不保存原始异常或源码';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.created_at IS '记录首次创建的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_analysis.updated_at IS '本记录最近更新的 UTC 时间';
-- postgres-only
CREATE TABLE knowledge.code_svn_operation (
 id TEXT PRIMARY KEY,
 source_id TEXT REFERENCES knowledge.code_repository(source_id),
 checkout_id TEXT,
 analysis_id TEXT,
 job_id TEXT,
 invocation_id TEXT,
 actor_id TEXT NOT NULL REFERENCES app_user(id),
 config_revision_id TEXT NOT NULL REFERENCES knowledge.code_resource_config(revision_id),
 operation_kind TEXT NOT NULL CHECK(operation_kind IN ('browse','checkout','info','update','log','diff','blame','repair','retire')),
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
 state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','interrupted','cancelled')),
 target_revision BIGINT CHECK(target_revision>=0),
 from_revision BIGINT CHECK(from_revision>=0),
 to_revision BIGINT CHECK(to_revision>=0),
 peg_revision BIGINT CHECK(peg_revision>=0),
 request_json JSONB NOT NULL DEFAULT '{}',
 result_json JSONB NOT NULL DEFAULT '{}',
 result_hash TEXT CHECK(result_hash IS NULL OR length(result_hash)=64),
 checkout_generation BIGINT CHECK(checkout_generation>=0),
 owner_instance_id TEXT,
 claim_version BIGINT NOT NULL DEFAULT 0 CHECK(claim_version>=0),
 lease_until TIMESTAMPTZ,
 deadline_at TIMESTAMPTZ NOT NULL,
 started_at TIMESTAMPTZ,
 quiesced_at TIMESTAMPTZ,
 finished_at TIMESTAMPTZ,
 error_code TEXT,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 UNIQUE(checkout_id,id),
 FOREIGN KEY(checkout_id,source_id) REFERENCES knowledge.code_checkout(id,source_id),
 FOREIGN KEY(analysis_id,checkout_id,source_id) REFERENCES knowledge.code_analysis(id,checkout_id,source_id),
 FOREIGN KEY(job_id,invocation_id) REFERENCES agent_runtime_invocation(job_id,invocation_id),
 CHECK((job_id IS NULL AND invocation_id IS NULL) OR (job_id IS NOT NULL AND invocation_id IS NOT NULL)),
 CHECK(analysis_id IS NULL OR (checkout_id IS NOT NULL AND job_id IS NOT NULL)),
 CHECK(source_id IS NOT NULL OR (operation_kind='browse' AND analysis_id IS NULL AND state<>'succeeded')),
 CHECK(operation_kind NOT IN ('checkout','update') OR (checkout_id IS NOT NULL AND target_revision IS NOT NULL)),
 CHECK(state<>'running' OR (owner_instance_id IS NOT NULL AND lease_until IS NOT NULL AND started_at IS NOT NULL))
);
-- sqlite-only
CREATE TABLE "knowledge.code_svn_operation" (
 id TEXT PRIMARY KEY,
 source_id TEXT REFERENCES "knowledge.code_repository"(source_id),
 checkout_id TEXT,
 analysis_id TEXT,
 job_id TEXT,
 invocation_id TEXT,
 actor_id TEXT NOT NULL REFERENCES app_user(id),
 config_revision_id TEXT NOT NULL REFERENCES "knowledge.code_resource_config"(revision_id),
 operation_kind TEXT NOT NULL CHECK(operation_kind IN ('browse','checkout','info','update','log','diff','blame','repair','retire')),
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
 state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','interrupted','cancelled')),
 target_revision BIGINT CHECK(target_revision>=0),
 from_revision BIGINT CHECK(from_revision>=0),
 to_revision BIGINT CHECK(to_revision>=0),
 peg_revision BIGINT CHECK(peg_revision>=0),
 request_json TEXT NOT NULL DEFAULT '{}',
 result_json TEXT NOT NULL DEFAULT '{}',
 result_hash TEXT CHECK(result_hash IS NULL OR length(result_hash)=64),
 checkout_generation BIGINT CHECK(checkout_generation>=0),
 owner_instance_id TEXT,
 claim_version BIGINT NOT NULL DEFAULT 0 CHECK(claim_version>=0),
 lease_until TEXT,
 deadline_at TEXT NOT NULL,
 started_at TEXT,
 quiesced_at TEXT,
 finished_at TEXT,
 error_code TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(checkout_id,id),
 FOREIGN KEY(checkout_id,source_id) REFERENCES "knowledge.code_checkout"(id,source_id),
 FOREIGN KEY(analysis_id,checkout_id,source_id) REFERENCES "knowledge.code_analysis"(id,checkout_id,source_id),
 FOREIGN KEY(job_id,invocation_id) REFERENCES agent_runtime_invocation(job_id,invocation_id),
 CHECK((job_id IS NULL AND invocation_id IS NULL) OR (job_id IS NOT NULL AND invocation_id IS NOT NULL)),
 CHECK(analysis_id IS NULL OR (checkout_id IS NOT NULL AND job_id IS NOT NULL)),
 CHECK(source_id IS NOT NULL OR (operation_kind='browse' AND analysis_id IS NULL AND state<>'succeeded')),
 CHECK(operation_kind NOT IN ('checkout','update') OR (checkout_id IS NOT NULL AND target_revision IS NOT NULL)),
 CHECK(state<>'running' OR (owner_instance_id IS NOT NULL AND lease_until IS NOT NULL AND started_at IS NOT NULL))
);
-- postgres-only
COMMENT ON TABLE knowledge.code_svn_operation IS '受管 SVN 浏览检出更新和历史操作';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.id IS '本记录稳定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.source_id IS '实际核实的仓库分支来源；首次管理浏览完成前可空，问答操作必填';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.checkout_id IS '绑定的受管真实工作副本标识，与来源复合校验';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.analysis_id IS '产生本证据的原 Job 分析标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.job_id IS '原标准问答 Job 标识，不创建独立提取任务';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.invocation_id IS '当前 Runtime 调用标识，与 Job 组成复合引用';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.actor_id IS '经过平台认证的当前操作用户标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.config_revision_id IS '准入时固定的代码资源配置修订';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.operation_kind IS '受管 SVN 操作种类，不接受任意命令';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.request_key IS '服务端绑定调用者与操作身份的幂等键';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.request_hash IS '规范请求和执行身份摘要，同键不同请求拒绝';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.state IS 'SVN 操作排队、运行及结束状态；停止证明单独保存';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.target_revision IS '操作固定目标 SVN 版本，不以 HEAD 作为问答目标';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.from_revision IS '历史查询起点或差异左端 SVN 版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.to_revision IS '历史查询终点或差异右端 SVN 版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.peg_revision IS '确定历史文件身份的 SVN peg 版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.request_json IS '已校验的路径、版本、时间和分页参数，不含命令串或凭据';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.result_json IS '有界结果元数据与计数，不持久化原始 diff、源码或提交说明';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.result_hash IS '实际返回的有界结果摘要，用于重取一致性核验';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.checkout_generation IS '操作绑定的工作副本修改代次';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.owner_instance_id IS '实际执行实例标识，用于拒绝旧执行器提交';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.claim_version IS '每次执行领取递增的提交代次，用于阻断旧执行器';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.lease_until IS '执行租约截止；到期不代表旧进程已经停止';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.deadline_at IS '受原 Job 总预算约束的不可延长截止';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.started_at IS '本次实际执行开始的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.quiesced_at IS '确认 SVN 子进程已经退出的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.finished_at IS '操作或派生任务结束的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.error_code IS '固定机器错误码，不保存原始异常或源码';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.created_at IS '记录首次创建的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_svn_operation.updated_at IS '本记录最近更新的 UTC 时间';
-- postgres-only
CREATE TABLE knowledge.code_evidence (
 id TEXT PRIMARY KEY,
 analysis_id TEXT NOT NULL REFERENCES knowledge.code_analysis(id),
 kind TEXT NOT NULL CHECK(kind IN ('file_read','svn_history')),
 relative_path TEXT,
 symbol TEXT,
 line_start INTEGER CHECK(line_start>0),
 line_end INTEGER CHECK(line_end>=line_start),
 svn_revision BIGINT NOT NULL CHECK(svn_revision>=0),
 peg_revision BIGINT CHECK(peg_revision>=0),
 repository_content_hash TEXT CHECK(repository_content_hash IS NULL OR length(repository_content_hash)=64),
 read_content_hash TEXT CHECK(read_content_hash IS NULL OR length(read_content_hash)=64),
 representation_json JSONB NOT NULL DEFAULT '{}',
 tool_call_id TEXT NOT NULL,
 operation_id TEXT REFERENCES knowledge.code_svn_operation(id),
 from_revision BIGINT CHECK(from_revision>=0),
 to_revision BIGINT CHECK(to_revision>=0),
 result_hash TEXT CHECK(result_hash IS NULL OR length(result_hash)=64),
 evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
 observed_at TIMESTAMPTZ NOT NULL,
 validated_at TIMESTAMPTZ,
 UNIQUE(analysis_id,evidence_hash),
 CHECK(kind<>'file_read' OR (relative_path IS NOT NULL AND line_start IS NOT NULL AND line_end IS NOT NULL AND repository_content_hash IS NOT NULL AND read_content_hash IS NOT NULL)),
 CHECK(kind<>'svn_history' OR (operation_id IS NOT NULL AND result_hash IS NOT NULL))
);
-- sqlite-only
CREATE TABLE "knowledge.code_evidence" (
 id TEXT PRIMARY KEY,
 analysis_id TEXT NOT NULL REFERENCES "knowledge.code_analysis"(id),
 kind TEXT NOT NULL CHECK(kind IN ('file_read','svn_history')),
 relative_path TEXT,
 symbol TEXT,
 line_start INTEGER CHECK(line_start>0),
 line_end INTEGER CHECK(line_end>=line_start),
 svn_revision BIGINT NOT NULL CHECK(svn_revision>=0),
 peg_revision BIGINT CHECK(peg_revision>=0),
 repository_content_hash TEXT CHECK(repository_content_hash IS NULL OR length(repository_content_hash)=64),
 read_content_hash TEXT CHECK(read_content_hash IS NULL OR length(read_content_hash)=64),
 representation_json TEXT NOT NULL DEFAULT '{}',
 tool_call_id TEXT NOT NULL,
 operation_id TEXT REFERENCES "knowledge.code_svn_operation"(id),
 from_revision BIGINT CHECK(from_revision>=0),
 to_revision BIGINT CHECK(to_revision>=0),
 result_hash TEXT CHECK(result_hash IS NULL OR length(result_hash)=64),
 evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
 observed_at TEXT NOT NULL,
 validated_at TEXT,
 UNIQUE(analysis_id,evidence_hash),
 CHECK(kind<>'file_read' OR (relative_path IS NOT NULL AND line_start IS NOT NULL AND line_end IS NOT NULL AND repository_content_hash IS NOT NULL AND read_content_hash IS NOT NULL)),
 CHECK(kind<>'svn_history' OR (operation_id IS NOT NULL AND result_hash IS NOT NULL))
);
-- postgres-only
COMMENT ON TABLE knowledge.code_evidence IS '实际代码读取或 SVN 历史证据元数据';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.id IS '本记录稳定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.analysis_id IS '产生本证据的原 Job 分析标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.kind IS '实际文件读取或 SVN 历史证据种类';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.relative_path IS '仓库分支内规范相对文件路径';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.symbol IS '证据对应的函数或业务符号，可未知';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.line_start IS '模型实际读取范围的原文件起始行，从 1 开始';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.line_end IS '模型实际读取范围的原文件结束行，包含该行';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.svn_revision IS '证据或答案明确对应的 SVN 数字版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.peg_revision IS '确定历史文件身份的 SVN peg 版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.repository_content_hash IS '指定 SVN 版本仓库文件字节的 SHA256';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.read_content_hash IS '模型实际取得文本表示的 SHA256';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.representation_json IS '编码、换行、关键字转换与原行号映射的核验信息';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.tool_call_id IS '真正返回证据的工具调用标识，不接受模型自报已读';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.operation_id IS '产生历史证据的受控 SVN 操作标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.from_revision IS '历史查询起点或差异左端 SVN 版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.to_revision IS '历史查询终点或差异右端 SVN 版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.result_hash IS '实际返回的有界结果摘要，用于重取一致性核验';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.evidence_hash IS '规范证据身份和内容摘要，用于同分析去重';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.observed_at IS '实际取得证据或 revision 属性的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_evidence.validated_at IS '证据或答案引用校验通过的 UTC 时间';
-- postgres-only
CREATE TABLE knowledge.code_answer (
 document_id TEXT PRIMARY KEY REFERENCES knowledge.document(id),
 source_id TEXT NOT NULL REFERENCES knowledge.code_repository(source_id),
 svn_revision BIGINT NOT NULL CHECK(svn_revision>=0),
 question_text TEXT NOT NULL,
 question_hash TEXT NOT NULL CHECK(length(question_hash)=64),
 conditions_json JSONB NOT NULL DEFAULT '{}',
 conditions_hash TEXT NOT NULL CHECK(length(conditions_hash)=64),
 visibility_scope_json JSONB NOT NULL DEFAULT '{}',
 visibility_scope_hash TEXT NOT NULL CHECK(length(visibility_scope_hash)=64),
 identity_hash TEXT NOT NULL CHECK(length(identity_hash)=64),
 created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(source_id,svn_revision,identity_hash),
 FOREIGN KEY(document_id,source_id) REFERENCES knowledge.document(id,source_id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_answer" (
 document_id TEXT PRIMARY KEY REFERENCES "knowledge.document"(id),
 source_id TEXT NOT NULL REFERENCES "knowledge.code_repository"(source_id),
 svn_revision BIGINT NOT NULL CHECK(svn_revision>=0),
 question_text TEXT NOT NULL,
 question_hash TEXT NOT NULL CHECK(length(question_hash)=64),
 conditions_json TEXT NOT NULL DEFAULT '{}',
 conditions_hash TEXT NOT NULL CHECK(length(conditions_hash)=64),
 visibility_scope_json TEXT NOT NULL DEFAULT '{}',
 visibility_scope_hash TEXT NOT NULL CHECK(length(visibility_scope_hash)=64),
 identity_hash TEXT NOT NULL CHECK(length(identity_hash)=64),
 created_at TEXT NOT NULL,
 UNIQUE(source_id,svn_revision,identity_hash),
 FOREIGN KEY(document_id,source_id) REFERENCES "knowledge.document"(id,source_id)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_answer IS '指定 SVN 版本的业务问题条件与可见范围身份';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.document_id IS '共享知识文档标识，代码答案固定一个 SVN 版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.source_id IS '固定仓库 UUID 与分支的来源标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.svn_revision IS '证据或答案明确对应的 SVN 数字版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.question_text IS '允许共享的规范化业务问题，不存原始对话';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.question_hash IS '规范化业务问题的 SHA256 摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.conditions_json IS '规则适用的对象、操作及配置条件，不含私有实例值';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.conditions_hash IS '规范适用条件的 SHA256';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.visibility_scope_json IS '平台生成的可共享来源路径与业务范围，不是授权凭据';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.visibility_scope_hash IS '规范可见范围的 SHA256';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.identity_hash IS '规范化版本、问题、条件及可见范围组成的答案身份摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer.created_at IS '记录首次创建的 UTC 时间';
-- postgres-only
CREATE TABLE knowledge.code_answer_revision (
 revision_id TEXT PRIMARY KEY REFERENCES knowledge.document_revision(id),
 document_id TEXT NOT NULL REFERENCES knowledge.code_answer(document_id),
 claims_json JSONB NOT NULL,
 coverage_json JSONB NOT NULL DEFAULT '{}',
 unknowns_json JSONB NOT NULL DEFAULT '[]',
 validation_version TEXT NOT NULL,
 validated_at TIMESTAMPTZ NOT NULL,
 UNIQUE(document_id,revision_id),
 FOREIGN KEY(document_id,revision_id) REFERENCES knowledge.document_revision(document_id,id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_answer_revision" (
 revision_id TEXT PRIMARY KEY REFERENCES "knowledge.document_revision"(id),
 document_id TEXT NOT NULL REFERENCES "knowledge.code_answer"(document_id),
 claims_json TEXT NOT NULL,
 coverage_json TEXT NOT NULL DEFAULT '{}',
 unknowns_json TEXT NOT NULL DEFAULT '[]',
 validation_version TEXT NOT NULL,
 validated_at TEXT NOT NULL,
 UNIQUE(document_id,revision_id),
 FOREIGN KEY(document_id,revision_id) REFERENCES "knowledge.document_revision"(document_id,id)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_answer_revision IS '有实际代码证据支持的业务答案内容修订扩展';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer_revision.revision_id IS '对应共享内容或资源配置修订的标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer_revision.document_id IS '共享知识文档标识，代码答案固定一个 SVN 版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer_revision.claims_json IS '分项结论、条件和本分析实际证据 ID 引用';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer_revision.coverage_json IS '已核验的入口、模块和调用范围';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer_revision.unknowns_json IS '明确未知项；关键未知不得进入确定答案内容修订';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer_revision.validation_version IS '保存时证据与引用校验算法版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_answer_revision.validated_at IS '证据或答案引用校验通过的 UTC 时间';
-- postgres-only
CREATE TABLE knowledge.code_qa_record (
 id TEXT PRIMARY KEY,
 job_id TEXT NOT NULL REFERENCES agent_job(id),
 result_revision INTEGER NOT NULL CHECK(result_revision>0),
 knowledge_base_id TEXT NOT NULL REFERENCES knowledge.knowledge_base(id),
 actor_id TEXT NOT NULL REFERENCES app_user(id),
 source_id TEXT NOT NULL REFERENCES knowledge.code_repository(source_id),
 requested_revisions BIGINT[] NOT NULL,
 question_text TEXT NOT NULL,
 answer_text TEXT NOT NULL,
 answer_hash TEXT NOT NULL CHECK(length(answer_hash)=64),
 support_status TEXT NOT NULL CHECK(support_status IN ('supported','partial','conflicted','unverified')),
 answer_origin TEXT NOT NULL CHECK(answer_origin IN ('cache','code_analysis','mixed','unresolved')),
 references_json JSONB NOT NULL DEFAULT '[]',
 created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(job_id,result_revision,knowledge_base_id),
 CHECK(array_ndims(requested_revisions)=1 AND array_lower(requested_revisions,1)=1 AND cardinality(requested_revisions) BETWEEN 1 AND 2 AND array_position(requested_revisions,NULL) IS NULL AND requested_revisions[1]>=0 AND (cardinality(requested_revisions)=1 OR (requested_revisions[2]>=0 AND requested_revisions[1]<>requested_revisions[2])))
);
-- sqlite-only
CREATE TABLE "knowledge.code_qa_record" (
 id TEXT PRIMARY KEY,
 job_id TEXT NOT NULL REFERENCES agent_job(id),
 result_revision INTEGER NOT NULL CHECK(result_revision>0),
 knowledge_base_id TEXT NOT NULL REFERENCES "knowledge.knowledge_base"(id),
 actor_id TEXT NOT NULL REFERENCES app_user(id),
 source_id TEXT NOT NULL REFERENCES "knowledge.code_repository"(source_id),
 requested_revisions TEXT NOT NULL,
 question_text TEXT NOT NULL,
 answer_text TEXT NOT NULL,
 answer_hash TEXT NOT NULL CHECK(length(answer_hash)=64),
 support_status TEXT NOT NULL CHECK(support_status IN ('supported','partial','conflicted','unverified')),
 answer_origin TEXT NOT NULL CHECK(answer_origin IN ('cache','code_analysis','mixed','unresolved')),
 references_json TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL,
 UNIQUE(job_id,result_revision,knowledge_base_id),
 CHECK(json_valid(requested_revisions) AND json_type(requested_revisions)='array' AND json_array_length(requested_revisions) BETWEEN 1 AND 2 AND json_type(requested_revisions,'$[0]')='integer' AND json_extract(requested_revisions,'$[0]')>=0 AND (json_array_length(requested_revisions)=1 OR (json_type(requested_revisions,'$[1]')='integer' AND json_extract(requested_revisions,'$[1]')>=0 AND json_extract(requested_revisions,'$[0]')<>json_extract(requested_revisions,'$[1]'))))
);
-- postgres-only
COMMENT ON TABLE knowledge.code_qa_record IS '每次带用户 SVN 版本的受限问答结果';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.id IS '本记录稳定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.job_id IS '原标准问答 Job 标识，不创建独立提取任务';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.result_revision IS '原 Job 最终业务结果修订号，从 1 开始';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.knowledge_base_id IS '当前问答或索引任务所属知识库';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.actor_id IS '经过平台认证的当前操作用户标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.source_id IS '固定仓库 UUID 与分支的来源标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.requested_revisions IS '用户指定的一个版本或显式比较的两个不同版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.question_text IS '允许共享的规范化业务问题，不存原始对话';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.answer_text IS '本次允许持久化的规范化业务回答，不保存原始消息';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.answer_hash IS '最终回答与版本引用的幂等摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.support_status IS '结论支持状态，区分充分证据、部分、冲突和未核验';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.answer_origin IS '回答来自缓存、原 Job 代码分析、混合或未解决';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.references_json IS '实际引用的文档修订及其 SVN 版本，保留较高版本线索标记';
-- postgres-only
COMMENT ON COLUMN knowledge.code_qa_record.created_at IS '记录首次创建的 UTC 时间';
-- postgres-only
CREATE TABLE knowledge.code_index_task (
 id TEXT PRIMARY KEY,
 index_id TEXT NOT NULL REFERENCES knowledge.vector_index(id),
 document_id TEXT NOT NULL REFERENCES knowledge.code_answer(document_id),
 revision_id TEXT NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('upsert','remove')),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','cancelled')),
 step TEXT NOT NULL DEFAULT 'pending' CHECK(step IN ('pending','chunked','written','verified','exposed','cleaned','done')),
 expected_chunks INTEGER NOT NULL DEFAULT 0 CHECK(expected_chunks>=0),
 completed_chunks INTEGER NOT NULL DEFAULT 0 CHECK(completed_chunks>=0 AND completed_chunks<=expected_chunks),
 owner_instance_id TEXT,
 claim_version BIGINT NOT NULL DEFAULT 0 CHECK(claim_version>=0),
 lease_until TIMESTAMPTZ,
 attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
 next_attempt_at TIMESTAMPTZ,
 error_code TEXT,
 ready_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 finished_at TIMESTAMPTZ,
 UNIQUE(index_id,revision_id,action),
 FOREIGN KEY(document_id,revision_id) REFERENCES knowledge.code_answer_revision(document_id,revision_id),
 CHECK(ready_at IS NULL OR (action='upsert' AND expected_chunks>0 AND expected_chunks=completed_chunks)),
 CHECK(state<>'running' OR (owner_instance_id IS NOT NULL AND lease_until IS NOT NULL))
);
-- sqlite-only
CREATE TABLE "knowledge.code_index_task" (
 id TEXT PRIMARY KEY,
 index_id TEXT NOT NULL REFERENCES "knowledge.vector_index"(id),
 document_id TEXT NOT NULL REFERENCES "knowledge.code_answer"(document_id),
 revision_id TEXT NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('upsert','remove')),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','cancelled')),
 step TEXT NOT NULL DEFAULT 'pending' CHECK(step IN ('pending','chunked','written','verified','exposed','cleaned','done')),
 expected_chunks INTEGER NOT NULL DEFAULT 0 CHECK(expected_chunks>=0),
 completed_chunks INTEGER NOT NULL DEFAULT 0 CHECK(completed_chunks>=0 AND completed_chunks<=expected_chunks),
 owner_instance_id TEXT,
 claim_version BIGINT NOT NULL DEFAULT 0 CHECK(claim_version>=0),
 lease_until TEXT,
 attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
 next_attempt_at TEXT,
 error_code TEXT,
 ready_at TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 finished_at TEXT,
 UNIQUE(index_id,revision_id,action),
 FOREIGN KEY(document_id,revision_id) REFERENCES "knowledge.code_answer_revision"(document_id,revision_id),
 CHECK(ready_at IS NULL OR (action='upsert' AND expected_chunks>0 AND expected_chunks=completed_chunks)),
 CHECK(state<>'running' OR (owner_instance_id IS NOT NULL AND lease_until IS NOT NULL))
);
-- postgres-only
COMMENT ON TABLE knowledge.code_index_task IS '代码答案增量向量写入与确定点清理任务';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.id IS '本记录稳定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.index_id IS '本知识库受管增量向量索引标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.document_id IS '共享知识文档标识，代码答案固定一个 SVN 版本';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.revision_id IS '对应共享内容或资源配置修订的标识';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.action IS '增量派生动作：写入当前内容或清理旧点';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.config_hash IS '固定 collection、Embedding 与分块配置摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.state IS '索引任务排队、运行、成功、失败或取消状态';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.step IS '有界派生处理进度，不代表业务内容已经可检索';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.expected_chunks IS '本修订预期产生的分块数';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.completed_chunks IS '已完整写入并核实的分块数';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.owner_instance_id IS '实际执行实例标识，用于拒绝旧执行器提交';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.claim_version IS '每次执行领取递增的提交代次，用于阻断旧执行器';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.lease_until IS '执行租约截止；到期不代表旧进程已经停止';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.attempt_count IS '本派生任务已尝试执行的次数';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.next_attempt_at IS '失败重试最早可领取的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.error_code IS '固定机器错误码，不保存原始异常或源码';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.ready_at IS '所有分块完整核验并暴露后的就绪时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.created_at IS '记录首次创建的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.updated_at IS '本记录最近更新的 UTC 时间';
-- postgres-only
COMMENT ON COLUMN knowledge.code_index_task.finished_at IS '操作或派生任务结束的 UTC 时间';
-- postgres-only
ALTER TABLE knowledge.code_checkout ADD CONSTRAINT code_checkout_writer_fk FOREIGN KEY(id,writer_operation_id) REFERENCES knowledge.code_svn_operation(checkout_id,id) DEFERRABLE INITIALLY DEFERRED;
-- postgres-only
ALTER TABLE knowledge.code_analysis ADD CONSTRAINT code_analysis_saved_fk FOREIGN KEY(saved_revision_id) REFERENCES knowledge.code_answer_revision(revision_id) DEFERRABLE INITIALLY DEFERRED;
-- postgres-only
ALTER TABLE knowledge.document_revision ADD CONSTRAINT code_revision_analysis_fk FOREIGN KEY(code_analysis_id) REFERENCES knowledge.code_analysis(id);
-- postgres-only
CREATE INDEX code_answer_revision_lookup ON knowledge.code_answer(source_id,svn_revision,document_id);
-- sqlite-only
CREATE INDEX code_answer_revision_lookup ON "knowledge.code_answer"(source_id,svn_revision,document_id);
-- postgres-only
CREATE INDEX code_included_document ON knowledge.knowledge_base_document(document_id,knowledge_base_id) WHERE state='included';
-- sqlite-only
CREATE INDEX code_included_document ON "knowledge.knowledge_base_document"(document_id,knowledge_base_id) WHERE state='included';
-- postgres-only
CREATE UNIQUE INDEX code_one_analysis_per_job ON knowledge.code_analysis(job_id) WHERE closed_at IS NULL;
-- sqlite-only
CREATE UNIQUE INDEX code_one_analysis_per_job ON "knowledge.code_analysis"(job_id) WHERE closed_at IS NULL;
-- postgres-only
CREATE INDEX code_checkout_readers ON knowledge.code_analysis(checkout_id,requested_revision) WHERE read_acquired_at IS NOT NULL AND read_released_at IS NULL;
-- sqlite-only
CREATE INDEX code_checkout_readers ON "knowledge.code_analysis"(checkout_id,requested_revision) WHERE read_acquired_at IS NOT NULL AND read_released_at IS NULL;
-- postgres-only
CREATE INDEX code_analysis_recovery ON knowledge.code_analysis(lease_until) WHERE closed_at IS NULL;
-- sqlite-only
CREATE INDEX code_analysis_recovery ON "knowledge.code_analysis"(lease_until) WHERE closed_at IS NULL;
-- postgres-only
CREATE INDEX code_svn_queue ON knowledge.code_svn_operation(state,created_at,id);
-- sqlite-only
CREATE INDEX code_svn_queue ON "knowledge.code_svn_operation"(state,created_at,id);
-- postgres-only
CREATE INDEX code_svn_checkout_history ON knowledge.code_svn_operation(checkout_id,created_at);
-- sqlite-only
CREATE INDEX code_svn_checkout_history ON "knowledge.code_svn_operation"(checkout_id,created_at);
-- postgres-only
CREATE INDEX code_analysis_evidence ON knowledge.code_evidence(analysis_id,kind);
-- sqlite-only
CREATE INDEX code_analysis_evidence ON "knowledge.code_evidence"(analysis_id,kind);
-- postgres-only
CREATE INDEX code_qa_actor_history ON knowledge.code_qa_record(actor_id,knowledge_base_id,created_at DESC);
-- sqlite-only
CREATE INDEX code_qa_actor_history ON "knowledge.code_qa_record"(actor_id,knowledge_base_id,created_at DESC);
-- postgres-only
CREATE INDEX code_index_queue ON knowledge.code_index_task(state,next_attempt_at,created_at);
-- sqlite-only
CREATE INDEX code_index_queue ON "knowledge.code_index_task"(state,next_attempt_at,created_at);
-- postgres-only
CREATE INDEX code_index_ready ON knowledge.code_index_task(index_id,revision_id) WHERE action='upsert' AND ready_at IS NOT NULL;
-- sqlite-only
CREATE INDEX code_index_ready ON "knowledge.code_index_task"(index_id,revision_id) WHERE action='upsert' AND ready_at IS NOT NULL;
-- postgres-only
CREATE UNIQUE INDEX code_index_one_writer ON knowledge.code_index_task(index_id,document_id) WHERE state='running';
-- sqlite-only
CREATE UNIQUE INDEX code_index_one_writer ON "knowledge.code_index_task"(index_id,document_id) WHERE state='running';
-- postgres-only
COMMENT ON COLUMN knowledge.knowledge_base.kind IS '知识库类型，ONES 与代码创建后不可互换';
-- postgres-only
COMMENT ON COLUMN knowledge.knowledge_base.code_indexing_paused IS '代码索引暂停只积压派生任务，不暂停问答结果保存';
-- postgres-only
COMMENT ON COLUMN knowledge.document_revision.origin_kind IS '修订来源为真实导入批次或原问答代码分析';
-- postgres-only
COMMENT ON COLUMN knowledge.document_revision.code_analysis_id IS '生成代码答案的原问答分析，与导入批次互斥';
-- postgres-only
COMMENT ON COLUMN knowledge.document_chunk.context_json IS '分块结论所需条件和证据引用，不承载认证信息';
