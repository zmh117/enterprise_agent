-- Expand governed Office embedded-image layout OCR facts. This migration only
-- changes relational identities and constraints. It never reads, creates, or
-- deletes object-storage content and never writes OCR text or coordinates.
-- migration: sqlite-foreign-keys-off

-- SQLite widens column-level profile checks without rebuilding large domain tables.
-- sqlite-only
ALTER TABLE business_application_revision
  RENAME COLUMN document_processing_profile_code TO document_processing_profile_code_v1;
-- sqlite-only
ALTER TABLE business_application_revision
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1'
  ));
-- sqlite-only
UPDATE business_application_revision
   SET document_processing_profile_code = document_processing_profile_code_v1;
-- sqlite-only
ALTER TABLE business_application_revision DROP COLUMN document_processing_profile_code_v1;

-- sqlite-only
ALTER TABLE business_application_publication
  RENAME COLUMN document_processing_profile_code TO document_processing_profile_code_v1;
-- sqlite-only
ALTER TABLE business_application_publication
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1'
  ));
-- sqlite-only
UPDATE business_application_publication
   SET document_processing_profile_code = document_processing_profile_code_v1;
-- sqlite-only
ALTER TABLE business_application_publication DROP COLUMN document_processing_profile_code_v1;

-- sqlite-only
ALTER TABLE agent_job_file_request
  RENAME COLUMN document_processing_profile_code TO document_processing_profile_code_v1;
-- sqlite-only
ALTER TABLE agent_job_file_request
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1'
  ));
-- sqlite-only
UPDATE agent_job_file_request
   SET document_processing_profile_code = document_processing_profile_code_v1;
-- sqlite-only
ALTER TABLE agent_job_file_request DROP COLUMN document_processing_profile_code_v1;

-- sqlite-only
ALTER TABLE file_processing_run RENAME COLUMN profile_code TO profile_code_v1;
-- sqlite-only
ALTER TABLE file_processing_run
  ADD COLUMN profile_code TEXT NOT NULL DEFAULT 'docling-text-v1'
  CHECK (profile_code IN ('docling-text-v1', 'docling-layout-ocr-v1'));
-- sqlite-only
UPDATE file_processing_run SET profile_code = profile_code_v1;
-- sqlite-only
ALTER TABLE file_processing_run DROP COLUMN profile_code_v1;

-- postgres-only
ALTER TABLE business_application_revision
  DROP CONSTRAINT business_application_revisio_document_processing_profile__check;
-- postgres-only
ALTER TABLE business_application_revision
  ADD CONSTRAINT business_application_revision_document_processing_profile_code_v2_check
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1'
  ));

-- postgres-only
ALTER TABLE business_application_publication
  DROP CONSTRAINT business_application_publica_document_processing_profile__check;
-- postgres-only
ALTER TABLE business_application_publication
  ADD CONSTRAINT business_application_publication_document_profile_code_v2_check
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1'
  ));

-- postgres-only
ALTER TABLE agent_job_file_request
  DROP CONSTRAINT agent_job_file_request_document_processing_profile_code_check;
-- postgres-only
ALTER TABLE agent_job_file_request
  ADD CONSTRAINT agent_job_file_request_document_profile_code_v2_check
  CHECK (document_processing_profile_code IN (
    'NONE', 'docling-text-v1', 'docling-layout-ocr-v1'
  ));

-- postgres-only
ALTER TABLE file_processing_run DROP CONSTRAINT file_processing_run_profile_code_check;
-- postgres-only
ALTER TABLE file_processing_run
  ADD CONSTRAINT file_processing_run_profile_code_v2_check
  CHECK (profile_code IN ('docling-text-v1', 'docling-layout-ocr-v1'));

ALTER TABLE file_processing_run
  ADD COLUMN stage_code TEXT NOT NULL DEFAULT 'PARENT_PARSE'
  CHECK (stage_code IN ('PARENT_PARSE', 'PICTURE_OCR', 'ASSEMBLING'));

ALTER TABLE file_processing_run
  ADD COLUMN required_output_kinds_json TEXT NOT NULL
  DEFAULT '["MARKDOWN","DOCLING_JSON"]'
  CHECK (length(required_output_kinds_json) BETWEEN 1 AND 256);

ALTER TABLE file_processing_run ADD COLUMN run_deadline_at TEXT;

ALTER TABLE file_processing_run
  ADD COLUMN assembly_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED'
  CHECK (assembly_status IN (
    'NOT_REQUIRED', 'PENDING', 'CLAIMED', 'COMPLETED', 'FAILED'
  ));

ALTER TABLE file_processing_run
  ADD COLUMN assembly_attempt INTEGER NOT NULL DEFAULT 0 CHECK (assembly_attempt >= 0);

ALTER TABLE file_processing_run
  ADD COLUMN assembly_claim_token TEXT NOT NULL DEFAULT ''
  CHECK (length(assembly_claim_token) <= 128);

ALTER TABLE file_processing_run ADD COLUMN assembly_claimed_at TEXT;

-- SQLite replaces representation tables to widen their kind checks.
-- sqlite-only
CREATE TABLE file_representation_layout_ocr (
  id TEXT PRIMARY KEY,
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  tenant_id TEXT NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 128),
  source_file_id TEXT NOT NULL REFERENCES managed_file(id),
  source_version_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN (
    'MARKDOWN', 'DOCLING_JSON', 'OCR_LAYOUT_JSON'
  )),
  media_type TEXT NOT NULL,
  encoding TEXT NOT NULL CHECK (encoding = 'utf-8'),
  status TEXT NOT NULL DEFAULT 'AVAILABLE'
    CHECK (status IN ('AVAILABLE', 'CONTENT_UNAVAILABLE', 'DELETED')),
  size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  object_key TEXT NOT NULL UNIQUE CHECK (length(object_key) BETWEEN 1 AND 1024),
  profile_hash TEXT NOT NULL CHECK (length(profile_hash) = 64),
  created_at TEXT NOT NULL,
  content_deleted_at TEXT,
  FOREIGN KEY (
    processing_run_id, tenant_id, source_file_id, source_version_id
  ) REFERENCES file_processing_run(
    id, tenant_id, source_file_id, source_version_id
  ),
  CHECK (
    (kind = 'MARKDOWN' AND media_type = 'text/markdown')
    OR (kind IN ('DOCLING_JSON', 'OCR_LAYOUT_JSON') AND media_type = 'application/json')
  ),
  CHECK (
    (status IN ('CONTENT_UNAVAILABLE', 'DELETED') AND content_deleted_at IS NOT NULL)
    OR status = 'AVAILABLE'
  )
);

-- sqlite-only
INSERT INTO file_representation_layout_ocr
  (id, processing_run_id, tenant_id, source_file_id, source_version_id,
   kind, media_type, encoding, status, size_bytes, content_sha256, object_key,
   profile_hash, created_at, content_deleted_at)
SELECT id, processing_run_id, tenant_id, source_file_id, source_version_id,
       kind, media_type, encoding, status, size_bytes, content_sha256, object_key,
       profile_hash, created_at, content_deleted_at
  FROM file_representation;

-- sqlite-only
DROP TABLE file_representation;
-- sqlite-only
ALTER TABLE file_representation_layout_ocr RENAME TO file_representation;
-- sqlite-only
CREATE UNIQUE INDEX uq_file_representation_run_kind
  ON file_representation(processing_run_id, kind);
-- sqlite-only
CREATE INDEX idx_file_representation_source
  ON file_representation(
    tenant_id, source_file_id, source_version_id, kind, status
  );
-- sqlite-only
CREATE INDEX idx_file_representation_cleanup
  ON file_representation(status, content_deleted_at, created_at, id);

-- sqlite-only
CREATE TABLE file_representation_transfer_layout_ocr (
  id TEXT PRIMARY KEY,
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  kind TEXT NOT NULL CHECK (kind IN (
    'MARKDOWN', 'DOCLING_JSON', 'OCR_LAYOUT_JSON'
  )),
  token_hash TEXT NOT NULL CHECK (length(token_hash) = 64),
  expected_size_bytes BIGINT CHECK (
    expected_size_bytes IS NULL OR expected_size_bytes >= 0
  ),
  expected_sha256 TEXT NOT NULL DEFAULT ''
    CHECK (length(expected_sha256) IN (0, 64)),
  received_size_bytes BIGINT NOT NULL DEFAULT 0 CHECK (received_size_bytes >= 0),
  received_sha256 TEXT NOT NULL DEFAULT ''
    CHECK (length(received_sha256) IN (0, 64)),
  staging_object_key TEXT NOT NULL UNIQUE
    CHECK (length(staging_object_key) BETWEEN 1 AND 1024),
  status TEXT NOT NULL DEFAULT 'OPEN'
    CHECK (status IN (
      'OPEN', 'UPLOADING', 'STAGED', 'FINALIZED', 'EXPIRED', 'FAILED'
    )),
  error_code TEXT NOT NULL DEFAULT '' CHECK (length(error_code) <= 128),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finalized_at TEXT,
  UNIQUE(processing_run_id, kind),
  CHECK (
    (status = 'FINALIZED' AND finalized_at IS NOT NULL)
    OR status <> 'FINALIZED'
  )
);

-- sqlite-only
INSERT INTO file_representation_transfer_layout_ocr
  (id, processing_run_id, kind, token_hash, expected_size_bytes,
   expected_sha256, received_size_bytes, received_sha256, staging_object_key,
   status, error_code, expires_at, created_at, updated_at, finalized_at)
SELECT id, processing_run_id, kind, token_hash, expected_size_bytes,
       expected_sha256, received_size_bytes, received_sha256, staging_object_key,
       status, error_code, expires_at, created_at, updated_at, finalized_at
  FROM file_representation_transfer;

-- sqlite-only
DROP TABLE file_representation_transfer;
-- sqlite-only
ALTER TABLE file_representation_transfer_layout_ocr
  RENAME TO file_representation_transfer;
-- sqlite-only
CREATE INDEX idx_file_representation_transfer_expiry
  ON file_representation_transfer(status, expires_at, id);

-- postgres-only
ALTER TABLE file_representation DROP CONSTRAINT file_representation_kind_check;
-- postgres-only
ALTER TABLE file_representation DROP CONSTRAINT file_representation_check;
-- postgres-only
ALTER TABLE file_representation
  ADD CONSTRAINT file_representation_kind_v2_check
  CHECK (kind IN ('MARKDOWN', 'DOCLING_JSON', 'OCR_LAYOUT_JSON'));
-- postgres-only
ALTER TABLE file_representation
  ADD CONSTRAINT file_representation_media_kind_v2_check
  CHECK (
    (kind = 'MARKDOWN' AND media_type = 'text/markdown')
    OR (kind IN ('DOCLING_JSON', 'OCR_LAYOUT_JSON') AND media_type = 'application/json')
  );

-- postgres-only
ALTER TABLE file_representation_transfer
  DROP CONSTRAINT file_representation_transfer_kind_check;
-- postgres-only
ALTER TABLE file_representation_transfer
  ADD CONSTRAINT file_representation_transfer_kind_v2_check
  CHECK (kind IN ('MARKDOWN', 'DOCLING_JSON', 'OCR_LAYOUT_JSON'));

CREATE TABLE document_parent_artifact_transfer (
  id TEXT PRIMARY KEY,
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  kind TEXT NOT NULL CHECK (kind = 'PARENT_MARKDOWN'),
  token_hash TEXT NOT NULL CHECK (length(token_hash) = 64),
  expected_size_bytes BIGINT NOT NULL CHECK (expected_size_bytes > 0),
  expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
  received_size_bytes BIGINT NOT NULL DEFAULT 0 CHECK (received_size_bytes >= 0),
  received_sha256 TEXT NOT NULL DEFAULT '' CHECK (length(received_sha256) IN (0, 64)),
  staging_object_key TEXT NOT NULL UNIQUE CHECK (length(staging_object_key) BETWEEN 1 AND 1024),
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN (
    'OPEN', 'UPLOADING', 'FINALIZED', 'EXPIRED', 'FAILED', 'CONTENT_UNAVAILABLE'
  )),
  error_code TEXT NOT NULL DEFAULT '' CHECK (length(error_code) <= 128),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finalized_at TEXT,
  content_deleted_at TEXT,
  UNIQUE(processing_run_id, kind),
  CHECK (
    (status = 'FINALIZED' AND finalized_at IS NOT NULL)
    OR status <> 'FINALIZED'
  )
);

CREATE INDEX idx_document_parent_artifact_transfer_expiry
  ON document_parent_artifact_transfer(status, expires_at, id);

CREATE TABLE document_picture_asset (
  id TEXT PRIMARY KEY,
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  tenant_id TEXT NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 128),
  source_file_id TEXT NOT NULL REFERENCES managed_file(id),
  source_version_id TEXT NOT NULL,
  profile_code TEXT NOT NULL CHECK (profile_code = 'docling-layout-ocr-v1'),
  profile_hash TEXT NOT NULL CHECK (length(profile_hash) = 64),
  normalized_sha256 TEXT NOT NULL CHECK (length(normalized_sha256) = 64),
  media_type TEXT NOT NULL CHECK (media_type IN (
    'image/png', 'image/jpeg', 'image/webp'
  )),
  original_width_pixels INTEGER NOT NULL CHECK (original_width_pixels > 0),
  original_height_pixels INTEGER NOT NULL CHECK (original_height_pixels > 0),
  width_pixels INTEGER NOT NULL CHECK (width_pixels > 0),
  height_pixels INTEGER NOT NULL CHECK (height_pixels > 0),
  normalization_transform_json TEXT NOT NULL
    CHECK (length(normalization_transform_json) BETWEEN 2 AND 1024),
  size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
  object_key TEXT NOT NULL UNIQUE CHECK (length(object_key) BETWEEN 1 AND 1024),
  status TEXT NOT NULL DEFAULT 'STAGING'
    CHECK (status IN ('STAGING', 'AVAILABLE', 'CONTENT_UNAVAILABLE', 'DELETED')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  content_deleted_at TEXT,
  cleanup_error_code TEXT NOT NULL DEFAULT '' CHECK (length(cleanup_error_code) <= 128),
  FOREIGN KEY (
    processing_run_id, tenant_id, source_file_id, source_version_id
  ) REFERENCES file_processing_run(
    id, tenant_id, source_file_id, source_version_id
  ),
  UNIQUE(processing_run_id, normalized_sha256),
  CHECK (
    (status IN ('CONTENT_UNAVAILABLE', 'DELETED') AND content_deleted_at IS NOT NULL)
    OR status IN ('STAGING', 'AVAILABLE')
  )
);

CREATE INDEX idx_document_picture_asset_cleanup
  ON document_picture_asset(status, content_deleted_at, created_at, id);

CREATE TABLE document_picture_asset_transfer (
  id TEXT PRIMARY KEY,
  picture_asset_id TEXT NOT NULL UNIQUE REFERENCES document_picture_asset(id),
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  token_hash TEXT NOT NULL CHECK (length(token_hash) = 64),
  expected_media_type TEXT NOT NULL CHECK (expected_media_type IN (
    'image/png', 'image/jpeg', 'image/webp'
  )),
  expected_width_pixels INTEGER NOT NULL CHECK (expected_width_pixels > 0),
  expected_height_pixels INTEGER NOT NULL CHECK (expected_height_pixels > 0),
  expected_size_bytes BIGINT NOT NULL CHECK (expected_size_bytes > 0),
  expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
  received_size_bytes BIGINT NOT NULL DEFAULT 0 CHECK (received_size_bytes >= 0),
  received_sha256 TEXT NOT NULL DEFAULT '' CHECK (length(received_sha256) IN (0, 64)),
  staging_object_key TEXT NOT NULL UNIQUE CHECK (length(staging_object_key) BETWEEN 1 AND 1024),
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN (
    'OPEN', 'UPLOADING', 'STAGED', 'FINALIZED', 'EXPIRED', 'FAILED'
  )),
  error_code TEXT NOT NULL DEFAULT '' CHECK (length(error_code) <= 128),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finalized_at TEXT
);

CREATE INDEX idx_document_picture_asset_transfer_expiry
  ON document_picture_asset_transfer(status, expires_at, id);

CREATE TABLE document_picture_occurrence (
  id TEXT PRIMARY KEY,
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  picture_asset_id TEXT NOT NULL REFERENCES document_picture_asset(id),
  occurrence_index INTEGER NOT NULL CHECK (occurrence_index > 0),
  source_format TEXT NOT NULL CHECK (source_format IN ('DOCX', 'PPTX')),
  picture_ref TEXT NOT NULL CHECK (length(picture_ref) BETWEEN 1 AND 512),
  parent_ref TEXT NOT NULL CHECK (length(parent_ref) BETWEEN 1 AND 512),
  parent_label TEXT NOT NULL DEFAULT '' CHECK (length(parent_label) <= 128),
  parent_ordinal INTEGER NOT NULL CHECK (parent_ordinal >= 0),
  slide_no INTEGER CHECK (slide_no IS NULL OR slide_no > 0),
  parent_bbox_json TEXT NOT NULL DEFAULT '' CHECK (length(parent_bbox_json) <= 256),
  selection_status TEXT NOT NULL DEFAULT 'SELECTED'
    CHECK (selection_status IN ('SELECTED', 'SKIPPED_LIMIT')),
  created_at TEXT NOT NULL,
  UNIQUE(processing_run_id, picture_ref),
  UNIQUE(processing_run_id, occurrence_index),
  CHECK (
    (source_format = 'DOCX' AND slide_no IS NULL AND parent_bbox_json = '')
    OR (source_format = 'PPTX' AND slide_no IS NOT NULL AND parent_bbox_json <> '')
  )
);

CREATE INDEX idx_document_picture_occurrence_asset
  ON document_picture_occurrence(picture_asset_id, occurrence_index);

CREATE TABLE document_picture_processing_item (
  id TEXT PRIMARY KEY,
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  picture_asset_id TEXT NOT NULL REFERENCES document_picture_asset(id),
  status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN (
    'QUEUED', 'CLAIMED', 'SUBMITTED', 'RETRY_WAIT',
    'AVAILABLE', 'NO_TEXT', 'SKIPPED_LIMIT', 'FAILED'
  )),
  occurrence_count INTEGER NOT NULL CHECK (occurrence_count > 0),
  attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  external_task_id TEXT NOT NULL DEFAULT '' CHECK (length(external_task_id) <= 256),
  ocr_engine_code TEXT NOT NULL CHECK (length(ocr_engine_code) BETWEEN 1 AND 128),
  model_revision TEXT NOT NULL CHECK (length(model_revision) BETWEEN 1 AND 128),
  model_digest TEXT NOT NULL CHECK (
    length(model_digest) = 71 AND substr(model_digest, 1, 7) = 'sha256:'
  ),
  claim_token TEXT NOT NULL DEFAULT '' CHECK (length(claim_token) <= 128),
  claimed_at TEXT,
  claim_expires_at TEXT,
  next_retry_at TEXT,
  error_code TEXT NOT NULL DEFAULT '' CHECK (length(error_code) <= 128),
  result_size_bytes BIGINT CHECK (result_size_bytes IS NULL OR result_size_bytes >= 0),
  result_sha256 TEXT NOT NULL DEFAULT '' CHECK (length(result_sha256) IN (0, 64)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(processing_run_id, picture_asset_id),
  CHECK (
    status NOT IN ('AVAILABLE', 'NO_TEXT', 'SKIPPED_LIMIT', 'FAILED')
    OR completed_at IS NOT NULL
  )
);

CREATE INDEX idx_document_picture_item_claim
  ON document_picture_processing_item(status, next_retry_at, created_at, id);

CREATE TABLE document_picture_processing_attempt (
  id TEXT PRIMARY KEY,
  picture_item_id TEXT NOT NULL REFERENCES document_picture_processing_item(id),
  attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
  external_task_id TEXT NOT NULL DEFAULT '' CHECK (length(external_task_id) <= 256),
  status TEXT NOT NULL CHECK (status IN (
    'CLAIMED', 'SUBMITTED', 'SUCCEEDED', 'RETRYABLE_FAILED', 'FAILED'
  )),
  error_code TEXT NOT NULL DEFAULT '' CHECK (length(error_code) <= 128),
  started_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(picture_item_id, attempt_no)
);

CREATE TABLE document_picture_result_transfer (
  id TEXT PRIMARY KEY,
  picture_item_id TEXT NOT NULL UNIQUE REFERENCES document_picture_processing_item(id),
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  token_hash TEXT NOT NULL CHECK (length(token_hash) = 64),
  expected_size_bytes BIGINT NOT NULL CHECK (expected_size_bytes > 0),
  expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
  received_size_bytes BIGINT NOT NULL DEFAULT 0 CHECK (received_size_bytes >= 0),
  received_sha256 TEXT NOT NULL DEFAULT '' CHECK (length(received_sha256) IN (0, 64)),
  staging_object_key TEXT NOT NULL UNIQUE CHECK (length(staging_object_key) BETWEEN 1 AND 1024),
  status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN (
    'OPEN', 'UPLOADING', 'STAGED', 'FINALIZED', 'EXPIRED', 'FAILED'
  )),
  error_code TEXT NOT NULL DEFAULT '' CHECK (length(error_code) <= 128),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finalized_at TEXT
);

CREATE INDEX idx_document_picture_result_transfer_expiry
  ON document_picture_result_transfer(status, expires_at, id);

CREATE TABLE document_processing_stage_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE CHECK (length(event_key) BETWEEN 1 AND 256),
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  picture_item_id TEXT REFERENCES document_picture_processing_item(id),
  item_key TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL CHECK (event_type IN (
    'PICTURE_OCR_REQUESTED', 'ASSEMBLY_REQUESTED'
  )),
  payload_json TEXT NOT NULL CHECK (length(payload_json) BETWEEN 2 AND 4096),
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN (
    'PENDING', 'CLAIMED', 'PUBLISHED', 'FAILED', 'DEAD'
  )),
  attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  claim_token TEXT NOT NULL DEFAULT '' CHECK (length(claim_token) <= 128),
  claimed_at TEXT,
  next_attempt_at TEXT NOT NULL,
  error_code TEXT NOT NULL DEFAULT '' CHECK (length(error_code) <= 128),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  published_at TEXT,
  UNIQUE(event_type, processing_run_id, item_key),
  CHECK (
    (event_type = 'PICTURE_OCR_REQUESTED' AND picture_item_id IS NOT NULL
      AND item_key = picture_item_id)
    OR (event_type = 'ASSEMBLY_REQUESTED' AND picture_item_id IS NULL
      AND item_key = '')
  )
);

CREATE INDEX idx_document_processing_stage_outbox_claim
  ON document_processing_stage_outbox(status, next_attempt_at, created_at, id);

CREATE TABLE document_picture_cleanup_fact (
  id TEXT PRIMARY KEY,
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  object_kind TEXT NOT NULL CHECK (object_kind IN (
    'PARENT_ARTIFACT', 'PICTURE_ASSET', 'PICTURE_RESULT'
  )),
  object_id TEXT NOT NULL,
  internal_object_key TEXT NOT NULL CHECK (length(internal_object_key) BETWEEN 1 AND 1024),
  reason_code TEXT NOT NULL CHECK (length(reason_code) BETWEEN 1 AND 128),
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN (
    'PENDING', 'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', 'DEAD'
  )),
  attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  next_attempt_at TEXT NOT NULL,
  error_code TEXT NOT NULL DEFAULT '' CHECK (length(error_code) <= 128),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(object_kind, object_id)
);

CREATE INDEX idx_document_picture_cleanup_claim
  ON document_picture_cleanup_fact(status, next_attempt_at, created_at, id);

CREATE INDEX idx_file_processing_run_layout_stage
  ON file_processing_run(profile_code, stage_code, assembly_status, updated_at, id);

-- postgres-only
COMMENT ON COLUMN business_application_revision.document_processing_profile_code IS
  '草稿修订选择的代码注册文档处理Profile；支持NONE、文字或布局OCR';
-- postgres-only
COMMENT ON COLUMN business_application_publication.document_processing_profile_code IS
  'Publication冻结的单一文档处理Profile代码';
-- postgres-only
COMMENT ON COLUMN agent_job_file_request.document_processing_profile_code IS
  'Job文件请求冻结的单一文档处理Profile代码';
-- postgres-only
COMMENT ON COLUMN file_processing_run.profile_code IS '固定文字或布局OCR Profile代码';
-- postgres-only
COMMENT ON COLUMN file_processing_run.stage_code IS '布局OCR运行的父解析、逐图OCR或组装阶段';
-- postgres-only
COMMENT ON COLUMN file_processing_run.required_output_kinds_json IS '运行创建时冻结的必需表示种类集合';
-- postgres-only
COMMENT ON COLUMN file_processing_run.run_deadline_at IS '布局OCR父运行不可滚动的总截止时间';
-- postgres-only
COMMENT ON COLUMN file_processing_run.assembly_status IS '最终组装的独立幂等状态';
-- postgres-only
COMMENT ON COLUMN file_processing_run.assembly_attempt IS '最终组装尝试次数';
-- postgres-only
COMMENT ON COLUMN file_processing_run.assembly_claim_token IS '最终组装短期claim身份摘要';
-- postgres-only
COMMENT ON COLUMN file_processing_run.assembly_claimed_at IS '最终组装最近claim时间';
-- postgres-only
COMMENT ON COLUMN file_representation.kind IS 'Markdown、Docling JSON或OCR布局JSON表示种类';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.kind IS 'transfer绑定的Profile必需表示种类';

-- postgres-only
COMMENT ON TABLE document_parent_artifact_transfer IS '布局OCR父Markdown的私有暂存与可恢复传输事实';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.id IS '父artifact transfer稳定身份';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.processing_run_id IS '父artifact所属精确处理运行';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.kind IS '固定父Markdown种类';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.token_hash IS '一次性上传凭证hash';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.expected_size_bytes IS '预期父Markdown字节数';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.expected_sha256 IS '预期父Markdown SHA-256';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.received_size_bytes IS '实际接收父Markdown字节数';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.received_sha256 IS '实际接收父Markdown SHA-256';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.staging_object_key IS '仅File Service解析的私有暂存位置';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.status IS '父artifact transfer状态';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.error_code IS '白名单transfer错误码';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.expires_at IS '未终结transfer到期时间';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.created_at IS 'transfer创建时间';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.updated_at IS 'transfer最近更新时间';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.finalized_at IS '父Markdown完成暂存时间';
-- postgres-only
COMMENT ON COLUMN document_parent_artifact_transfer.content_deleted_at IS '父Markdown内容不可用时间';

-- postgres-only
COMMENT ON TABLE document_picture_asset IS 'Office内嵌图片规范化派生资产身份与生命周期事实';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.id IS '图片资产稳定身份';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.processing_run_id IS '图片资产所属父处理运行';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.tenant_id IS '继承父运行的tenant身份';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.source_file_id IS '图片资产所属原始文件';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.source_version_id IS '图片资产所属精确原始版本';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.profile_code IS '固定布局OCR Profile代码';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.profile_hash IS '固定布局OCR Profile SHA-256';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.normalized_sha256 IS '同一运行内规范化图片SHA-256';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.media_type IS '规范化图片媒体类型';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.original_width_pixels IS '方向归一前图片宽度像素';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.original_height_pixels IS '方向归一前图片高度像素';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.width_pixels IS '规范化图片宽度像素';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.height_pixels IS '规范化图片高度像素';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.normalization_transform_json IS '不含正文的有界EXIF方向变换provenance';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.size_bytes IS '规范化图片字节数';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.object_key IS '仅File Service解析的内部对象位置';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.status IS '图片资产内容可用性状态';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.created_at IS '图片资产创建时间';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.updated_at IS '图片资产最近更新时间';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.content_deleted_at IS '图片资产内容不可用时间';
-- postgres-only
COMMENT ON COLUMN document_picture_asset.cleanup_error_code IS '清理失败的白名单错误码';

-- postgres-only
COMMENT ON TABLE document_picture_asset_transfer IS '绑定图片资产的两阶段staging传输事实';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.id IS '图片资产transfer身份';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.picture_asset_id IS 'transfer绑定的图片资产';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.processing_run_id IS 'transfer绑定的父处理运行';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.token_hash IS '一次性上传凭证hash';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.expected_media_type IS '预期规范化媒体类型';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.expected_width_pixels IS '预期图片宽度像素';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.expected_height_pixels IS '预期图片高度像素';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.expected_size_bytes IS '预期图片字节数';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.expected_sha256 IS '预期规范化图片SHA-256';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.received_size_bytes IS '实际接收图片字节数';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.received_sha256 IS '实际接收图片SHA-256';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.staging_object_key IS '仅File Service解析的暂存位置';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.status IS '图片资产transfer状态';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.error_code IS '白名单transfer错误码';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.expires_at IS '未终结transfer到期时间';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.created_at IS 'transfer创建时间';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.updated_at IS 'transfer最近更新时间';
-- postgres-only
COMMENT ON COLUMN document_picture_asset_transfer.finalized_at IS 'transfer终结时间';

-- postgres-only
COMMENT ON TABLE document_picture_occurrence IS '图片资产在精确Office文档中的稳定出现位置';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.id IS '图片occurrence稳定身份';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.processing_run_id IS 'occurrence所属父处理运行';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.picture_asset_id IS 'occurrence引用的规范化图片资产';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.occurrence_index IS '父文档内稳定出现顺序';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.source_format IS 'DOCX或PPTX父格式';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.picture_ref IS 'Docling稳定picture self_ref';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.parent_ref IS 'Docling可解析最近父容器ref';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.parent_label IS '父容器安全结构label';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.parent_ordinal IS '同父容器内稳定顺序';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.slide_no IS 'PPTX slide编号；DOCX为空';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.parent_bbox_json IS 'PPTX父slide归一化bbox摘要';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.selection_status IS '按稳定occurrence软上限冻结的选择状态';
-- postgres-only
COMMENT ON COLUMN document_picture_occurrence.created_at IS 'occurrence创建时间';

-- postgres-only
COMMENT ON TABLE document_picture_processing_item IS '按唯一图片资产持久化的逐图OCR工作项';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.id IS '逐图OCR item稳定身份';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.processing_run_id IS 'item所属父处理运行';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.picture_asset_id IS 'item处理的规范化图片资产';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.status IS '逐图OCR受控状态';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.occurrence_count IS '复用该OCR结果的occurrence数量';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.attempt IS '当前逐图OCR attempt序号';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.external_task_id IS '当前Docling临时task身份';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.ocr_engine_code IS '代码固定OCR引擎代码';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.model_revision IS '固定OCR模型revision';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.model_digest IS '固定模型artifact digest';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.claim_token IS '逐图item短期claim身份摘要';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.claimed_at IS '最近claim时间';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.claim_expires_at IS 'claim租约到期时间';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.next_retry_at IS '有限重试下次到期时间';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.error_code IS '白名单OCR错误码';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.result_size_bytes IS '私有OCR结果对象字节数';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.result_sha256 IS '私有OCR结果对象SHA-256';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.created_at IS 'item创建时间';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.updated_at IS 'item最近更新时间';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_item.completed_at IS 'item确定终态时间';

-- postgres-only
COMMENT ON TABLE document_picture_processing_attempt IS '逐图OCR每次外部调用的安全attempt事实';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_attempt.id IS 'attempt稳定身份';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_attempt.picture_item_id IS 'attempt所属逐图item';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_attempt.attempt_no IS 'item内单调attempt序号';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_attempt.external_task_id IS '该attempt的Docling临时task身份';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_attempt.status IS 'attempt安全状态';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_attempt.error_code IS 'attempt白名单错误码';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_attempt.started_at IS 'attempt开始时间';
-- postgres-only
COMMENT ON COLUMN document_picture_processing_attempt.completed_at IS 'attempt结束时间';

-- postgres-only
COMMENT ON TABLE document_picture_result_transfer IS '逐图OCR私有结果的两阶段staging传输事实';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.id IS '逐图结果transfer身份';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.picture_item_id IS 'transfer绑定的逐图item';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.processing_run_id IS 'transfer绑定的父运行';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.token_hash IS '一次性上传凭证hash';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.expected_size_bytes IS '预期结果字节数';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.expected_sha256 IS '预期结果SHA-256';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.received_size_bytes IS '实际结果字节数';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.received_sha256 IS '实际结果SHA-256';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.staging_object_key IS '仅File Service解析的结果暂存位置';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.status IS '逐图结果transfer状态';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.error_code IS '白名单transfer错误码';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.expires_at IS '未终结transfer到期时间';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.created_at IS 'transfer创建时间';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.updated_at IS 'transfer最近更新时间';
-- postgres-only
COMMENT ON COLUMN document_picture_result_transfer.finalized_at IS 'transfer终结时间';

-- postgres-only
COMMENT ON TABLE document_processing_stage_outbox IS '布局OCR逐图与assembly的持久安全Outbox';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.id IS '阶段Outbox稳定身份';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.event_key IS '阶段事件幂等键';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.processing_run_id IS '事件所属父运行';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.picture_item_id IS '逐图事件绑定item；assembly为空';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.item_key IS 'NULL安全的阶段唯一item键';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.event_type IS '逐图OCR或assembly事件类型';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.payload_json IS '不含内容与对象位置的有界安全消息';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.status IS '阶段Outbox发布状态';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.attempt IS 'Outbox发布attempt次数';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.claim_token IS 'Outbox短期claim身份摘要';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.claimed_at IS 'Outbox最近claim时间';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.next_attempt_at IS 'Outbox下次发布时间';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.error_code IS 'Outbox白名单错误码';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.created_at IS 'Outbox创建时间';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.updated_at IS 'Outbox最近更新时间';
-- postgres-only
COMMENT ON COLUMN document_processing_stage_outbox.published_at IS 'Outbox成功发布时间';

-- postgres-only
COMMENT ON TABLE document_picture_cleanup_fact IS '图片asset与私有OCR结果的可重试清理事实';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.id IS '清理事实稳定身份';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.processing_run_id IS '清理对象所属父运行';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.object_kind IS '父artifact、图片asset或逐图结果对象种类';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.object_id IS '待清理领域对象身份';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.internal_object_key IS '仅File Service解析的内部对象位置';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.reason_code IS '进入清理的稳定原因码';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.status IS '可重试清理状态';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.attempt IS '清理attempt次数';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.next_attempt_at IS '下次清理时间';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.error_code IS '清理白名单错误码';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.created_at IS '清理事实创建时间';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.updated_at IS '清理事实最近更新时间';
-- postgres-only
COMMENT ON COLUMN document_picture_cleanup_fact.completed_at IS '清理确定完成时间';
