-- Add the immutable layout OCR v2 profile code without rewriting historical
-- publications, processing runs, picture assets, or object-storage content.
-- migration: sqlite-foreign-keys-off

-- SQLite widens column-level profile checks by replacing only the constrained
-- scalar column. Existing values are copied byte-for-byte.
-- sqlite-only
ALTER TABLE business_application_revision
  RENAME COLUMN document_processing_profile_code TO document_processing_profile_code_v2;
-- sqlite-only
ALTER TABLE business_application_revision
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1', 'docling-layout-ocr-v2'
  ));
-- sqlite-only
UPDATE business_application_revision
   SET document_processing_profile_code = document_processing_profile_code_v2;
-- sqlite-only
ALTER TABLE business_application_revision DROP COLUMN document_processing_profile_code_v2;

-- sqlite-only
ALTER TABLE business_application_publication
  RENAME COLUMN document_processing_profile_code TO document_processing_profile_code_v2;
-- sqlite-only
ALTER TABLE business_application_publication
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1', 'docling-layout-ocr-v2'
  ));
-- sqlite-only
UPDATE business_application_publication
   SET document_processing_profile_code = document_processing_profile_code_v2;
-- sqlite-only
ALTER TABLE business_application_publication DROP COLUMN document_processing_profile_code_v2;

-- sqlite-only
ALTER TABLE agent_job_file_request
  RENAME COLUMN document_processing_profile_code TO document_processing_profile_code_v2;
-- sqlite-only
ALTER TABLE agent_job_file_request
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1', 'docling-layout-ocr-v2'
  ));
-- sqlite-only
UPDATE agent_job_file_request
   SET document_processing_profile_code = document_processing_profile_code_v2;
-- sqlite-only
ALTER TABLE agent_job_file_request DROP COLUMN document_processing_profile_code_v2;

-- sqlite-only
DROP INDEX idx_file_processing_run_layout_stage;
-- sqlite-only
ALTER TABLE file_processing_run RENAME COLUMN profile_code TO profile_code_v2;
-- sqlite-only
ALTER TABLE file_processing_run
  ADD COLUMN profile_code TEXT NOT NULL DEFAULT 'docling-text-v1'
  CHECK (profile_code IN (
    'docling-text-v1', 'docling-layout-ocr-v1', 'docling-layout-ocr-v2'
  ));
-- sqlite-only
UPDATE file_processing_run SET profile_code = profile_code_v2;
-- sqlite-only
ALTER TABLE file_processing_run DROP COLUMN profile_code_v2;
-- sqlite-only
CREATE INDEX idx_file_processing_run_layout_stage
  ON file_processing_run(profile_code, stage_code, assembly_status, updated_at, id);

-- sqlite-only
ALTER TABLE document_picture_asset RENAME COLUMN profile_code TO profile_code_v2;
-- sqlite-only
ALTER TABLE document_picture_asset
  ADD COLUMN profile_code TEXT NOT NULL DEFAULT 'docling-layout-ocr-v1'
  CHECK (profile_code IN ('docling-layout-ocr-v1', 'docling-layout-ocr-v2'));
-- sqlite-only
UPDATE document_picture_asset SET profile_code = profile_code_v2;
-- sqlite-only
ALTER TABLE document_picture_asset DROP COLUMN profile_code_v2;

-- PostgreSQL updates only check constraints and does not touch table rows.
-- postgres-only
ALTER TABLE business_application_revision
  DROP CONSTRAINT business_application_revision_document_processing_profile_code_;
-- postgres-only
ALTER TABLE business_application_revision
  ADD CONSTRAINT business_application_revision_document_profile_code_v3_check
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1', 'docling-layout-ocr-v2'
  ));

-- postgres-only
ALTER TABLE business_application_publication
  DROP CONSTRAINT business_application_publication_document_profile_code_v2_check;
-- postgres-only
ALTER TABLE business_application_publication
  ADD CONSTRAINT business_application_publication_document_profile_code_v3_check
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1', 'docling-layout-ocr-v2'
  ));

-- postgres-only
ALTER TABLE agent_job_file_request
  DROP CONSTRAINT agent_job_file_request_document_profile_code_v2_check;
-- postgres-only
ALTER TABLE agent_job_file_request
  ADD CONSTRAINT agent_job_file_request_document_profile_code_v3_check
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1', 'docling-layout-ocr-v2'
  ));

-- postgres-only
ALTER TABLE file_processing_run
  DROP CONSTRAINT file_processing_run_profile_code_v2_check;
-- postgres-only
ALTER TABLE file_processing_run
  ADD CONSTRAINT file_processing_run_profile_code_v3_check
  CHECK (profile_code IN (
    'docling-text-v1', 'docling-layout-ocr-v1', 'docling-layout-ocr-v2'
  ));

-- postgres-only
ALTER TABLE document_picture_asset
  DROP CONSTRAINT document_picture_asset_profile_code_check;
-- postgres-only
ALTER TABLE document_picture_asset
  ADD CONSTRAINT document_picture_asset_profile_code_v2_check
  CHECK (profile_code IN ('docling-layout-ocr-v1', 'docling-layout-ocr-v2'));

COMMENT ON COLUMN business_application_revision.document_processing_profile_code IS
  '单选NONE、固定文字Profile、历史布局OCR v1或新布局OCR v2代码';
COMMENT ON COLUMN business_application_publication.document_processing_profile_code IS
  'Publication冻结的单一文档处理Profile代码，v1仅历史解释';
COMMENT ON COLUMN agent_job_file_request.document_processing_profile_code IS
  'Job创建时冻结的文档处理Profile代码';
COMMENT ON COLUMN file_processing_run.profile_code IS
  '固定文字或不可变布局OCR Profile代码';
COMMENT ON COLUMN document_picture_asset.profile_code IS
  '固定布局OCR v1或v2 Profile代码';
