-- Contract the open-test file domain to the only executable contract:
-- fixed direct-text rules, docling-layout-ocr-v2, Manifest v5, Python Runtime
-- protocol 1.3. This migration never rewrites an old immutable fact into a
-- current fact. Operators must run the guarded open-test reset first.
-- migration: sqlite-foreign-keys-off

CREATE TABLE migration_119_single_rule_guard (
  violation INTEGER NOT NULL CHECK (violation = 0)
);

INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (SELECT 1 FROM managed_file);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (SELECT 1 FROM task_workspace);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (SELECT 1 FROM agent_job_file_snapshot);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (SELECT 1 FROM file_processing_run);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (SELECT 1 FROM attachment_content);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (
  SELECT 1 FROM agent_definition WHERE runtime_kind <> 'python-v1'
);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (
  SELECT 1 FROM agent_publication WHERE runtime_kind <> 'python-v1'
);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (
  SELECT 1 FROM agent_job
   WHERE agent_runtime_kind <> 'python-v1'
      OR agent_runtime_protocol_version <> '1.3'
);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (
  SELECT 1 FROM agent_job_execution_summary
   WHERE source_protocol_version <> '1.3'
);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (
  SELECT 1 FROM business_application_revision
   WHERE document_processing_profile_code NOT IN ('NONE', 'docling-layout-ocr-v2')
);
INSERT INTO migration_119_single_rule_guard
SELECT 1 WHERE EXISTS (
  SELECT 1 FROM business_application_publication
   WHERE schema_version <> 6
      OR document_processing_profile_code NOT IN ('NONE', 'docling-layout-ocr-v2')
);

DROP TABLE migration_119_single_rule_guard;

DROP TABLE attachment_content;
DROP INDEX idx_message_attachment_managed_version;
ALTER TABLE message_attachment DROP COLUMN managed_file_id;
ALTER TABLE message_attachment DROP COLUMN managed_file_version_id;

ALTER TABLE business_application_revision DROP COLUMN file_format_policy_version;
ALTER TABLE business_application_publication DROP COLUMN file_format_policy_version;
ALTER TABLE agent_job_file_request DROP COLUMN file_format_policy_version;
ALTER TABLE agent_job_file_snapshot DROP COLUMN file_format_policy_version;
ALTER TABLE file_commit_intent DROP COLUMN file_format_policy_version;

-- SQLite replaces the constrained scalar columns without accepting an old
-- code. The preflight above guarantees every copied value is already current.
-- sqlite-only
ALTER TABLE business_application_revision
  RENAME COLUMN document_processing_profile_code TO document_processing_profile_code_old;
-- sqlite-only
ALTER TABLE business_application_revision
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN ('NONE', 'docling-layout-ocr-v2'));
-- sqlite-only
UPDATE business_application_revision
   SET document_processing_profile_code = document_processing_profile_code_old;
-- sqlite-only
ALTER TABLE business_application_revision DROP COLUMN document_processing_profile_code_old;

-- sqlite-only
ALTER TABLE business_application_publication
  RENAME COLUMN document_processing_profile_code TO document_processing_profile_code_old;
-- sqlite-only
ALTER TABLE business_application_publication
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN ('NONE', 'docling-layout-ocr-v2'));
-- sqlite-only
UPDATE business_application_publication
   SET document_processing_profile_code = document_processing_profile_code_old;
-- sqlite-only
ALTER TABLE business_application_publication DROP COLUMN document_processing_profile_code_old;

-- sqlite-only
ALTER TABLE agent_job_file_request
  RENAME COLUMN document_processing_profile_code TO document_processing_profile_code_old;
-- sqlite-only
ALTER TABLE agent_job_file_request
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN ('NONE', 'docling-layout-ocr-v2'));
-- sqlite-only
UPDATE agent_job_file_request
   SET document_processing_profile_code = document_processing_profile_code_old;
-- sqlite-only
ALTER TABLE agent_job_file_request DROP COLUMN document_processing_profile_code_old;

-- sqlite-only
DROP INDEX idx_file_processing_run_layout_stage;
-- sqlite-only
ALTER TABLE file_processing_run RENAME COLUMN profile_code TO profile_code_old;
-- sqlite-only
ALTER TABLE file_processing_run
  ADD COLUMN profile_code TEXT NOT NULL DEFAULT 'docling-layout-ocr-v2'
  CHECK (profile_code = 'docling-layout-ocr-v2');
-- sqlite-only
UPDATE file_processing_run SET profile_code = profile_code_old;
-- sqlite-only
ALTER TABLE file_processing_run DROP COLUMN profile_code_old;
-- sqlite-only
CREATE INDEX idx_file_processing_run_layout_stage
  ON file_processing_run(profile_code, stage_code, assembly_status, updated_at, id);

-- sqlite-only
ALTER TABLE document_picture_asset RENAME COLUMN profile_code TO profile_code_old;
-- sqlite-only
ALTER TABLE document_picture_asset
  ADD COLUMN profile_code TEXT NOT NULL DEFAULT 'docling-layout-ocr-v2'
  CHECK (profile_code = 'docling-layout-ocr-v2');
-- sqlite-only
UPDATE document_picture_asset SET profile_code = profile_code_old;
-- sqlite-only
ALTER TABLE document_picture_asset DROP COLUMN profile_code_old;

-- sqlite-only
ALTER TABLE agent_job_file_snapshot RENAME COLUMN schema_version TO schema_version_old;
-- sqlite-only
ALTER TABLE agent_job_file_snapshot
  ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 5 CHECK (schema_version = 5);
-- sqlite-only
UPDATE agent_job_file_snapshot SET schema_version = schema_version_old;
-- sqlite-only
ALTER TABLE agent_job_file_snapshot DROP COLUMN schema_version_old;

-- sqlite-only
ALTER TABLE agent_job RENAME COLUMN agent_runtime_kind TO agent_runtime_kind_old;
-- sqlite-only
ALTER TABLE agent_job
  ADD COLUMN agent_runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
  CHECK (agent_runtime_kind = 'python-v1');
-- sqlite-only
UPDATE agent_job SET agent_runtime_kind = agent_runtime_kind_old;
-- sqlite-only
ALTER TABLE agent_job DROP COLUMN agent_runtime_kind_old;

-- sqlite-only
DROP INDEX idx_agent_definition_runtime_kind;
-- sqlite-only
ALTER TABLE agent_definition RENAME COLUMN runtime_kind TO runtime_kind_old;
-- sqlite-only
ALTER TABLE agent_definition
  ADD COLUMN runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
  CHECK (runtime_kind = 'python-v1');
-- sqlite-only
UPDATE agent_definition SET runtime_kind = runtime_kind_old;
-- sqlite-only
ALTER TABLE agent_definition DROP COLUMN runtime_kind_old;
-- sqlite-only
CREATE INDEX idx_agent_definition_runtime_kind ON agent_definition(runtime_kind);

-- sqlite-only
DROP INDEX idx_agent_publication_runtime_kind;
-- sqlite-only
ALTER TABLE agent_publication RENAME COLUMN runtime_kind TO runtime_kind_old;
-- sqlite-only
ALTER TABLE agent_publication
  ADD COLUMN runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
  CHECK (runtime_kind = 'python-v1');
-- sqlite-only
UPDATE agent_publication SET runtime_kind = runtime_kind_old;
-- sqlite-only
ALTER TABLE agent_publication DROP COLUMN runtime_kind_old;
-- sqlite-only
CREATE INDEX idx_agent_publication_runtime_kind ON agent_publication(runtime_kind);

-- sqlite-only
ALTER TABLE agent_job
  RENAME COLUMN agent_runtime_protocol_version TO agent_runtime_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job
  ADD COLUMN agent_runtime_protocol_version TEXT NOT NULL DEFAULT '1.3'
  CHECK (agent_runtime_protocol_version = '1.3');
-- sqlite-only
UPDATE agent_job
   SET agent_runtime_protocol_version = agent_runtime_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job DROP COLUMN agent_runtime_protocol_version_old;

-- sqlite-only
ALTER TABLE agent_job_execution_summary
  RENAME COLUMN source_protocol_version TO source_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job_execution_summary
  ADD COLUMN source_protocol_version TEXT NOT NULL DEFAULT '1.3'
  CHECK (source_protocol_version = '1.3');
-- sqlite-only
UPDATE agent_job_execution_summary
   SET source_protocol_version = source_protocol_version_old;
-- sqlite-only
ALTER TABLE agent_job_execution_summary DROP COLUMN source_protocol_version_old;

-- PostgreSQL contracts the existing named constraints in place.
-- postgres-only
ALTER TABLE business_application_revision
  DROP CONSTRAINT business_application_revision_document_profile_code_v3_check;
-- postgres-only
ALTER TABLE business_application_revision
  ADD CONSTRAINT business_application_revision_document_profile_code_check
  CHECK (document_processing_profile_code IN ('NONE', 'docling-layout-ocr-v2'));

-- postgres-only
ALTER TABLE business_application_publication
  DROP CONSTRAINT business_application_publication_document_profile_code_v3_check;
-- postgres-only
ALTER TABLE business_application_publication
  ADD CONSTRAINT business_application_publication_document_profile_code_check
  CHECK (document_processing_profile_code IN ('NONE', 'docling-layout-ocr-v2'));

-- postgres-only
ALTER TABLE agent_job_file_request
  DROP CONSTRAINT agent_job_file_request_document_profile_code_v3_check;
-- postgres-only
ALTER TABLE agent_job_file_request
  ADD CONSTRAINT agent_job_file_request_document_profile_code_check
  CHECK (document_processing_profile_code IN ('NONE', 'docling-layout-ocr-v2'));

-- postgres-only
ALTER TABLE file_processing_run
  DROP CONSTRAINT file_processing_run_profile_code_v3_check;
-- postgres-only
ALTER TABLE file_processing_run ALTER COLUMN profile_code SET DEFAULT 'docling-layout-ocr-v2';
-- postgres-only
ALTER TABLE file_processing_run
  ADD CONSTRAINT file_processing_run_profile_code_check
  CHECK (profile_code = 'docling-layout-ocr-v2');

-- postgres-only
ALTER TABLE document_picture_asset
  DROP CONSTRAINT document_picture_asset_profile_code_v2_check;
-- postgres-only
ALTER TABLE document_picture_asset ALTER COLUMN profile_code SET DEFAULT 'docling-layout-ocr-v2';
-- postgres-only
ALTER TABLE document_picture_asset
  ADD CONSTRAINT document_picture_asset_profile_code_check
  CHECK (profile_code = 'docling-layout-ocr-v2');

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  DROP CONSTRAINT agent_job_file_snapshot_schema_version_check;
-- postgres-only
ALTER TABLE agent_job_file_snapshot ALTER COLUMN schema_version SET DEFAULT 5;
-- postgres-only
ALTER TABLE agent_job_file_snapshot
  ADD CONSTRAINT agent_job_file_snapshot_schema_version_check
  CHECK (schema_version = 5);

-- postgres-only
ALTER TABLE agent_job DROP CONSTRAINT agent_job_agent_runtime_kind_check;
-- postgres-only
ALTER TABLE agent_job ALTER COLUMN agent_runtime_kind SET DEFAULT 'python-v1';
-- postgres-only
ALTER TABLE agent_job
  ADD CONSTRAINT agent_job_agent_runtime_kind_check
  CHECK (agent_runtime_kind = 'python-v1');

-- postgres-only
ALTER TABLE agent_definition DROP CONSTRAINT agent_definition_runtime_kind_check;
-- postgres-only
ALTER TABLE agent_definition ALTER COLUMN runtime_kind SET DEFAULT 'python-v1';
-- postgres-only
ALTER TABLE agent_definition
  ADD CONSTRAINT agent_definition_runtime_kind_check
  CHECK (runtime_kind = 'python-v1');

-- postgres-only
ALTER TABLE agent_publication DROP CONSTRAINT agent_publication_runtime_kind_check;
-- postgres-only
ALTER TABLE agent_publication ALTER COLUMN runtime_kind SET DEFAULT 'python-v1';
-- postgres-only
ALTER TABLE agent_publication
  ADD CONSTRAINT agent_publication_runtime_kind_check
  CHECK (runtime_kind = 'python-v1');

-- postgres-only
ALTER TABLE agent_job DROP CONSTRAINT agent_job_agent_runtime_protocol_version_check;
-- postgres-only
ALTER TABLE agent_job ALTER COLUMN agent_runtime_protocol_version SET DEFAULT '1.3';
-- postgres-only
ALTER TABLE agent_job
  ADD CONSTRAINT agent_job_agent_runtime_protocol_version_check
  CHECK (agent_runtime_protocol_version = '1.3');

-- postgres-only
ALTER TABLE agent_job_execution_summary
  DROP CONSTRAINT agent_job_execution_summary_source_protocol_version_check;
-- postgres-only
ALTER TABLE agent_job_execution_summary
  ADD CONSTRAINT agent_job_execution_summary_source_protocol_version_check
  CHECK (source_protocol_version = '1.3');

COMMENT ON COLUMN business_application_revision.document_processing_profile_code IS
  'Application草稿只允许NONE或当前docling-layout-ocr-v2 Profile';
COMMENT ON COLUMN business_application_publication.document_processing_profile_code IS
  'Publication冻结NONE或当前docling-layout-ocr-v2 Profile';
COMMENT ON COLUMN agent_job_file_request.document_processing_profile_code IS
  'Job只冻结NONE或当前docling-layout-ocr-v2 Profile';
COMMENT ON COLUMN file_processing_run.profile_code IS
  '文件处理运行固定使用docling-layout-ocr-v2';
COMMENT ON COLUMN document_picture_asset.profile_code IS
  'Office内嵌图片资产固定使用docling-layout-ocr-v2';
COMMENT ON COLUMN agent_job_file_snapshot.schema_version IS
  'Job文件清单固定为schema v5';
COMMENT ON COLUMN agent_job.agent_runtime_kind IS
  'Agent Job固定使用python-v1 Runtime';
COMMENT ON COLUMN agent_definition.runtime_kind IS
  'Agent定义固定使用python-v1 Runtime';
COMMENT ON COLUMN agent_publication.runtime_kind IS
  'Agent发布版本固定使用python-v1 Runtime';
COMMENT ON COLUMN agent_job.agent_runtime_protocol_version IS
  'Agent Job固定使用Runtime protocol 1.3';
COMMENT ON COLUMN agent_job_execution_summary.source_protocol_version IS
  '执行摘要只接受Runtime protocol 1.3';
