-- 候选同步状态；只扩展事实，不导入数据、不发布或启用调度。
-- migration: sqlite-foreign-keys-off
-- postgres-only
ALTER TABLE knowledge.document DROP CONSTRAINT document_lifecycle_state_check;
-- postgres-only
ALTER TABLE knowledge.document ADD CONSTRAINT document_lifecycle_state_check CHECK(lifecycle_state IN ('pending','active','unavailable','deleted'));
-- postgres-only
ALTER TABLE knowledge.document ADD COLUMN source_observed_stamp_raw BIGINT CHECK(source_observed_stamp_raw IS NULL OR source_observed_stamp_raw>0);
-- postgres-only
ALTER TABLE knowledge.document ADD CONSTRAINT knowledge_pending_not_current CHECK(lifecycle_state<>'pending' OR current_revision_id IS NULL);
-- postgres-only
COMMENT ON COLUMN knowledge.document.source_observed_stamp_raw IS '已激活观察水位；仅更新时间变化不创建正文修订，候选阶段不推进';
-- postgres-only
COMMENT ON COLUMN knowledge.document.lifecycle_state IS '文档生命周期；pending 在候选阶段不可检索，不代表采集失败时删除';
-- sqlite-only
CREATE TABLE "knowledge.document_pending" (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
 source_object_type TEXT NOT NULL,
 external_id TEXT NOT NULL,
 external_number TEXT NOT NULL,
 document_kind TEXT NOT NULL CHECK(document_kind IN ('defect','ticket','requirement','article')),
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
INSERT INTO "knowledge.document_pending" (id,source_id,source_object_type,external_id,external_number,document_kind,current_revision_id,lifecycle_state,created_at,last_seen_at)
SELECT id,source_id,source_object_type,external_id,external_number,document_kind,current_revision_id,lifecycle_state,created_at,last_seen_at FROM "knowledge.document";
-- sqlite-only
DROP TABLE "knowledge.document";
-- sqlite-only
ALTER TABLE "knowledge.document_pending" RENAME TO "knowledge.document";
-- sqlite-only
CREATE INDEX knowledge_document_kind_idx ON "knowledge.document"(source_id,document_kind);
-- postgres-only
CREATE TABLE knowledge.sync_binding (
 id TEXT PRIMARY KEY,
 code TEXT NOT NULL UNIQUE,
 source_id TEXT NOT NULL UNIQUE REFERENCES knowledge.source(id),
 configuration_revision INTEGER NOT NULL CHECK(configuration_revision>0),
 configuration_hash TEXT NOT NULL CHECK(length(configuration_hash)=64),
 configuration_json JSONB NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 interval_seconds INTEGER NOT NULL DEFAULT 3600 CHECK(interval_seconds=3600),
 next_run_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL
);
-- postgres-only
CREATE TABLE knowledge.sync_run (
 id TEXT PRIMARY KEY,
 binding_id TEXT NOT NULL REFERENCES knowledge.sync_binding(id),
 source_id TEXT NOT NULL REFERENCES knowledge.source(id),
 binding_revision INTEGER NOT NULL CHECK(binding_revision>0),
 configuration_hash TEXT NOT NULL CHECK(length(configuration_hash)=64),
 input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
 phase TEXT NOT NULL CHECK(phase IN ('COLLECTING','STAGED','CHUNKING','INDEXING','VERIFIED','ACTIVATED','CANCELLED')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 manifest_json JSONB NOT NULL,
 checkpoint_json JSONB NOT NULL,
 resource_baseline_json JSONB NOT NULL,
 activated_watermark TIMESTAMPTZ,
 error_code TEXT,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 UNIQUE(binding_id,binding_revision,input_hash),
 UNIQUE(id,source_id),
 CHECK((phase IN ('ACTIVATED','CANCELLED') AND active=0) OR (phase NOT IN ('ACTIVATED','CANCELLED') AND active=1))
);
-- postgres-only
CREATE UNIQUE INDEX knowledge_sync_active_source_idx ON knowledge.sync_run(source_id) WHERE active=1;
-- postgres-only
CREATE TABLE knowledge.sync_candidate (
 run_id TEXT NOT NULL,
 source_id TEXT NOT NULL,
 external_id TEXT NOT NULL,
 document_id TEXT NOT NULL,
 baseline_revision_id TEXT,
 baseline_kind TEXT NOT NULL CHECK(baseline_kind IN ('defect','ticket','requirement')),
 baseline_members_json JSONB NOT NULL,
 baseline_stamp BIGINT CHECK(baseline_stamp IS NULL OR baseline_stamp>0),
 candidate_revision_id TEXT,
 candidate_kind TEXT NOT NULL CHECK(candidate_kind IN ('defect','ticket','requirement')),
 candidate_members_json JSONB NOT NULL,
 observed_stamp BIGINT CHECK(observed_stamp IS NULL OR observed_stamp>0),
 record_hash TEXT CHECK(record_hash IS NULL OR length(record_hash)=64),
 outcome TEXT NOT NULL CHECK(outcome IN ('baseline','created','revised','unchanged','stale')),
 PRIMARY KEY(run_id,document_id),
 UNIQUE(run_id,source_id,external_id),
 FOREIGN KEY(run_id,source_id) REFERENCES knowledge.sync_run(id,source_id),
 FOREIGN KEY(document_id,baseline_revision_id) REFERENCES knowledge.document_revision(document_id,id),
 FOREIGN KEY(document_id,candidate_revision_id) REFERENCES knowledge.document_revision(document_id,id),
 FOREIGN KEY(document_id) REFERENCES knowledge.document(id),
 CHECK((outcome='baseline' AND record_hash IS NULL) OR (outcome<>'baseline' AND record_hash IS NOT NULL))
);
-- sqlite-only
CREATE TABLE "knowledge.sync_binding" (
 id TEXT PRIMARY KEY,
 code TEXT NOT NULL UNIQUE,
 source_id TEXT NOT NULL UNIQUE REFERENCES "knowledge.source"(id),
 configuration_revision INTEGER NOT NULL CHECK(configuration_revision>0),
 configuration_hash TEXT NOT NULL CHECK(length(configuration_hash)=64),
 configuration_json TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 interval_seconds INTEGER NOT NULL DEFAULT 3600 CHECK(interval_seconds=3600),
 next_run_at TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
-- sqlite-only
CREATE TABLE "knowledge.sync_run" (
 id TEXT PRIMARY KEY,
 binding_id TEXT NOT NULL REFERENCES "knowledge.sync_binding"(id),
 source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
 binding_revision INTEGER NOT NULL CHECK(binding_revision>0),
 configuration_hash TEXT NOT NULL CHECK(length(configuration_hash)=64),
 input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
 phase TEXT NOT NULL CHECK(phase IN ('COLLECTING','STAGED','CHUNKING','INDEXING','VERIFIED','ACTIVATED','CANCELLED')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 manifest_json TEXT NOT NULL,
 checkpoint_json TEXT NOT NULL,
 resource_baseline_json TEXT NOT NULL,
 activated_watermark TEXT,
 error_code TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(binding_id,binding_revision,input_hash),
 UNIQUE(id,source_id),
 CHECK((phase IN ('ACTIVATED','CANCELLED') AND active=0) OR (phase NOT IN ('ACTIVATED','CANCELLED') AND active=1))
);
-- sqlite-only
CREATE UNIQUE INDEX knowledge_sync_active_source_idx ON "knowledge.sync_run"(source_id) WHERE active=1;
-- sqlite-only
CREATE TABLE "knowledge.sync_candidate" (
 run_id TEXT NOT NULL,
 source_id TEXT NOT NULL,
 external_id TEXT NOT NULL,
 document_id TEXT NOT NULL,
 baseline_revision_id TEXT,
 baseline_kind TEXT NOT NULL CHECK(baseline_kind IN ('defect','ticket','requirement')),
 baseline_members_json TEXT NOT NULL,
 baseline_stamp INTEGER CHECK(baseline_stamp IS NULL OR baseline_stamp>0),
 candidate_revision_id TEXT,
 candidate_kind TEXT NOT NULL CHECK(candidate_kind IN ('defect','ticket','requirement')),
 candidate_members_json TEXT NOT NULL,
 observed_stamp INTEGER CHECK(observed_stamp IS NULL OR observed_stamp>0),
 record_hash TEXT CHECK(record_hash IS NULL OR length(record_hash)=64),
 outcome TEXT NOT NULL CHECK(outcome IN ('baseline','created','revised','unchanged','stale')),
 PRIMARY KEY(run_id,document_id),
 UNIQUE(run_id,source_id,external_id),
 FOREIGN KEY(run_id,source_id) REFERENCES "knowledge.sync_run"(id,source_id),
 FOREIGN KEY(document_id,baseline_revision_id) REFERENCES "knowledge.document_revision"(document_id,id),
 FOREIGN KEY(document_id,candidate_revision_id) REFERENCES "knowledge.document_revision"(document_id,id),
 FOREIGN KEY(document_id) REFERENCES "knowledge.document"(id),
 CHECK((outcome='baseline' AND record_hash IS NULL) OR (outcome<>'baseline' AND record_hash IS NOT NULL))
);
-- postgres-only
COMMENT ON TABLE knowledge.sync_binding IS '受管知识同步绑定；默认停用，不授予检索权限';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.id IS '绑定标识';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.code IS '稳定绑定编码';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.source_id IS '固定来源身份';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.configuration_revision IS '配置修订，旧候选不得跨修订激活';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.configuration_hash IS '配置摘要，不含认证材料';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.configuration_json IS '来源范围、知识库映射和资源引用；禁止认证明文';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.enabled IS '显式启用标记，默认停用';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.interval_seconds IS '小时触发间隔';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.next_run_at IS '下次触发时间';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.created_at IS '创建时间';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_binding.updated_at IS '最近配置更新时间';
-- postgres-only
COMMENT ON TABLE knowledge.sync_run IS '同步阶段与恢复事实；失败保留候选，不推进发布水位';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.id IS '运行标识';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.binding_id IS '固定同步绑定';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.source_id IS '来源排他范围';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.binding_revision IS '启动时配置修订';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.configuration_hash IS '启动时配置摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.input_hash IS '冻结输入批次摘要';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.phase IS '最后持久阶段，失败不跳过阶段';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.active IS '有效运行标记，同来源唯一';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.manifest_json IS '输入清单和安全统计；不包含正文或认证值';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.checkpoint_json IS '采集和处理进度检查点';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.resource_baseline_json IS '启动时资源配置和发布指针期望值';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.activated_watermark IS '完整激活后才推进的水位';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.error_code IS '安全失败码';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.created_at IS '创建时间';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_run.updated_at IS '最近检查点时间';
-- postgres-only
COMMENT ON TABLE knowledge.sync_candidate IS '冻结基线加候选覆盖；只保存版本引用，不复制正文';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.run_id IS '候选所属运行';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.source_id IS '固定来源标识';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.external_id IS '来源工作项标识';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.document_id IS '跨知识库稳定文档标识';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.baseline_revision_id IS '激活前期望内容版本';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.baseline_kind IS '激活前期望分类';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.baseline_members_json IS '激活前完整收录期望';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.baseline_stamp IS '激活前观察到的最大来源版本';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.candidate_revision_id IS '构建候选所读取的不可变版本';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.candidate_kind IS '候选分类，不提前改写当前文档';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.candidate_members_json IS '候选收录状态';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.observed_stamp IS '本轮观察来源版本，激活前不更新当前水位';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.record_hash IS '本轮输入内容摘要，支持幂等恢复';
-- postgres-only
COMMENT ON COLUMN knowledge.sync_candidate.outcome IS '候选处理结果；基线不代表已重新采集';
