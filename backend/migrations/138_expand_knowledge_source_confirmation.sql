-- 来源确认与旧的 ONES 抽样核验分开表达；不自动确认任何历史批次。
-- migration: sqlite-foreign-keys-off

-- postgres-only
ALTER TABLE knowledge.source_binding DROP CONSTRAINT source_binding_state_check;
-- postgres-only
ALTER TABLE knowledge.source_binding ADD CONSTRAINT source_binding_state_check
  CHECK(state IN ('PENDING','CONFIRMED','VERIFIED','REVOKED'));
-- postgres-only
ALTER TABLE knowledge.source_binding ADD CONSTRAINT source_binding_confirmation_check
  CHECK(state<>'CONFIRMED' OR verification_hash IS NULL);
-- postgres-only
DROP INDEX knowledge.knowledge_source_verified_idx;
-- postgres-only
CREATE UNIQUE INDEX knowledge_source_verified_idx ON knowledge.source_binding(source_id)
  WHERE state IN ('CONFIRMED','VERIFIED');
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.state IS '待确认、导入来源已确认、历史技术核验通过或已撤销；均不授予业务读取权';
-- postgres-only
COMMENT ON COLUMN knowledge.source_binding.attestation_hash IS '导入侧明确来源确认记录的系统摘要；历史记录保留原摘要，不代表 ONES 权限证明';

-- sqlite-only
CREATE TABLE "knowledge.source_binding_confirmed" (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES "knowledge.source"(id),
    revision INTEGER NOT NULL CHECK(revision>0),
    instance_code TEXT NOT NULL CHECK(length(instance_code) BETWEEN 1 AND 128),
    target_hash TEXT NOT NULL CHECK(length(target_hash)=64),
    team_id TEXT NOT NULL CHECK(length(team_id) BETWEEN 1 AND 128),
    state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','CONFIRMED','VERIFIED','REVOKED')),
    attestation_hash TEXT NOT NULL CHECK(length(attestation_hash)=64),
    corpus_hash TEXT NOT NULL CHECK(length(corpus_hash)=64),
    document_count INTEGER NOT NULL CHECK(document_count>0),
    verification_hash TEXT CHECK(verification_hash IS NULL OR length(verification_hash)=64),
    checked_count INTEGER NOT NULL DEFAULT 0 CHECK(checked_count>=0 AND checked_count<=document_count),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    verified_by TEXT,
    verified_job_id TEXT,
    verified_at TEXT,
    revoked_by TEXT,
    revoked_at TEXT,
    UNIQUE(source_id,revision),
    CHECK((verification_hash IS NULL AND checked_count=0 AND verified_at IS NULL AND verified_by IS NULL AND verified_job_id IS NULL) OR (verification_hash IS NOT NULL AND checked_count>0 AND verified_at IS NOT NULL AND verified_by IS NOT NULL AND verified_job_id IS NOT NULL)),
    CHECK(state<>'VERIFIED' OR verification_hash IS NOT NULL),
    CHECK(state<>'CONFIRMED' OR verification_hash IS NULL),
    CHECK((state='REVOKED' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL) OR (state<>'REVOKED' AND revoked_at IS NULL AND revoked_by IS NULL))
);
-- sqlite-only
INSERT INTO "knowledge.source_binding_confirmed"
  (id,source_id,revision,instance_code,target_hash,team_id,state,attestation_hash,corpus_hash,document_count,verification_hash,checked_count,created_by,created_at,verified_by,verified_job_id,verified_at,revoked_by,revoked_at)
SELECT id,source_id,revision,instance_code,target_hash,team_id,state,attestation_hash,corpus_hash,document_count,verification_hash,checked_count,created_by,created_at,verified_by,verified_job_id,verified_at,revoked_by,revoked_at
FROM "knowledge.source_binding";
-- sqlite-only
DROP TABLE "knowledge.source_binding";
-- sqlite-only
ALTER TABLE "knowledge.source_binding_confirmed" RENAME TO "knowledge.source_binding";
-- sqlite-only
CREATE UNIQUE INDEX knowledge_source_verified_idx ON "knowledge.source_binding"(source_id)
  WHERE state IN ('CONFIRMED','VERIFIED');
