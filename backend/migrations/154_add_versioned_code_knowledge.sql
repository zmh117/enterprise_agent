-- 代码业务知识：只建结构，不配置来源、不授予权限、不启动任务。
-- migration: sqlite-foreign-keys-off
-- postgres-only
ALTER TABLE knowledge.document DROP CONSTRAINT document_document_kind_check;
-- postgres-only
ALTER TABLE knowledge.document ADD CONSTRAINT document_document_kind_check CHECK(document_kind IN ('defect','ticket','requirement','article','object','state_machine','state','operation','rule'));
-- sqlite-only
CREATE TABLE "knowledge.document_code" (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
 source_object_type TEXT NOT NULL,
 external_id TEXT NOT NULL,
 external_number TEXT NOT NULL,
 document_kind TEXT NOT NULL CHECK(document_kind IN ('defect','ticket','requirement','article','object','state_machine','state','operation','rule')),
 current_revision_id TEXT,
 lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('pending','active','unavailable','deleted')),
 created_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL,
 source_observed_stamp_raw INTEGER CHECK(source_observed_stamp_raw IS NULL OR source_observed_stamp_raw>0),
 UNIQUE(source_id,source_object_type,external_id),
 UNIQUE(source_id,source_object_type,external_id,id),
 FOREIGN KEY(id,current_revision_id) REFERENCES "knowledge.document_revision"(document_id,id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(lifecycle_state<>'pending' OR current_revision_id IS NULL)
);
-- sqlite-only
INSERT INTO "knowledge.document_code" (id,source_id,source_object_type,external_id,external_number,document_kind,current_revision_id,lifecycle_state,created_at,last_seen_at)
SELECT id,source_id,source_object_type,external_id,external_number,document_kind,current_revision_id,lifecycle_state,created_at,last_seen_at FROM "knowledge.document";
-- sqlite-only
DROP TABLE "knowledge.document";
-- sqlite-only
ALTER TABLE "knowledge.document_code" RENAME TO "knowledge.document";
-- sqlite-only
CREATE INDEX knowledge_document_kind_idx ON "knowledge.document"(source_id,document_kind);
-- postgres-only
CREATE TABLE knowledge.code_binding (
 source_id TEXT PRIMARY KEY REFERENCES knowledge.source(id),
 knowledge_base_id TEXT NOT NULL UNIQUE REFERENCES knowledge.knowledge_base(id),
 config_revision INTEGER NOT NULL CHECK(config_revision>0),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 config_json JSONB NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 demand_enabled INTEGER NOT NULL DEFAULT 0 CHECK(demand_enabled IN (0,1)),
 collected_revision BIGINT CHECK(collected_revision>=0),
 collected_from_revision BIGINT CHECK(collected_from_revision>=0),
 active_snapshot_id TEXT,
 next_run_at TIMESTAMPTZ,
 operations_json JSONB NOT NULL DEFAULT '{}',
 collection_json JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 UNIQUE(source_id,knowledge_base_id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_binding" (
 source_id TEXT PRIMARY KEY REFERENCES "knowledge.source"(id),
 knowledge_base_id TEXT NOT NULL UNIQUE REFERENCES "knowledge.knowledge_base"(id),
 config_revision INTEGER NOT NULL CHECK(config_revision>0),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 config_json TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 demand_enabled INTEGER NOT NULL DEFAULT 0 CHECK(demand_enabled IN (0,1)),
 collected_revision INTEGER CHECK(collected_revision>=0),
 collected_from_revision INTEGER CHECK(collected_from_revision>=0),
 active_snapshot_id TEXT,
 next_run_at TEXT,
 operations_json TEXT NOT NULL DEFAULT '{}',
 collection_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(source_id,knowledge_base_id)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_binding IS '受管代码来源配置及开发快照指针';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.source_id IS '受管代码来源配置及开发快照指针：source_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.knowledge_base_id IS '受管代码来源配置及开发快照指针：knowledge_base_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.config_revision IS '受管代码来源配置及开发快照指针：config_revision';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.config_hash IS '受管代码来源配置及开发快照指针：config_hash';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.config_json IS '受管代码来源配置及开发快照指针：config_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.enabled IS '受管代码来源配置及开发快照指针：enabled';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.demand_enabled IS '受管代码来源配置及开发快照指针：demand_enabled';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.collected_revision IS '受管代码来源配置及开发快照指针：collected_revision';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.collected_from_revision IS '提交账本已核验连续区间的起点；禁止把基线前历史推定为完整';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.active_snapshot_id IS '受管代码来源配置及开发快照指针：active_snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.next_run_at IS '受管代码来源配置及开发快照指针：next_run_at';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.operations_json IS '独立每日计划、冻结提取配置与显式现场版本绑定';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.collection_json IS '固定 SVN 目标、采集恢复检查点与基线映射证明';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.created_at IS '受管代码来源配置及开发快照指针：created_at';
-- postgres-only
COMMENT ON COLUMN knowledge.code_binding.updated_at IS '受管代码来源配置及开发快照指针：updated_at';
-- postgres-only
CREATE TABLE knowledge.code_source_snapshot (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES knowledge.code_binding(source_id),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('local_bundle','svn')),
 svn_revision BIGINT CHECK(svn_revision>=0),
 source_ref JSONB NOT NULL,
 manifest_hash TEXT NOT NULL CHECK(length(manifest_hash)=64),
 manifest_json JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 retired_at TIMESTAMPTZ,
 UNIQUE(id,source_id),
 CHECK((source_kind='local_bundle' AND svn_revision IS NULL) OR (source_kind='svn' AND svn_revision IS NOT NULL))
);
-- sqlite-only
CREATE TABLE "knowledge.code_source_snapshot" (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES "knowledge.code_binding"(source_id),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('local_bundle','svn')),
 svn_revision INTEGER CHECK(svn_revision>=0),
 source_ref TEXT NOT NULL,
 manifest_hash TEXT NOT NULL CHECK(length(manifest_hash)=64),
 manifest_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 retired_at TEXT,
 UNIQUE(id,source_id),
 CHECK((source_kind='local_bundle' AND svn_revision IS NULL) OR (source_kind='svn' AND svn_revision IS NOT NULL))
);
-- postgres-only
COMMENT ON TABLE knowledge.code_source_snapshot IS '不可变来源清单及真实版本身份';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.id IS '不可变来源清单及真实版本身份：id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.source_id IS '不可变来源清单及真实版本身份：source_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.config_hash IS '不可变来源清单及真实版本身份：config_hash';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.source_kind IS '不可变来源清单及真实版本身份：source_kind';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.svn_revision IS '不可变来源清单及真实版本身份：svn_revision';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.source_ref IS '不可变来源清单及真实版本身份：source_ref';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.manifest_hash IS '不可变来源清单及真实版本身份：manifest_hash';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.manifest_json IS '不可变来源清单及真实版本身份：manifest_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.created_at IS '不可变来源清单及真实版本身份：created_at';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_snapshot.retired_at IS '来源字节退役时间；保留知识及清单，显式再导入必须分配新来源快照';
-- postgres-only
CREATE INDEX code_source_manifest_idx ON knowledge.code_source_snapshot(source_id,config_hash,manifest_hash);
-- sqlite-only
CREATE INDEX code_source_manifest_idx ON "knowledge.code_source_snapshot"(source_id,config_hash,manifest_hash);
-- postgres-only
CREATE TABLE knowledge.code_source_file (
 source_snapshot_id TEXT NOT NULL REFERENCES knowledge.code_source_snapshot(id),
 file_id TEXT NOT NULL,
 relative_path TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('backend','factory_frontend','group_frontend')),
 metadata_json JSONB NOT NULL,
 artifact_json JSONB NOT NULL,
 PRIMARY KEY(source_snapshot_id,file_id),
 UNIQUE(source_snapshot_id,relative_path)
);
-- sqlite-only
CREATE TABLE "knowledge.code_source_file" (
 source_snapshot_id TEXT NOT NULL REFERENCES "knowledge.code_source_snapshot"(id),
 file_id TEXT NOT NULL,
 relative_path TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('backend','factory_frontend','group_frontend')),
 metadata_json TEXT NOT NULL,
 artifact_json TEXT NOT NULL,
 PRIMARY KEY(source_snapshot_id,file_id),
 UNIQUE(source_snapshot_id,relative_path)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_source_file IS '来源文件的受管表示位置；不保存源正文';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_file.source_snapshot_id IS '来源文件的受管表示位置；不保存源正文：source_snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_file.file_id IS '来源文件的受管表示位置；不保存源正文：file_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_file.relative_path IS '来源文件的受管表示位置；不保存源正文：relative_path';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_file.role IS '来源文件的受管表示位置；不保存源正文：role';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_file.metadata_json IS '来源文件的受管表示位置；不保存源正文：metadata_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_source_file.artifact_json IS '来源文件的受管表示位置；不保存源正文：artifact_json';
-- postgres-only
CREATE TABLE knowledge.code_commit (
 source_id TEXT NOT NULL REFERENCES knowledge.code_binding(source_id),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 repository_uuid TEXT NOT NULL,
 revision BIGINT NOT NULL CHECK(revision>=0),
 paths_json JSONB NOT NULL,
 complete INTEGER NOT NULL CHECK(complete IN (0,1)),
 analysis_state TEXT NOT NULL CHECK(analysis_state IN ('PENDING','CHECKED','UNAVAILABLE')),
 created_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(source_id,config_hash,revision)
);
-- sqlite-only
CREATE TABLE "knowledge.code_commit" (
 source_id TEXT NOT NULL REFERENCES "knowledge.code_binding"(source_id),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 repository_uuid TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>=0),
 paths_json TEXT NOT NULL,
 complete INTEGER NOT NULL CHECK(complete IN (0,1)),
 analysis_state TEXT NOT NULL CHECK(analysis_state IN ('PENDING','CHECKED','UNAVAILABLE')),
 created_at TEXT NOT NULL,
 PRIMARY KEY(source_id,config_hash,revision)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_commit IS '固定范围提交账本及未完成分析事实';
-- postgres-only
COMMENT ON COLUMN knowledge.code_commit.source_id IS '固定范围提交账本及未完成分析事实：source_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_commit.config_hash IS '固定范围提交账本及未完成分析事实：config_hash';
-- postgres-only
COMMENT ON COLUMN knowledge.code_commit.repository_uuid IS '固定范围提交账本及未完成分析事实：repository_uuid';
-- postgres-only
COMMENT ON COLUMN knowledge.code_commit.revision IS '固定范围提交账本及未完成分析事实：revision';
-- postgres-only
COMMENT ON COLUMN knowledge.code_commit.paths_json IS '固定范围提交账本及未完成分析事实：paths_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_commit.complete IS '固定范围提交账本及未完成分析事实：complete';
-- postgres-only
COMMENT ON COLUMN knowledge.code_commit.analysis_state IS '固定范围提交账本及未完成分析事实：analysis_state';
-- postgres-only
COMMENT ON COLUMN knowledge.code_commit.created_at IS '固定范围提交账本及未完成分析事实：created_at';
-- postgres-only
CREATE TABLE knowledge.code_snapshot (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL,
 knowledge_base_id TEXT NOT NULL,
 source_snapshot_id TEXT NOT NULL,
 processing_hash TEXT NOT NULL CHECK(length(processing_hash)=64),
 state TEXT NOT NULL CHECK(state IN ('CANDIDATE','READY','UNAVAILABLE')),
 index_manifest JSONB NOT NULL,
 validation_json JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 ready_at TIMESTAMPTZ,
 FOREIGN KEY(source_id,knowledge_base_id) REFERENCES knowledge.code_binding(source_id,knowledge_base_id),
 FOREIGN KEY(source_snapshot_id,source_id) REFERENCES knowledge.code_source_snapshot(id,source_id),
 UNIQUE(id,source_id),
 UNIQUE(source_id,source_snapshot_id,processing_hash)
);
-- sqlite-only
CREATE TABLE "knowledge.code_snapshot" (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL,
 knowledge_base_id TEXT NOT NULL,
 source_snapshot_id TEXT NOT NULL,
 processing_hash TEXT NOT NULL CHECK(length(processing_hash)=64),
 state TEXT NOT NULL CHECK(state IN ('CANDIDATE','READY','UNAVAILABLE')),
 index_manifest TEXT NOT NULL,
 validation_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 ready_at TEXT,
 FOREIGN KEY(source_id,knowledge_base_id) REFERENCES "knowledge.code_binding"(source_id,knowledge_base_id),
 FOREIGN KEY(source_snapshot_id,source_id) REFERENCES "knowledge.code_source_snapshot"(id,source_id),
 UNIQUE(id,source_id),
 UNIQUE(source_id,source_snapshot_id,processing_hash)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_snapshot IS '知识成员版本与索引就绪证据';
-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.id IS '知识成员版本与索引就绪证据：id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.source_id IS '知识成员版本与索引就绪证据：source_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.knowledge_base_id IS '知识成员版本与索引就绪证据：knowledge_base_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.source_snapshot_id IS '知识成员版本与索引就绪证据：source_snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.state IS '知识成员版本与索引就绪证据：state';
-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.index_manifest IS '知识成员版本与索引就绪证据：index_manifest';
-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.validation_json IS '知识成员版本与索引就绪证据：validation_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.created_at IS '知识成员版本与索引就绪证据：created_at';
-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.ready_at IS '知识成员版本与索引就绪证据：ready_at';
-- postgres-only
CREATE TABLE knowledge.code_build (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES knowledge.code_binding(source_id),
 source_snapshot_id TEXT NOT NULL,
 snapshot_id TEXT NOT NULL,
 parent_snapshot_id TEXT,
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 configuration_json JSONB NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose IN ('baseline','daily','history','release')),
 stage TEXT NOT NULL CHECK(stage IN ('QUEUED','SOURCE_READY','EXTRACTING','VALIDATING','INDEXING','READY','ACTIVATED','FAILED','INTERRUPTED','CANCELLED')),
 active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
 lease_version INTEGER NOT NULL DEFAULT 0 CHECK(lease_version>=0),
 lease_until TIMESTAMPTZ,
 dedupe_key TEXT NOT NULL UNIQUE,
 error_code TEXT,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 FOREIGN KEY(source_snapshot_id,source_id) REFERENCES knowledge.code_source_snapshot(id,source_id),
 FOREIGN KEY(snapshot_id,source_id) REFERENCES knowledge.code_snapshot(id,source_id),
 FOREIGN KEY(parent_snapshot_id,source_id) REFERENCES knowledge.code_snapshot(id,source_id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_build" (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES "knowledge.code_binding"(source_id),
 source_snapshot_id TEXT NOT NULL,
 snapshot_id TEXT NOT NULL,
 parent_snapshot_id TEXT,
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 configuration_json TEXT NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose IN ('baseline','daily','history','release')),
 stage TEXT NOT NULL CHECK(stage IN ('QUEUED','SOURCE_READY','EXTRACTING','VALIDATING','INDEXING','READY','ACTIVATED','FAILED','INTERRUPTED','CANCELLED')),
 active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
 lease_version INTEGER NOT NULL DEFAULT 0 CHECK(lease_version>=0),
 lease_until TEXT,
 dedupe_key TEXT NOT NULL UNIQUE,
 error_code TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(source_snapshot_id,source_id) REFERENCES "knowledge.code_source_snapshot"(id,source_id),
 FOREIGN KEY(snapshot_id,source_id) REFERENCES "knowledge.code_snapshot"(id,source_id),
 FOREIGN KEY(parent_snapshot_id,source_id) REFERENCES "knowledge.code_snapshot"(id,source_id)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_build IS '固定目标构建及可恢复租约和阶段';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.id IS '固定目标构建及可恢复租约和阶段：id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.source_id IS '固定目标构建及可恢复租约和阶段：source_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.source_snapshot_id IS '固定目标构建及可恢复租约和阶段：source_snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.snapshot_id IS '固定目标构建及可恢复租约和阶段：snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.parent_snapshot_id IS '固定目标构建及可恢复租约和阶段：parent_snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.config_hash IS '固定目标构建及可恢复租约和阶段：config_hash';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.configuration_json IS '固定目标构建及可恢复租约和阶段：configuration_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.purpose IS '固定目标构建及可恢复租约和阶段：purpose';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.stage IS '固定目标构建及可恢复租约和阶段：stage';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.active IS '固定目标构建及可恢复租约和阶段：active';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.lease_version IS '固定目标构建及可恢复租约和阶段：lease_version';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.lease_until IS '固定目标构建及可恢复租约和阶段：lease_until';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.dedupe_key IS '固定目标构建及可恢复租约和阶段：dedupe_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.error_code IS '固定目标构建及可恢复租约和阶段：error_code';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.created_at IS '固定目标构建及可恢复租约和阶段：created_at';
-- postgres-only
COMMENT ON COLUMN knowledge.code_build.updated_at IS '固定目标构建及可恢复租约和阶段：updated_at';
-- postgres-only
CREATE TABLE knowledge.code_unit (
 id TEXT PRIMARY KEY,
 build_id TEXT NOT NULL REFERENCES knowledge.code_build(id),
 unit_key TEXT NOT NULL,
 scope_json JSONB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUBMITTED','VALIDATED','FAILED','UNKNOWN','CANCELLED')),
 job_id TEXT UNIQUE,
 execution_lease_version INTEGER CHECK(execution_lease_version>0),
 artifact_json JSONB,
 result_json JSONB,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 UNIQUE(build_id,unit_key)
);
-- sqlite-only
CREATE TABLE "knowledge.code_unit" (
 id TEXT PRIMARY KEY,
 build_id TEXT NOT NULL REFERENCES "knowledge.code_build"(id),
 unit_key TEXT NOT NULL,
 scope_json TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUBMITTED','VALIDATED','FAILED','UNKNOWN','CANCELLED')),
 job_id TEXT UNIQUE,
 execution_lease_version INTEGER CHECK(execution_lease_version>0),
 artifact_json TEXT,
 result_json TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(build_id,unit_key)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_unit IS '有界提取单元与固定 Job 产物关联';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.id IS '有界提取单元与固定 Job 产物关联：id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.build_id IS '有界提取单元与固定 Job 产物关联：build_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.unit_key IS '有界提取单元与固定 Job 产物关联：unit_key';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.scope_json IS '有界提取单元与固定 Job 产物关联：scope_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.state IS '有界提取单元与固定 Job 产物关联：state';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.job_id IS '有界提取单元与固定 Job 产物关联：job_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.execution_lease_version IS '原提取 Job 的固定租约版本；回收不能用后续租约重写产物身份';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.artifact_json IS '有界提取单元与固定 Job 产物关联：artifact_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.result_json IS '有界提取单元与固定 Job 产物关联：result_json';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.created_at IS '有界提取单元与固定 Job 产物关联：created_at';
-- postgres-only
COMMENT ON COLUMN knowledge.code_unit.updated_at IS '有界提取单元与固定 Job 产物关联：updated_at';
-- postgres-only
CREATE TABLE knowledge.code_member (
 snapshot_id TEXT NOT NULL REFERENCES knowledge.code_snapshot(id),
 document_id TEXT NOT NULL REFERENCES knowledge.document(id),
 revision_id TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,document_id),
 FOREIGN KEY(document_id,revision_id) REFERENCES knowledge.document_revision(document_id,id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_member" (
 snapshot_id TEXT NOT NULL REFERENCES "knowledge.code_snapshot"(id),
 document_id TEXT NOT NULL REFERENCES "knowledge.document"(id),
 revision_id TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,document_id),
 FOREIGN KEY(document_id,revision_id) REFERENCES "knowledge.document_revision"(document_id,id)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_member IS '快照指定的文档修订；历史读取唯一成员事实';
-- postgres-only
COMMENT ON COLUMN knowledge.code_member.snapshot_id IS '快照指定的文档修订；历史读取唯一成员事实：snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_member.document_id IS '快照指定的文档修订；历史读取唯一成员事实：document_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_member.revision_id IS '快照指定的文档修订；历史读取唯一成员事实：revision_id';
-- postgres-only
CREATE TABLE knowledge.code_relation (
 snapshot_id TEXT NOT NULL REFERENCES knowledge.code_snapshot(id),
 relation_id TEXT NOT NULL,
 from_document_id TEXT NOT NULL,
 to_document_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('references','contains','operation_rule','rule_dependency','effect_object')),
 relation_json JSONB NOT NULL,
 PRIMARY KEY(snapshot_id,relation_id),
 FOREIGN KEY(snapshot_id,from_document_id) REFERENCES knowledge.code_member(snapshot_id,document_id),
 FOREIGN KEY(snapshot_id,to_document_id) REFERENCES knowledge.code_member(snapshot_id,document_id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_relation" (
 snapshot_id TEXT NOT NULL REFERENCES "knowledge.code_snapshot"(id),
 relation_id TEXT NOT NULL,
 from_document_id TEXT NOT NULL,
 to_document_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('references','contains','operation_rule','rule_dependency','effect_object')),
 relation_json TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,relation_id),
 FOREIGN KEY(snapshot_id,from_document_id) REFERENCES "knowledge.code_member"(snapshot_id,document_id),
 FOREIGN KEY(snapshot_id,to_document_id) REFERENCES "knowledge.code_member"(snapshot_id,document_id)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_relation IS '同快照业务关系及读取时点';
-- postgres-only
COMMENT ON COLUMN knowledge.code_relation.snapshot_id IS '同快照业务关系及读取时点：snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_relation.relation_id IS '同快照业务关系及读取时点：relation_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_relation.from_document_id IS '同快照业务关系及读取时点：from_document_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_relation.to_document_id IS '同快照业务关系及读取时点：to_document_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_relation.kind IS '同快照业务关系及读取时点：kind';
-- postgres-only
COMMENT ON COLUMN knowledge.code_relation.relation_json IS '同快照业务关系及读取时点：relation_json';
-- postgres-only
CREATE TABLE knowledge.code_dependency (
 revision_id TEXT NOT NULL REFERENCES knowledge.document_revision(id),
 relative_path TEXT NOT NULL,
 symbol TEXT NOT NULL,
 dependency_kind TEXT NOT NULL CHECK(dependency_kind IN ('source','configuration','structure')),
 PRIMARY KEY(revision_id,relative_path,symbol,dependency_kind)
);
-- sqlite-only
CREATE TABLE "knowledge.code_dependency" (
 revision_id TEXT NOT NULL REFERENCES "knowledge.document_revision"(id),
 relative_path TEXT NOT NULL,
 symbol TEXT NOT NULL,
 dependency_kind TEXT NOT NULL CHECK(dependency_kind IN ('source','configuration','structure')),
 PRIMARY KEY(revision_id,relative_path,symbol,dependency_kind)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_dependency IS '修订的源码路径和配置反向依赖';
-- postgres-only
COMMENT ON COLUMN knowledge.code_dependency.revision_id IS '修订的源码路径和配置反向依赖：revision_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_dependency.relative_path IS '修订的源码路径和配置反向依赖：relative_path';
-- postgres-only
COMMENT ON COLUMN knowledge.code_dependency.symbol IS '修订的源码路径和配置反向依赖：symbol';
-- postgres-only
COMMENT ON COLUMN knowledge.code_dependency.dependency_kind IS '修订的源码路径和配置反向依赖：dependency_kind';
-- postgres-only
CREATE TABLE knowledge.code_history_check (
 source_id TEXT NOT NULL REFERENCES knowledge.code_binding(source_id),
 document_id TEXT NOT NULL REFERENCES knowledge.document(id),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 from_revision BIGINT NOT NULL CHECK(from_revision>=0),
 to_revision BIGINT NOT NULL CHECK(to_revision>from_revision),
 from_snapshot_id TEXT NOT NULL,
 to_snapshot_id TEXT NOT NULL,
 ledger_complete INTEGER NOT NULL CHECK(ledger_complete IN (0,1)),
 comparison_json JSONB NOT NULL,
 PRIMARY KEY(source_id,document_id,config_hash,from_revision,to_revision),
 FOREIGN KEY(from_snapshot_id,source_id) REFERENCES knowledge.code_snapshot(id,source_id),
 FOREIGN KEY(to_snapshot_id,source_id) REFERENCES knowledge.code_snapshot(id,source_id)
);
-- sqlite-only
CREATE TABLE "knowledge.code_history_check" (
 source_id TEXT NOT NULL REFERENCES "knowledge.code_binding"(source_id),
 document_id TEXT NOT NULL REFERENCES "knowledge.document"(id),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 from_revision INTEGER NOT NULL CHECK(from_revision>=0),
 to_revision INTEGER NOT NULL CHECK(to_revision>from_revision),
 from_snapshot_id TEXT NOT NULL,
 to_snapshot_id TEXT NOT NULL,
 ledger_complete INTEGER NOT NULL CHECK(ledger_complete IN (0,1)),
 comparison_json TEXT NOT NULL,
 PRIMARY KEY(source_id,document_id,config_hash,from_revision,to_revision),
 FOREIGN KEY(from_snapshot_id,source_id) REFERENCES "knowledge.code_snapshot"(id,source_id),
 FOREIGN KEY(to_snapshot_id,source_id) REFERENCES "knowledge.code_snapshot"(id,source_id)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_history_check IS '精确规则比较及完整提交区间证明';
-- postgres-only
COMMENT ON COLUMN knowledge.code_history_check.source_id IS '精确规则比较及完整提交区间证明：source_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_history_check.document_id IS '精确规则比较及完整提交区间证明：document_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_history_check.config_hash IS '精确规则比较及完整提交区间证明：config_hash';
-- postgres-only
COMMENT ON COLUMN knowledge.code_history_check.from_revision IS '精确规则比较及完整提交区间证明：from_revision';
-- postgres-only
COMMENT ON COLUMN knowledge.code_history_check.to_revision IS '精确规则比较及完整提交区间证明：to_revision';
-- postgres-only
COMMENT ON COLUMN knowledge.code_history_check.from_snapshot_id IS '精确规则比较及完整提交区间证明：from_snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_history_check.to_snapshot_id IS '精确规则比较及完整提交区间证明：to_snapshot_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_history_check.ledger_complete IS '精确规则比较及完整提交区间证明：ledger_complete';
-- postgres-only
COMMENT ON COLUMN knowledge.code_history_check.comparison_json IS '精确规则比较及完整提交区间证明：comparison_json';
-- postgres-only
CREATE TABLE knowledge.code_demand (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES knowledge.code_binding(source_id),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 revision BIGINT NOT NULL CHECK(revision>=0),
 requester_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('PENDING','BUILDING','READY','UNAVAILABLE','CANCELLED')),
 build_id TEXT REFERENCES knowledge.code_build(id),
 created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(source_id,config_hash,revision)
);
-- sqlite-only
CREATE TABLE "knowledge.code_demand" (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES "knowledge.code_binding"(source_id),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 revision INTEGER NOT NULL CHECK(revision>=0),
 requester_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('PENDING','BUILDING','READY','UNAVAILABLE','CANCELLED')),
 build_id TEXT REFERENCES "knowledge.code_build"(id),
 created_at TEXT NOT NULL,
 UNIQUE(source_id,config_hash,revision)
);
-- postgres-only
COMMENT ON TABLE knowledge.code_demand IS '有界历史缓存需求，不授予调用者源码权限';
-- postgres-only
COMMENT ON COLUMN knowledge.code_demand.id IS '有界历史缓存需求，不授予调用者源码权限：id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_demand.source_id IS '有界历史缓存需求，不授予调用者源码权限：source_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_demand.config_hash IS '有界历史缓存需求，不授予调用者源码权限：config_hash';
-- postgres-only
COMMENT ON COLUMN knowledge.code_demand.revision IS '有界历史缓存需求，不授予调用者源码权限：revision';
-- postgres-only
COMMENT ON COLUMN knowledge.code_demand.requester_id IS '有界历史缓存需求，不授予调用者源码权限：requester_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_demand.state IS '有界历史缓存需求，不授予调用者源码权限：state';
-- postgres-only
COMMENT ON COLUMN knowledge.code_demand.build_id IS '有界历史缓存需求，不授予调用者源码权限：build_id';
-- postgres-only
COMMENT ON COLUMN knowledge.code_demand.created_at IS '有界历史缓存需求，不授予调用者源码权限：created_at';
-- postgres-only
CREATE UNIQUE INDEX knowledge_code_build_one_active_idx ON knowledge.code_build(source_id) WHERE active=1;
-- sqlite-only
CREATE UNIQUE INDEX knowledge_code_build_one_active_idx ON "knowledge.code_build"(source_id) WHERE active=1;
-- postgres-only
CREATE INDEX knowledge_code_build_queue_idx ON knowledge.code_build(source_id,stage,created_at);
-- sqlite-only
CREATE INDEX knowledge_code_build_queue_idx ON "knowledge.code_build"(source_id,stage,created_at);
-- postgres-only
CREATE INDEX knowledge_code_source_revision_idx ON knowledge.code_source_snapshot(source_id,svn_revision);
-- sqlite-only
CREATE INDEX knowledge_code_source_revision_idx ON "knowledge.code_source_snapshot"(source_id,svn_revision);
-- postgres-only
CREATE INDEX knowledge_code_relation_target_idx ON knowledge.code_relation(snapshot_id,to_document_id);
-- sqlite-only
CREATE INDEX knowledge_code_relation_target_idx ON "knowledge.code_relation"(snapshot_id,to_document_id);
-- postgres-only
CREATE INDEX knowledge_code_dependency_path_idx ON knowledge.code_dependency(relative_path,revision_id);
-- sqlite-only
CREATE INDEX knowledge_code_dependency_path_idx ON "knowledge.code_dependency"(relative_path,revision_id);
-- postgres-only
CREATE INDEX knowledge_code_unit_job_idx ON knowledge.code_unit(job_id,build_id);
-- sqlite-only
CREATE INDEX knowledge_code_unit_job_idx ON "knowledge.code_unit"(job_id,build_id);
-- postgres-only
CREATE INDEX knowledge_code_demand_queue_idx ON knowledge.code_demand(source_id,state);
-- sqlite-only
CREATE INDEX knowledge_code_demand_queue_idx ON "knowledge.code_demand"(source_id,state);

-- postgres-only
COMMENT ON COLUMN knowledge.code_snapshot.processing_hash IS '提取与索引处理配置摘要；相同来源允许显式的新配置重建';
