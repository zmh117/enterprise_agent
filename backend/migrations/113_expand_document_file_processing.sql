-- Expand governed document processing facts. This migration only creates
-- relational identities and compatibility fields. It never reads, copies, or
-- deletes object-storage content.
-- migration: sqlite-foreign-keys-off

ALTER TABLE business_application_revision
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN ('NONE', 'docling-text-v1'));

ALTER TABLE business_application_publication
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN ('NONE', 'docling-text-v1'));

ALTER TABLE business_application_publication
  ADD COLUMN document_processing_profile_version TEXT NOT NULL DEFAULT '';

ALTER TABLE business_application_publication
  ADD COLUMN document_processing_profile_hash TEXT NOT NULL DEFAULT ''
  CHECK (length(document_processing_profile_hash) IN (0, 64));

ALTER TABLE agent_job_file_request
  ADD COLUMN document_processing_profile_code TEXT NOT NULL DEFAULT 'NONE'
  CHECK (document_processing_profile_code IN ('NONE', 'docling-text-v1'));

ALTER TABLE agent_job_file_request
  ADD COLUMN document_processing_profile_hash TEXT NOT NULL DEFAULT ''
  CHECK (length(document_processing_profile_hash) IN (0, 64));

-- SQLite cannot widen an existing column CHECK constraint in place.
-- sqlite-only
CREATE TABLE managed_file_document_sources (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 128),
  owner_type TEXT NOT NULL
    CHECK (owner_type IN ('PRIVATE_USER', 'GROUP_CONVERSATION')),
  owner_user_id TEXT NOT NULL DEFAULT '',
  owner_enterprise_id TEXT NOT NULL DEFAULT '',
  owner_connector_id TEXT NOT NULL DEFAULT '',
  owner_conversation_id TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 255),
  current_version_id TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'CONTENT_UNAVAILABLE', 'DELETED')),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT,
  source_received_at TEXT,
  format_code TEXT NOT NULL DEFAULT 'TXT'
    CHECK (format_code IN (
      'TXT', 'LOG', 'MARKDOWN', 'PDF', 'DOCX', 'PPTX', 'XLSX',
      'PNG', 'JPEG', 'WEBP'
    )),
  CHECK (
    (owner_type = 'PRIVATE_USER'
      AND length(owner_user_id) > 0
      AND owner_enterprise_id = ''
      AND owner_connector_id = ''
      AND owner_conversation_id = '')
    OR
    (owner_type = 'GROUP_CONVERSATION'
      AND owner_user_id = ''
      AND length(owner_enterprise_id) > 0
      AND length(owner_connector_id) > 0
      AND length(owner_conversation_id) > 0)
  ),
  CHECK (
    (status = 'DELETED' AND deleted_at IS NOT NULL)
    OR status <> 'DELETED'
  )
);

-- sqlite-only
INSERT INTO managed_file_document_sources (
  id, tenant_id, owner_type, owner_user_id, owner_enterprise_id,
  owner_connector_id, owner_conversation_id, display_name, current_version_id,
  status, created_by, created_at, updated_at, deleted_at, source_received_at,
  format_code
)
SELECT
  id, tenant_id, owner_type, owner_user_id, owner_enterprise_id,
  owner_connector_id, owner_conversation_id, display_name, current_version_id,
  status, created_by, created_at, updated_at, deleted_at, source_received_at,
  format_code
FROM managed_file;

-- sqlite-only
DROP TABLE managed_file;

-- sqlite-only
ALTER TABLE managed_file_document_sources RENAME TO managed_file;

-- sqlite-only
CREATE INDEX idx_managed_file_private_owner
  ON managed_file(tenant_id, owner_user_id, status, updated_at);

-- sqlite-only
CREATE INDEX idx_managed_file_group_owner
  ON managed_file(
    tenant_id, owner_enterprise_id, owner_connector_id,
    owner_conversation_id, status, updated_at
  );

-- sqlite-only
CREATE TABLE managed_file_version_document_sources (
  id TEXT PRIMARY KEY,
  file_id TEXT NOT NULL REFERENCES managed_file(id) ON DELETE CASCADE,
  version_number BIGINT NOT NULL CHECK (version_number > 0),
  parent_version_id TEXT REFERENCES managed_file_version_document_sources(id),
  base_version_id TEXT REFERENCES managed_file_version_document_sources(id),
  version_kind TEXT NOT NULL
    CHECK (version_kind IN ('ATTACHMENT', 'WORKING', 'OUTPUT', 'CONFLICT')),
  status TEXT NOT NULL DEFAULT 'AVAILABLE'
    CHECK (status IN ('AVAILABLE', 'CONFLICT', 'CONTENT_UNAVAILABLE', 'DELETED')),
  media_type TEXT NOT NULL,
  encoding TEXT NOT NULL DEFAULT '',
  size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  object_key TEXT NOT NULL UNIQUE CHECK (length(object_key) BETWEEN 1 AND 1024),
  source_kind TEXT NOT NULL
    CHECK (source_kind IN (
      'MESSAGE_ATTACHMENT', 'AGENT_GENERATED', 'AGENT_EDITED', 'CONFLICT'
    )),
  source_reference_digest TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  content_deleted_at TEXT,
  format_code TEXT NOT NULL DEFAULT 'TXT'
    CHECK (format_code IN (
      'TXT', 'LOG', 'MARKDOWN', 'PDF', 'DOCX', 'PPTX', 'XLSX',
      'PNG', 'JPEG', 'WEBP'
    )),
  UNIQUE(file_id, version_number),
  CHECK (
    (status IN ('CONTENT_UNAVAILABLE', 'DELETED') AND content_deleted_at IS NOT NULL)
    OR status IN ('AVAILABLE', 'CONFLICT')
  )
);

-- sqlite-only
INSERT INTO managed_file_version_document_sources (
  id, file_id, version_number, parent_version_id, base_version_id,
  version_kind, status, media_type, encoding, size_bytes, content_sha256,
  object_key, source_kind, source_reference_digest, created_by, created_at,
  content_deleted_at, format_code
)
SELECT
  id, file_id, version_number, parent_version_id, base_version_id,
  version_kind, status, media_type, encoding, size_bytes, content_sha256,
  object_key, source_kind, source_reference_digest, created_by, created_at,
  content_deleted_at, format_code
FROM managed_file_version;

-- sqlite-only
DROP TABLE managed_file_version;

-- sqlite-only
ALTER TABLE managed_file_version_document_sources RENAME TO managed_file_version;

-- sqlite-only
CREATE INDEX idx_managed_file_version_file
  ON managed_file_version(file_id, version_number);

-- sqlite-only
CREATE INDEX idx_managed_file_version_status
  ON managed_file_version(status, created_at);

-- postgres-only
ALTER TABLE managed_file DROP CONSTRAINT managed_file_format_code_check;

-- postgres-only
ALTER TABLE managed_file ADD CONSTRAINT managed_file_format_code_check
  CHECK (format_code IN (
    'TXT', 'LOG', 'MARKDOWN', 'PDF', 'DOCX', 'PPTX', 'XLSX',
    'PNG', 'JPEG', 'WEBP'
  ));

-- postgres-only
ALTER TABLE managed_file_version
  DROP CONSTRAINT managed_file_version_format_code_check;

-- postgres-only
ALTER TABLE managed_file_version
  ADD CONSTRAINT managed_file_version_format_code_check
  CHECK (format_code IN (
    'TXT', 'LOG', 'MARKDOWN', 'PDF', 'DOCX', 'PPTX', 'XLSX',
    'PNG', 'JPEG', 'WEBP'
  ));

CREATE UNIQUE INDEX uq_managed_file_version_identity
  ON managed_file_version(id, file_id);

CREATE TABLE file_processing_run (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 128),
  source_file_id TEXT NOT NULL REFERENCES managed_file(id),
  source_version_id TEXT NOT NULL,
  processor_code TEXT NOT NULL CHECK (processor_code = 'docling-serve'),
  processor_version TEXT NOT NULL CHECK (length(processor_version) BETWEEN 1 AND 64),
  processor_build_digest TEXT NOT NULL
    CHECK (
      length(processor_build_digest) = 71
      AND substr(processor_build_digest, 1, 7) = 'sha256:'
    ),
  profile_code TEXT NOT NULL CHECK (profile_code = 'docling-text-v1'),
  profile_hash TEXT NOT NULL CHECK (length(profile_hash) = 64),
  status TEXT NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN (
      'QUEUED', 'SUBMITTED', 'RUNNING', 'RETRY_WAIT',
      'SUCCEEDED', 'PARTIAL', 'NO_TEXT', 'FAILED'
    )),
  attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  external_task_id TEXT NOT NULL DEFAULT '' CHECK (length(external_task_id) <= 256),
  error_code TEXT NOT NULL DEFAULT '' CHECK (length(error_code) <= 128),
  source_size_bytes BIGINT NOT NULL CHECK (source_size_bytes >= 0),
  page_count INTEGER CHECK (page_count IS NULL OR page_count >= 0),
  processing_time_ms BIGINT CHECK (processing_time_ms IS NULL OR processing_time_ms >= 0),
  next_retry_at TEXT,
  started_at TEXT,
  completed_at TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (source_version_id, source_file_id)
    REFERENCES managed_file_version(id, file_id),
  UNIQUE(id, tenant_id, source_file_id, source_version_id),
  CHECK (
    status NOT IN ('SUCCEEDED', 'PARTIAL', 'NO_TEXT', 'FAILED')
    OR completed_at IS NOT NULL
  )
);

CREATE UNIQUE INDEX uq_file_processing_run_build_profile
  ON file_processing_run(
    source_version_id, processor_build_digest, profile_hash
  );

CREATE INDEX idx_file_processing_run_retry_due
  ON file_processing_run(status, next_retry_at, id);

CREATE INDEX idx_file_processing_run_tenant_status
  ON file_processing_run(tenant_id, status, created_at, id);

CREATE INDEX idx_file_processing_run_job_lookup
  ON file_processing_run(source_file_id, source_version_id, status);

CREATE TABLE file_representation (
  id TEXT PRIMARY KEY,
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  tenant_id TEXT NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 128),
  source_file_id TEXT NOT NULL REFERENCES managed_file(id),
  source_version_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('MARKDOWN', 'DOCLING_JSON')),
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
    OR (kind = 'DOCLING_JSON' AND media_type = 'application/json')
  ),
  CHECK (
    (status IN ('CONTENT_UNAVAILABLE', 'DELETED') AND content_deleted_at IS NOT NULL)
    OR status = 'AVAILABLE'
  )
);

CREATE UNIQUE INDEX uq_file_representation_run_kind
  ON file_representation(processing_run_id, kind);

CREATE INDEX idx_file_representation_source
  ON file_representation(
    tenant_id, source_file_id, source_version_id, kind, status
  );

CREATE INDEX idx_file_representation_cleanup
  ON file_representation(status, content_deleted_at, created_at, id);

CREATE TABLE file_representation_transfer (
  id TEXT PRIMARY KEY,
  processing_run_id TEXT NOT NULL REFERENCES file_processing_run(id),
  kind TEXT NOT NULL CHECK (kind IN ('MARKDOWN', 'DOCLING_JSON')),
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

CREATE INDEX idx_file_representation_transfer_expiry
  ON file_representation_transfer(status, expires_at, id);

ALTER TABLE message_attachment
  ADD COLUMN readability_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED'
  CHECK (readability_status IN (
    'NOT_REQUIRED', 'PENDING', 'AVAILABLE', 'PARTIAL', 'NO_TEXT', 'UNAVAILABLE'
  ));

ALTER TABLE message_attachment
  ADD COLUMN file_processing_run_id TEXT REFERENCES file_processing_run(id);

ALTER TABLE message_attachment
  ADD COLUMN readability_error_code TEXT NOT NULL DEFAULT ''
  CHECK (length(readability_error_code) <= 128);

ALTER TABLE message_attachment
  ADD COLUMN readability_updated_at TEXT;

CREATE INDEX idx_message_attachment_readability
  ON message_attachment(readability_status, updated_at, id);

CREATE INDEX idx_message_attachment_processing_run
  ON message_attachment(file_processing_run_id);

-- SQLite cannot replace the Manifest schema-version CHECK in place.
-- sqlite-only
CREATE TABLE agent_job_file_snapshot_schema_v4 (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id),
  tenant_id TEXT NOT NULL,
  principal_user_id TEXT NOT NULL,
  business_application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  retention_period TEXT NOT NULL
    CHECK (retention_period IN ('DAY', 'WEEK', 'MONTH')),
  schema_version INTEGER NOT NULL DEFAULT 4
    CHECK (schema_version IN (1, 2, 3, 4)),
  file_format_policy_version TEXT NOT NULL DEFAULT 'text-v1'
    CHECK (file_format_policy_version IN ('text-v1', 'text-v2')),
  manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
  created_at TEXT NOT NULL
);

-- sqlite-only
INSERT INTO agent_job_file_snapshot_schema_v4 (
  id, job_id, workspace_id, tenant_id, principal_user_id,
  business_application_publication_id, retention_period, schema_version,
  file_format_policy_version, manifest_hash, created_at
)
SELECT
  id, job_id, workspace_id, tenant_id, principal_user_id,
  business_application_publication_id, retention_period, schema_version,
  file_format_policy_version, manifest_hash, created_at
FROM agent_job_file_snapshot;

-- sqlite-only
DROP TABLE agent_job_file_snapshot;

-- sqlite-only
ALTER TABLE agent_job_file_snapshot_schema_v4 RENAME TO agent_job_file_snapshot;

-- sqlite-only
CREATE INDEX idx_agent_job_file_snapshot_workspace
  ON agent_job_file_snapshot(workspace_id, created_at);

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  DROP CONSTRAINT agent_job_file_snapshot_schema_version_check;

-- postgres-only
ALTER TABLE agent_job_file_snapshot ALTER COLUMN schema_version SET DEFAULT 4;

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  ADD CONSTRAINT agent_job_file_snapshot_schema_version_check
  CHECK (schema_version IN (1, 2, 3, 4));

-- SQLite needs a table-level all-or-none representation constraint.
-- sqlite-only
CREATE TABLE agent_job_file_snapshot_item_schema_v4 (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL
    REFERENCES agent_job_file_snapshot(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
  file_id TEXT NOT NULL REFERENCES managed_file(id),
  version_id TEXT NOT NULL REFERENCES managed_file_version(id),
  display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 255),
  source_kind TEXT NOT NULL
    CHECK (source_kind IN (
      'CURRENT_MESSAGE', 'EXPLICIT_REFERENCE', 'WORKSPACE', 'CONFLICT'
    )),
  allowed_actions_json TEXT NOT NULL DEFAULT '[]',
  auto_materialize INTEGER NOT NULL DEFAULT 0 CHECK (auto_materialize IN (0, 1)),
  conflict_candidate INTEGER NOT NULL DEFAULT 0
    CHECK (conflict_candidate IN (0, 1)),
  created_at TEXT NOT NULL,
  source_received_at TEXT,
  version_created_at TEXT NOT NULL DEFAULT '',
  format_code TEXT NOT NULL DEFAULT 'TXT'
    CHECK (format_code IN (
      'TXT', 'LOG', 'MARKDOWN', 'PDF', 'DOCX', 'PPTX', 'XLSX',
      'PNG', 'JPEG', 'WEBP'
    )),
  representation_id TEXT REFERENCES file_representation(id),
  representation_kind TEXT
    CHECK (representation_kind IS NULL OR representation_kind = 'MARKDOWN'),
  representation_size_bytes BIGINT
    CHECK (representation_size_bytes IS NULL OR representation_size_bytes >= 0),
  representation_sha256 TEXT
    CHECK (representation_sha256 IS NULL OR length(representation_sha256) = 64),
  representation_format_code TEXT
    CHECK (
      representation_format_code IS NULL
      OR representation_format_code = 'MARKDOWN'
    ),
  representation_created_at TEXT,
  UNIQUE(snapshot_id, ordinal),
  UNIQUE(snapshot_id, file_id, version_id),
  CHECK (
    (representation_id IS NULL
      AND representation_kind IS NULL
      AND representation_size_bytes IS NULL
      AND representation_sha256 IS NULL
      AND representation_format_code IS NULL
      AND representation_created_at IS NULL)
    OR
    (representation_id IS NOT NULL
      AND representation_kind = 'MARKDOWN'
      AND representation_size_bytes IS NOT NULL
      AND representation_sha256 IS NOT NULL
      AND representation_format_code = 'MARKDOWN'
      AND representation_created_at IS NOT NULL)
  )
);

-- sqlite-only
INSERT INTO agent_job_file_snapshot_item_schema_v4 (
  id, snapshot_id, ordinal, file_id, version_id, display_name, source_kind,
  allowed_actions_json, auto_materialize, conflict_candidate, created_at,
  source_received_at, version_created_at, format_code
)
SELECT
  id, snapshot_id, ordinal, file_id, version_id, display_name, source_kind,
  allowed_actions_json, auto_materialize, conflict_candidate, created_at,
  source_received_at, version_created_at, format_code
FROM agent_job_file_snapshot_item;

-- sqlite-only
DROP TABLE agent_job_file_snapshot_item;

-- sqlite-only
ALTER TABLE agent_job_file_snapshot_item_schema_v4
  RENAME TO agent_job_file_snapshot_item;

-- sqlite-only
CREATE INDEX idx_agent_job_file_snapshot_item_version
  ON agent_job_file_snapshot_item(version_id);

-- sqlite-only
CREATE INDEX idx_agent_job_file_snapshot_item_representation
  ON agent_job_file_snapshot_item(representation_id);

-- postgres-only
ALTER TABLE agent_job_file_snapshot_item
  DROP CONSTRAINT agent_job_file_snapshot_item_format_code_check;

-- postgres-only
ALTER TABLE agent_job_file_snapshot_item
  ADD CONSTRAINT agent_job_file_snapshot_item_format_code_check
  CHECK (format_code IN (
    'TXT', 'LOG', 'MARKDOWN', 'PDF', 'DOCX', 'PPTX', 'XLSX',
    'PNG', 'JPEG', 'WEBP'
  ));

-- postgres-only
ALTER TABLE agent_job_file_snapshot_item
  ADD COLUMN representation_id TEXT REFERENCES file_representation(id);

-- postgres-only
ALTER TABLE agent_job_file_snapshot_item
  ADD COLUMN representation_kind TEXT
  CHECK (representation_kind IS NULL OR representation_kind = 'MARKDOWN');

-- postgres-only
ALTER TABLE agent_job_file_snapshot_item
  ADD COLUMN representation_size_bytes BIGINT
  CHECK (representation_size_bytes IS NULL OR representation_size_bytes >= 0);

-- postgres-only
ALTER TABLE agent_job_file_snapshot_item
  ADD COLUMN representation_sha256 TEXT
  CHECK (representation_sha256 IS NULL OR length(representation_sha256) = 64);

-- postgres-only
ALTER TABLE agent_job_file_snapshot_item
  ADD COLUMN representation_format_code TEXT
  CHECK (
    representation_format_code IS NULL OR representation_format_code = 'MARKDOWN'
  );

-- postgres-only
ALTER TABLE agent_job_file_snapshot_item
  ADD COLUMN representation_created_at TEXT;

-- postgres-only
ALTER TABLE agent_job_file_snapshot_item
  ADD CONSTRAINT agent_job_file_snapshot_item_representation_check
  CHECK (
    (representation_id IS NULL
      AND representation_kind IS NULL
      AND representation_size_bytes IS NULL
      AND representation_sha256 IS NULL
      AND representation_format_code IS NULL
      AND representation_created_at IS NULL)
    OR
    (representation_id IS NOT NULL
      AND representation_kind = 'MARKDOWN'
      AND representation_size_bytes IS NOT NULL
      AND representation_sha256 IS NOT NULL
      AND representation_format_code = 'MARKDOWN'
      AND representation_created_at IS NOT NULL)
  );

-- postgres-only
CREATE INDEX idx_agent_job_file_snapshot_item_representation
  ON agent_job_file_snapshot_item(representation_id);

-- postgres-only
COMMENT ON COLUMN business_application_revision.document_processing_profile_code IS
  '草稿修订选择的代码注册文档处理Profile；NONE保持关闭';

-- postgres-only
COMMENT ON COLUMN business_application_publication.document_processing_profile_code IS
  'Publication冻结的文档处理Profile代码；历史记录为NONE';

-- postgres-only
COMMENT ON COLUMN business_application_publication.document_processing_profile_version IS
  'Publication冻结的处理Profile版本；NONE时为空';

-- postgres-only
COMMENT ON COLUMN business_application_publication.document_processing_profile_hash IS
  'Publication冻结的规范化处理Profile SHA-256；NONE时为空';

-- postgres-only
COMMENT ON COLUMN agent_job_file_request.document_processing_profile_code IS
  'Job文件请求冻结的文档处理Profile代码；历史请求为NONE';

-- postgres-only
COMMENT ON COLUMN agent_job_file_request.document_processing_profile_hash IS
  'Job文件请求冻结的文档处理Profile SHA-256；NONE时为空';

-- postgres-only
COMMENT ON TABLE file_processing_run IS
  '精确原始File Version与处理器build/Profile组合的不可变处理运行';

-- postgres-only
COMMENT ON COLUMN file_processing_run.id IS '文档处理运行稳定身份';
-- postgres-only
COMMENT ON COLUMN file_processing_run.tenant_id IS '处理运行所属tenant身份';
-- postgres-only
COMMENT ON COLUMN file_processing_run.source_file_id IS '精确原始Managed File身份';
-- postgres-only
COMMENT ON COLUMN file_processing_run.source_version_id IS '精确原始File Version身份';
-- postgres-only
COMMENT ON COLUMN file_processing_run.processor_code IS '代码注册处理器代码';
-- postgres-only
COMMENT ON COLUMN file_processing_run.processor_version IS '处理器发布版本';
-- postgres-only
COMMENT ON COLUMN file_processing_run.processor_build_digest IS '固定处理器镜像build digest';
-- postgres-only
COMMENT ON COLUMN file_processing_run.profile_code IS '固定文档处理Profile代码';
-- postgres-only
COMMENT ON COLUMN file_processing_run.profile_hash IS '规范化处理Profile SHA-256';
-- postgres-only
COMMENT ON COLUMN file_processing_run.status IS '受控处理运行状态';
-- postgres-only
COMMENT ON COLUMN file_processing_run.attempt IS '同一逻辑运行的当前attempt序号';
-- postgres-only
COMMENT ON COLUMN file_processing_run.external_task_id IS '当前attempt的Docling临时task身份';
-- postgres-only
COMMENT ON COLUMN file_processing_run.error_code IS '白名单安全处理错误码';
-- postgres-only
COMMENT ON COLUMN file_processing_run.source_size_bytes IS '原始版本字节数';
-- postgres-only
COMMENT ON COLUMN file_processing_run.page_count IS '处理器确认的有界页数';
-- postgres-only
COMMENT ON COLUMN file_processing_run.processing_time_ms IS '处理耗时毫秒数';
-- postgres-only
COMMENT ON COLUMN file_processing_run.next_retry_at IS '有限重试的下一到期时间';
-- postgres-only
COMMENT ON COLUMN file_processing_run.started_at IS '首次开始处理时间';
-- postgres-only
COMMENT ON COLUMN file_processing_run.completed_at IS '确定终态完成时间';
-- postgres-only
COMMENT ON COLUMN file_processing_run.created_by IS '创建处理运行的服务主体';
-- postgres-only
COMMENT ON COLUMN file_processing_run.created_at IS '处理运行创建时间';
-- postgres-only
COMMENT ON COLUMN file_processing_run.updated_at IS '处理运行最近更新时间';

-- postgres-only
COMMENT ON TABLE file_representation IS
  '文档处理运行产生的不可变Markdown或Docling JSON派生表示事实';

-- postgres-only
COMMENT ON COLUMN file_representation.id IS '派生表示稳定身份';
-- postgres-only
COMMENT ON COLUMN file_representation.processing_run_id IS '产生表示的精确处理运行';
-- postgres-only
COMMENT ON COLUMN file_representation.tenant_id IS '继承原始版本的tenant身份';
-- postgres-only
COMMENT ON COLUMN file_representation.source_file_id IS '表示所属原始Managed File';
-- postgres-only
COMMENT ON COLUMN file_representation.source_version_id IS '表示所属精确原始版本';
-- postgres-only
COMMENT ON COLUMN file_representation.kind IS 'MARKDOWN或DOCLING_JSON表示种类';
-- postgres-only
COMMENT ON COLUMN file_representation.media_type IS '表示内容媒体类型';
-- postgres-only
COMMENT ON COLUMN file_representation.encoding IS '表示内容固定UTF-8编码';
-- postgres-only
COMMENT ON COLUMN file_representation.status IS '表示内容可用性状态';
-- postgres-only
COMMENT ON COLUMN file_representation.size_bytes IS '表示内容字节数';
-- postgres-only
COMMENT ON COLUMN file_representation.content_sha256 IS '表示完整内容SHA-256';
-- postgres-only
COMMENT ON COLUMN file_representation.object_key IS '仅File Service可解析的内部对象位置';
-- postgres-only
COMMENT ON COLUMN file_representation.profile_hash IS '生成表示的固定Profile SHA-256';
-- postgres-only
COMMENT ON COLUMN file_representation.created_at IS '不可变表示发布时间';
-- postgres-only
COMMENT ON COLUMN file_representation.content_deleted_at IS '表示内容进入不可用状态的时间';

-- postgres-only
COMMENT ON TABLE file_representation_transfer IS
  '绑定处理运行与表示种类的受控两阶段staging传输事实';

-- postgres-only
COMMENT ON COLUMN file_representation_transfer.id IS '不透明staging transfer身份';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.processing_run_id IS 'transfer绑定的处理运行';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.kind IS 'transfer绑定的唯一表示种类';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.token_hash IS '一次性传输凭证的不可逆hash';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.expected_size_bytes IS '调用方声明的预期字节数';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.expected_sha256 IS '调用方声明的预期SHA-256';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.received_size_bytes IS 'File Service实际接收字节数';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.received_sha256 IS 'File Service计算的实际SHA-256';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.staging_object_key IS '仅File Service可解析的暂存对象位置';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.status IS '两阶段传输状态';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.error_code IS '白名单安全传输错误码';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.expires_at IS '未终结transfer到期时间';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.created_at IS 'transfer创建时间';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.updated_at IS 'transfer最近更新时间';
-- postgres-only
COMMENT ON COLUMN file_representation_transfer.finalized_at IS 'transfer确定终结时间';

-- postgres-only
COMMENT ON COLUMN message_attachment.readability_status IS
  '来源导入状态之外的Agent可读性事实';

-- postgres-only
COMMENT ON COLUMN message_attachment.file_processing_run_id IS
  '受支持文档附件绑定的精确处理运行';

-- postgres-only
COMMENT ON COLUMN message_attachment.readability_error_code IS
  '附件可读性失败的白名单安全错误码';

-- postgres-only
COMMENT ON COLUMN message_attachment.readability_updated_at IS
  '附件可读性事实最近更新时间';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot_item.representation_id IS
  'Manifest v4冻结的精确只读Markdown representation身份';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot_item.representation_kind IS
  'Manifest v4冻结的表示种类；第一阶段仅MARKDOWN';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot_item.representation_size_bytes IS
  'Manifest v4冻结的表示字节数';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot_item.representation_sha256 IS
  'Manifest v4冻结的表示内容SHA-256';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot_item.representation_format_code IS
  'Manifest v4冻结的只读表示格式代码';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot_item.representation_created_at IS
  'Manifest v4冻结的表示产生时间';
