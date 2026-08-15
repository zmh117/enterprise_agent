-- Expand governed task file workspaces. This migration creates only database
-- facts and attachment cleanup markers. It never reads, copies, or deletes
-- object-storage content.

ALTER TABLE business_application_revision
  ADD COLUMN task_workspace_retention_period TEXT NOT NULL DEFAULT 'WEEK'
  CHECK (task_workspace_retention_period IN ('DAY', 'WEEK', 'MONTH'));

ALTER TABLE business_application_revision
  ADD COLUMN task_file_features_json TEXT NOT NULL DEFAULT
    '{"default_file_delivery_enabled":false,"file_mcp_enabled":false,"runtime_file_edit_enabled":false,"workspace_enabled":false}';

ALTER TABLE business_application_publication
  ADD COLUMN task_workspace_retention_period TEXT NOT NULL DEFAULT 'WEEK'
  CHECK (task_workspace_retention_period IN ('DAY', 'WEEK', 'MONTH'));

ALTER TABLE business_application_publication
  ADD COLUMN task_file_features_json TEXT NOT NULL DEFAULT
    '{"default_file_delivery_enabled":false,"file_mcp_enabled":false,"runtime_file_edit_enabled":false,"workspace_enabled":false}';

CREATE TABLE task_workspace (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 128),
  session_id TEXT NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
  owner_type TEXT NOT NULL
    CHECK (owner_type IN ('PRIVATE_USER', 'GROUP_CONVERSATION')),
  owner_user_id TEXT NOT NULL DEFAULT '',
  owner_enterprise_id TEXT NOT NULL DEFAULT '',
  owner_connector_id TEXT NOT NULL DEFAULT '',
  owner_conversation_id TEXT NOT NULL DEFAULT '',
  business_application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  retention_period TEXT NOT NULL DEFAULT 'WEEK'
    CHECK (retention_period IN ('DAY', 'WEEK', 'MONTH')),
  retention_timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai'
    CHECK (retention_timezone = 'Asia/Shanghai'),
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'CLOSED', 'EXPIRED', 'CLEANING', 'CLEANED')),
  expires_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  closed_at TEXT,
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
  )
);

CREATE UNIQUE INDEX uq_task_workspace_active_session
  ON task_workspace(session_id)
  WHERE status = 'ACTIVE';
CREATE INDEX idx_task_workspace_expiry
  ON task_workspace(status, expires_at, id);
CREATE INDEX idx_task_workspace_private_owner
  ON task_workspace(tenant_id, owner_user_id, status);
CREATE INDEX idx_task_workspace_group_owner
  ON task_workspace(
    tenant_id, owner_enterprise_id, owner_connector_id,
    owner_conversation_id, status
  );

ALTER TABLE agent_job
  ADD COLUMN task_workspace_id TEXT REFERENCES task_workspace(id);

CREATE INDEX idx_agent_job_task_workspace
  ON agent_job(task_workspace_id, created_at);

CREATE TABLE managed_file (
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

CREATE INDEX idx_managed_file_private_owner
  ON managed_file(tenant_id, owner_user_id, status, updated_at);
CREATE INDEX idx_managed_file_group_owner
  ON managed_file(
    tenant_id, owner_enterprise_id, owner_connector_id,
    owner_conversation_id, status, updated_at
  );

CREATE TABLE managed_file_version (
  id TEXT PRIMARY KEY,
  file_id TEXT NOT NULL REFERENCES managed_file(id) ON DELETE CASCADE,
  version_number BIGINT NOT NULL CHECK (version_number > 0),
  parent_version_id TEXT REFERENCES managed_file_version(id),
  base_version_id TEXT REFERENCES managed_file_version(id),
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
    CHECK (source_kind IN ('MESSAGE_ATTACHMENT', 'AGENT_GENERATED', 'AGENT_EDITED', 'CONFLICT')),
  source_reference_digest TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  content_deleted_at TEXT,
  UNIQUE(file_id, version_number),
  CHECK (
    (status IN ('CONTENT_UNAVAILABLE', 'DELETED') AND content_deleted_at IS NOT NULL)
    OR status IN ('AVAILABLE', 'CONFLICT')
  )
);

CREATE INDEX idx_managed_file_version_file
  ON managed_file_version(file_id, version_number);
CREATE INDEX idx_managed_file_version_status
  ON managed_file_version(status, created_at);

CREATE TABLE task_workspace_file (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id) ON DELETE CASCADE,
  file_id TEXT NOT NULL REFERENCES managed_file(id),
  selected_version_id TEXT NOT NULL REFERENCES managed_file_version(id),
  logical_name TEXT NOT NULL CHECK (length(logical_name) BETWEEN 1 AND 255),
  role TEXT NOT NULL CHECK (role IN ('INPUT', 'WORKING', 'OUTPUT', 'CONFLICT')),
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'REMOVED')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  removed_at TEXT,
  UNIQUE(workspace_id, file_id),
  CHECK ((status = 'REMOVED' AND removed_at IS NOT NULL) OR status = 'ACTIVE')
);

CREATE UNIQUE INDEX uq_task_workspace_file_active_name
  ON task_workspace_file(workspace_id, logical_name)
  WHERE status = 'ACTIVE';
CREATE INDEX idx_task_workspace_file_version
  ON task_workspace_file(selected_version_id);

CREATE TABLE file_external_reference (
  id TEXT PRIMARY KEY,
  file_id TEXT NOT NULL REFERENCES managed_file(id) ON DELETE CASCADE,
  version_id TEXT NOT NULL REFERENCES managed_file_version(id) ON DELETE CASCADE,
  provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
  source_type TEXT NOT NULL CHECK (length(source_type) BETWEEN 1 AND 64),
  source_id TEXT NOT NULL CHECK (length(source_id) BETWEEN 1 AND 512),
  source_digest TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(provider, source_type, source_id, version_id)
);

CREATE INDEX idx_file_external_reference_file
  ON file_external_reference(file_id, version_id);

CREATE TABLE agent_job_file_snapshot (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id),
  tenant_id TEXT NOT NULL,
  principal_user_id TEXT NOT NULL,
  business_application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  retention_period TEXT NOT NULL
    CHECK (retention_period IN ('DAY', 'WEEK', 'MONTH')),
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version = 1),
  manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
  created_at TEXT NOT NULL
);

CREATE INDEX idx_agent_job_file_snapshot_workspace
  ON agent_job_file_snapshot(workspace_id, created_at);

CREATE TABLE agent_job_file_request (
  job_id TEXT PRIMARY KEY REFERENCES agent_job(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id),
  tenant_id TEXT NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 128),
  principal_user_id TEXT NOT NULL,
  business_application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  retention_period TEXT NOT NULL
    CHECK (retention_period IN ('DAY', 'WEEK', 'MONTH')),
  explicit_references_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'FINALIZED')),
  created_at TEXT NOT NULL,
  finalized_at TEXT
);

CREATE INDEX idx_agent_job_file_request_pending
  ON agent_job_file_request(status, created_at, job_id);

CREATE TABLE agent_job_file_snapshot_item (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES agent_job_file_snapshot(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
  file_id TEXT NOT NULL REFERENCES managed_file(id),
  version_id TEXT NOT NULL REFERENCES managed_file_version(id),
  display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 255),
  source_kind TEXT NOT NULL
    CHECK (source_kind IN ('CURRENT_MESSAGE', 'EXPLICIT_REFERENCE', 'WORKSPACE', 'CONFLICT')),
  allowed_actions_json TEXT NOT NULL DEFAULT '[]',
  auto_materialize INTEGER NOT NULL DEFAULT 0 CHECK (auto_materialize IN (0, 1)),
  conflict_candidate INTEGER NOT NULL DEFAULT 0 CHECK (conflict_candidate IN (0, 1)),
  created_at TEXT NOT NULL,
  UNIQUE(snapshot_id, ordinal),
  UNIQUE(snapshot_id, file_id, version_id)
);

CREATE INDEX idx_agent_job_file_snapshot_item_version
  ON agent_job_file_snapshot_item(version_id);

CREATE TABLE file_materialization_transfer (
  id TEXT PRIMARY KEY,
  transfer_id TEXT NOT NULL UNIQUE CHECK (length(transfer_id) BETWEEN 1 AND 128),
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id),
  file_id TEXT NOT NULL REFERENCES managed_file(id),
  version_id TEXT NOT NULL REFERENCES managed_file_version(id),
  sandbox_entry_handle TEXT NOT NULL CHECK (length(sandbox_entry_handle) BETWEEN 1 AND 128),
  relative_path TEXT NOT NULL CHECK (length(relative_path) BETWEEN 1 AND 512),
  expected_size_bytes BIGINT NOT NULL CHECK (expected_size_bytes >= 0),
  expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
  status TEXT NOT NULL DEFAULT 'READY'
    CHECK (status IN ('READY', 'CONSUMED', 'EXPIRED')),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  consumed_at TEXT
);

CREATE INDEX idx_file_materialization_transfer_expiry
  ON file_materialization_transfer(status, expires_at, id);

CREATE TABLE file_commit_intent (
  id TEXT PRIMARY KEY,
  commit_id TEXT NOT NULL UNIQUE CHECK (length(commit_id) BETWEEN 1 AND 128),
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id),
  target_file_id TEXT REFERENCES managed_file(id),
  base_version_id TEXT REFERENCES managed_file_version(id),
  sandbox_entry_handle TEXT NOT NULL CHECK (length(sandbox_entry_handle) BETWEEN 1 AND 128),
  display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 255),
  user_intent TEXT NOT NULL CHECK (user_intent IN ('MODIFY', 'GENERATE', 'SAVE')),
  delivery_mode TEXT NOT NULL CHECK (delivery_mode IN ('DEFAULT', 'WORKSPACE_ONLY')),
  metadata_hash TEXT NOT NULL CHECK (length(metadata_hash) = 64),
  content_sha256 TEXT,
  size_bytes BIGINT,
  status TEXT NOT NULL DEFAULT 'INTENT'
    CHECK (status IN (
      'INTENT', 'UPLOADING', 'COMMITTED', 'CONFLICT', 'REJECTED', 'EXPIRED'
    )),
  result_version_id TEXT REFERENCES managed_file_version(id),
  conflict_candidate_version_id TEXT REFERENCES managed_file_version(id),
  failure_code TEXT NOT NULL DEFAULT '',
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT,
  CHECK (
    (target_file_id IS NULL AND base_version_id IS NULL)
    OR (target_file_id IS NOT NULL AND base_version_id IS NOT NULL)
  ),
  CHECK (content_sha256 IS NULL OR length(content_sha256) = 64),
  CHECK (size_bytes IS NULL OR size_bytes >= 0)
);

CREATE INDEX idx_file_commit_intent_job
  ON file_commit_intent(job_id, created_at);
CREATE INDEX idx_file_commit_intent_expiry
  ON file_commit_intent(status, expires_at, id);

CREATE TABLE file_object_staging (
  id TEXT PRIMARY KEY,
  commit_intent_id TEXT NOT NULL UNIQUE
    REFERENCES file_commit_intent(id) ON DELETE CASCADE,
  object_key TEXT NOT NULL UNIQUE CHECK (length(object_key) BETWEEN 1 AND 1024),
  status TEXT NOT NULL DEFAULT 'UPLOADING'
    CHECK (status IN (
      'UPLOADING', 'COMPLETE', 'PUBLISHED', 'CLEANUP_PENDING', 'DELETED'
    )),
  size_bytes BIGINT NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
  content_sha256 TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  failure_code TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  deleted_at TEXT,
  CHECK (content_sha256 IS NULL OR length(content_sha256) = 64)
);

CREATE INDEX idx_file_object_staging_cleanup
  ON file_object_staging(status, updated_at, id);

CREATE TABLE file_conflict_candidate (
  id TEXT PRIMARY KEY,
  commit_intent_id TEXT NOT NULL UNIQUE REFERENCES file_commit_intent(id),
  file_id TEXT NOT NULL REFERENCES managed_file(id),
  base_version_id TEXT NOT NULL REFERENCES managed_file_version(id),
  current_version_id TEXT NOT NULL REFERENCES managed_file_version(id),
  candidate_version_id TEXT NOT NULL UNIQUE REFERENCES managed_file_version(id),
  status TEXT NOT NULL DEFAULT 'OPEN'
    CHECK (status IN ('OPEN', 'RESOLVED', 'EXPIRED')),
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE INDEX idx_file_conflict_candidate_open
  ON file_conflict_candidate(file_id, status, created_at);

CREATE TABLE file_retention_fact (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES managed_file_version(id) ON DELETE CASCADE,
  reason TEXT NOT NULL
    CHECK (reason IN ('MESSAGE_ATTACHMENT', 'USER_SAVED', 'DELIVERED')),
  source_id TEXT NOT NULL CHECK (length(source_id) BETWEEN 1 AND 256),
  retention_days INTEGER NOT NULL DEFAULT 360 CHECK (retention_days > 0),
  starts_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(version_id, reason, source_id)
);

CREATE INDEX idx_file_retention_fact_expiry
  ON file_retention_fact(expires_at, version_id);

CREATE TABLE file_cleanup_fact (
  id TEXT PRIMARY KEY,
  resource_type TEXT NOT NULL
    CHECK (resource_type IN (
      'WORKSPACE', 'FILE_VERSION', 'STAGING_OBJECT', 'ATTACHMENT_CONTENT'
    )),
  resource_id TEXT NOT NULL CHECK (length(resource_id) BETWEEN 1 AND 128),
  reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 128),
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'CLAIMED', 'RETRY', 'COMPLETED', 'DEAD')),
  due_at TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  failure_code TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(resource_type, resource_id, reason)
);

CREATE INDEX idx_file_cleanup_fact_due
  ON file_cleanup_fact(status, next_attempt_at, due_at, id);

CREATE TABLE file_domain_outbox (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 128),
  aggregate_type TEXT NOT NULL CHECK (length(aggregate_type) BETWEEN 1 AND 64),
  aggregate_id TEXT NOT NULL CHECK (length(aggregate_id) BETWEEN 1 AND 128),
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'PUBLISHED', 'FAILED')),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  published_at TEXT,
  failure_code TEXT NOT NULL DEFAULT '',
  UNIQUE(event_type, aggregate_id)
);

CREATE INDEX idx_file_domain_outbox_pending
  ON file_domain_outbox(status, created_at, id);

ALTER TABLE message_attachment
  ADD COLUMN retention_days INTEGER NOT NULL DEFAULT 360
  CHECK (retention_days > 0);

ALTER TABLE message_attachment
  ADD COLUMN managed_file_id TEXT;

ALTER TABLE message_attachment
  ADD COLUMN managed_file_version_id TEXT;

ALTER TABLE message_attachment
  ADD COLUMN content_deleted_at TEXT;

ALTER TABLE delivery_outbox
  ADD COLUMN delivery_kind TEXT NOT NULL DEFAULT 'RESULT'
  CHECK (delivery_kind IN ('RESULT', 'FAILURE', 'FILE_VERSION'));

ALTER TABLE delivery_outbox
  ADD COLUMN file_id TEXT NOT NULL DEFAULT '';

ALTER TABLE delivery_outbox
  ADD COLUMN file_version_id TEXT NOT NULL DEFAULT '';

ALTER TABLE delivery_outbox
  ADD COLUMN file_content_sha256 TEXT NOT NULL DEFAULT '';

ALTER TABLE delivery_outbox
  ADD COLUMN principal_user_id TEXT NOT NULL DEFAULT '';

ALTER TABLE delivery_outbox
  ADD COLUMN session_id TEXT NOT NULL DEFAULT '';

ALTER TABLE delivery_outbox
  ADD COLUMN agent_publication_id TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX uq_delivery_outbox_file_version
  ON delivery_outbox(job_id, file_version_id)
  WHERE file_version_id <> '';

ALTER TABLE delivery_attempt
  ADD COLUMN file_id TEXT NOT NULL DEFAULT '';

ALTER TABLE delivery_attempt
  ADD COLUMN file_version_id TEXT NOT NULL DEFAULT '';

-- sqlite-only
UPDATE message_attachment
   SET expires_at = datetime(created_at, '+360 days')
 WHERE expires_at IS NULL;

-- postgres-only
UPDATE message_attachment
   SET expires_at = (created_at::timestamptz + interval '360 days')::text
 WHERE expires_at IS NULL;

-- sqlite-only
INSERT INTO file_cleanup_fact
  (id, resource_type, resource_id, reason, status, due_at,
   attempt_count, next_attempt_at, created_at, updated_at)
SELECT 'cleanup_attachment_' || id, 'ATTACHMENT_CONTENT', id,
       'RETENTION_EXPIRED', 'PENDING', expires_at, 0, expires_at,
       datetime('now'), datetime('now')
  FROM message_attachment
 WHERE expires_at IS NOT NULL
   AND datetime(expires_at) <= datetime('now');

-- postgres-only
INSERT INTO file_cleanup_fact
  (id, resource_type, resource_id, reason, status, due_at,
   attempt_count, next_attempt_at, created_at, updated_at)
SELECT 'cleanup_attachment_' || id, 'ATTACHMENT_CONTENT', id,
       'RETENTION_EXPIRED', 'PENDING', expires_at, 0, expires_at,
       now()::text, now()::text
  FROM message_attachment
 WHERE expires_at IS NOT NULL
   AND expires_at::timestamptz <= now();

CREATE INDEX idx_message_attachment_retention_due
  ON message_attachment(status, expires_at, id);
CREATE INDEX idx_message_attachment_managed_version
  ON message_attachment(managed_file_version_id);

CREATE TABLE message_attachment_file_binding (
  attachment_id TEXT PRIMARY KEY REFERENCES message_attachment(id) ON DELETE CASCADE,
  file_id TEXT NOT NULL REFERENCES managed_file(id),
  version_id TEXT NOT NULL REFERENCES managed_file_version(id),
  retention_expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(file_id, version_id, attachment_id)
);

-- postgres-only
-- PostgreSQL ownership comments are canonical schema documentation. SQLite
-- skips these statements while migration validation still verifies coverage.
COMMENT ON TABLE task_workspace IS '会话内任务文件工作区及其自然周期生命周期';
COMMENT ON COLUMN task_workspace.id IS '任务文件工作区域 task_workspace 的 id 字段';
COMMENT ON COLUMN task_workspace.tenant_id IS '任务文件工作区域 task_workspace 的 tenant_id 字段';
COMMENT ON COLUMN task_workspace.session_id IS '任务文件工作区域 task_workspace 的 session_id 字段';
COMMENT ON COLUMN task_workspace.owner_type IS '任务文件工作区域 task_workspace 的 owner_type 字段';
COMMENT ON COLUMN task_workspace.owner_user_id IS '任务文件工作区域 task_workspace 的 owner_user_id 字段';
COMMENT ON COLUMN task_workspace.owner_enterprise_id IS '任务文件工作区域 task_workspace 的 owner_enterprise_id 字段';
COMMENT ON COLUMN task_workspace.owner_connector_id IS '任务文件工作区域 task_workspace 的 owner_connector_id 字段';
COMMENT ON COLUMN task_workspace.owner_conversation_id IS '任务文件工作区域 task_workspace 的 owner_conversation_id 字段';
COMMENT ON COLUMN task_workspace.business_application_publication_id IS '任务文件工作区域 task_workspace 的 business_application_publication_id 字段';
COMMENT ON COLUMN task_workspace.retention_period IS '任务文件工作区域 task_workspace 的 retention_period 字段';
COMMENT ON COLUMN task_workspace.retention_timezone IS '任务文件工作区域 task_workspace 的 retention_timezone 字段';
COMMENT ON COLUMN task_workspace.status IS '任务文件工作区域 task_workspace 的 status 字段';
COMMENT ON COLUMN task_workspace.expires_at IS '任务文件工作区域 task_workspace 的 expires_at 字段';
COMMENT ON COLUMN task_workspace.created_by IS '任务文件工作区域 task_workspace 的 created_by 字段';
COMMENT ON COLUMN task_workspace.created_at IS '任务文件工作区域 task_workspace 的 created_at 字段';
COMMENT ON COLUMN task_workspace.updated_at IS '任务文件工作区域 task_workspace 的 updated_at 字段';
COMMENT ON COLUMN task_workspace.closed_at IS '任务文件工作区域 task_workspace 的 closed_at 字段';
COMMENT ON TABLE managed_file IS '稳定文件身份及其当前版本指针';
COMMENT ON COLUMN managed_file.id IS '任务文件工作区域 managed_file 的 id 字段';
COMMENT ON COLUMN managed_file.tenant_id IS '任务文件工作区域 managed_file 的 tenant_id 字段';
COMMENT ON COLUMN managed_file.owner_type IS '任务文件工作区域 managed_file 的 owner_type 字段';
COMMENT ON COLUMN managed_file.owner_user_id IS '任务文件工作区域 managed_file 的 owner_user_id 字段';
COMMENT ON COLUMN managed_file.owner_enterprise_id IS '任务文件工作区域 managed_file 的 owner_enterprise_id 字段';
COMMENT ON COLUMN managed_file.owner_connector_id IS '任务文件工作区域 managed_file 的 owner_connector_id 字段';
COMMENT ON COLUMN managed_file.owner_conversation_id IS '任务文件工作区域 managed_file 的 owner_conversation_id 字段';
COMMENT ON COLUMN managed_file.display_name IS '任务文件工作区域 managed_file 的 display_name 字段';
COMMENT ON COLUMN managed_file.current_version_id IS '任务文件工作区域 managed_file 的 current_version_id 字段';
COMMENT ON COLUMN managed_file.status IS '任务文件工作区域 managed_file 的 status 字段';
COMMENT ON COLUMN managed_file.created_by IS '任务文件工作区域 managed_file 的 created_by 字段';
COMMENT ON COLUMN managed_file.created_at IS '任务文件工作区域 managed_file 的 created_at 字段';
COMMENT ON COLUMN managed_file.updated_at IS '任务文件工作区域 managed_file 的 updated_at 字段';
COMMENT ON COLUMN managed_file.deleted_at IS '任务文件工作区域 managed_file 的 deleted_at 字段';
COMMENT ON TABLE managed_file_version IS '文件不可变版本和内部对象引用';
COMMENT ON COLUMN managed_file_version.id IS '任务文件工作区域 managed_file_version 的 id 字段';
COMMENT ON COLUMN managed_file_version.file_id IS '任务文件工作区域 managed_file_version 的 file_id 字段';
COMMENT ON COLUMN managed_file_version.version_number IS '任务文件工作区域 managed_file_version 的 version_number 字段';
COMMENT ON COLUMN managed_file_version.parent_version_id IS '任务文件工作区域 managed_file_version 的 parent_version_id 字段';
COMMENT ON COLUMN managed_file_version.base_version_id IS '任务文件工作区域 managed_file_version 的 base_version_id 字段';
COMMENT ON COLUMN managed_file_version.version_kind IS '任务文件工作区域 managed_file_version 的 version_kind 字段';
COMMENT ON COLUMN managed_file_version.status IS '任务文件工作区域 managed_file_version 的 status 字段';
COMMENT ON COLUMN managed_file_version.media_type IS '任务文件工作区域 managed_file_version 的 media_type 字段';
COMMENT ON COLUMN managed_file_version.encoding IS '任务文件工作区域 managed_file_version 的 encoding 字段';
COMMENT ON COLUMN managed_file_version.size_bytes IS '任务文件工作区域 managed_file_version 的 size_bytes 字段';
COMMENT ON COLUMN managed_file_version.content_sha256 IS '任务文件工作区域 managed_file_version 的 content_sha256 字段';
COMMENT ON COLUMN managed_file_version.object_key IS '任务文件工作区域 managed_file_version 的 object_key 字段';
COMMENT ON COLUMN managed_file_version.source_kind IS '任务文件工作区域 managed_file_version 的 source_kind 字段';
COMMENT ON COLUMN managed_file_version.source_reference_digest IS '任务文件工作区域 managed_file_version 的 source_reference_digest 字段';
COMMENT ON COLUMN managed_file_version.created_by IS '任务文件工作区域 managed_file_version 的 created_by 字段';
COMMENT ON COLUMN managed_file_version.created_at IS '任务文件工作区域 managed_file_version 的 created_at 字段';
COMMENT ON COLUMN managed_file_version.content_deleted_at IS '任务文件工作区域 managed_file_version 的 content_deleted_at 字段';
COMMENT ON TABLE task_workspace_file IS '任务工作区到文件精确版本的逻辑引用';
COMMENT ON COLUMN task_workspace_file.id IS '任务文件工作区域 task_workspace_file 的 id 字段';
COMMENT ON COLUMN task_workspace_file.workspace_id IS '任务文件工作区域 task_workspace_file 的 workspace_id 字段';
COMMENT ON COLUMN task_workspace_file.file_id IS '任务文件工作区域 task_workspace_file 的 file_id 字段';
COMMENT ON COLUMN task_workspace_file.selected_version_id IS '任务文件工作区域 task_workspace_file 的 selected_version_id 字段';
COMMENT ON COLUMN task_workspace_file.logical_name IS '任务文件工作区域 task_workspace_file 的 logical_name 字段';
COMMENT ON COLUMN task_workspace_file.role IS '任务文件工作区域 task_workspace_file 的 role 字段';
COMMENT ON COLUMN task_workspace_file.status IS '任务文件工作区域 task_workspace_file 的 status 字段';
COMMENT ON COLUMN task_workspace_file.created_at IS '任务文件工作区域 task_workspace_file 的 created_at 字段';
COMMENT ON COLUMN task_workspace_file.updated_at IS '任务文件工作区域 task_workspace_file 的 updated_at 字段';
COMMENT ON COLUMN task_workspace_file.removed_at IS '任务文件工作区域 task_workspace_file 的 removed_at 字段';
COMMENT ON TABLE file_external_reference IS '内部文件版本与外部来源的血缘关联';
COMMENT ON COLUMN file_external_reference.id IS '任务文件工作区域 file_external_reference 的 id 字段';
COMMENT ON COLUMN file_external_reference.file_id IS '任务文件工作区域 file_external_reference 的 file_id 字段';
COMMENT ON COLUMN file_external_reference.version_id IS '任务文件工作区域 file_external_reference 的 version_id 字段';
COMMENT ON COLUMN file_external_reference.provider IS '任务文件工作区域 file_external_reference 的 provider 字段';
COMMENT ON COLUMN file_external_reference.source_type IS '任务文件工作区域 file_external_reference 的 source_type 字段';
COMMENT ON COLUMN file_external_reference.source_id IS '任务文件工作区域 file_external_reference 的 source_id 字段';
COMMENT ON COLUMN file_external_reference.source_digest IS '任务文件工作区域 file_external_reference 的 source_digest 字段';
COMMENT ON COLUMN file_external_reference.created_at IS '任务文件工作区域 file_external_reference 的 created_at 字段';
COMMENT ON TABLE agent_job_file_snapshot IS 'Agent Job 冻结文件清单头记录';
COMMENT ON COLUMN agent_job_file_snapshot.id IS '任务文件工作区域 agent_job_file_snapshot 的 id 字段';
COMMENT ON COLUMN agent_job_file_snapshot.job_id IS '任务文件工作区域 agent_job_file_snapshot 的 job_id 字段';
COMMENT ON COLUMN agent_job_file_snapshot.workspace_id IS '任务文件工作区域 agent_job_file_snapshot 的 workspace_id 字段';
COMMENT ON COLUMN agent_job_file_snapshot.tenant_id IS '任务文件工作区域 agent_job_file_snapshot 的 tenant_id 字段';
COMMENT ON COLUMN agent_job_file_snapshot.principal_user_id IS '任务文件工作区域 agent_job_file_snapshot 的 principal_user_id 字段';
COMMENT ON COLUMN agent_job_file_snapshot.business_application_publication_id IS '任务文件工作区域 agent_job_file_snapshot 的 business_application_publication_id 字段';
COMMENT ON COLUMN agent_job_file_snapshot.retention_period IS '任务文件工作区域 agent_job_file_snapshot 的 retention_period 字段';
COMMENT ON COLUMN agent_job_file_snapshot.schema_version IS '任务文件工作区域 agent_job_file_snapshot 的 schema_version 字段';
COMMENT ON COLUMN agent_job_file_snapshot.manifest_hash IS '任务文件工作区域 agent_job_file_snapshot 的 manifest_hash 字段';
COMMENT ON COLUMN agent_job_file_snapshot.created_at IS '任务文件工作区域 agent_job_file_snapshot 的 created_at 字段';
COMMENT ON TABLE agent_job_file_request IS '异步附件导入完成前的Job文件清单冻结请求';
COMMENT ON COLUMN agent_job_file_request.job_id IS '任务文件清单请求关联的Job';
COMMENT ON COLUMN agent_job_file_request.workspace_id IS '任务文件清单请求关联的工作区';
COMMENT ON COLUMN agent_job_file_request.tenant_id IS '任务文件清单请求的租户边界';
COMMENT ON COLUMN agent_job_file_request.principal_user_id IS '当前消息实际发送人的内部用户身份';
COMMENT ON COLUMN agent_job_file_request.business_application_publication_id IS '冻结的业务应用发布版本';
COMMENT ON COLUMN agent_job_file_request.retention_period IS '冻结的工作区自然周期保留策略';
COMMENT ON COLUMN agent_job_file_request.explicit_references_json IS '用户显式引用的有界File和Version身份';
COMMENT ON COLUMN agent_job_file_request.status IS '文件清单冻结请求状态';
COMMENT ON COLUMN agent_job_file_request.created_at IS '文件清单冻结请求创建时间';
COMMENT ON COLUMN agent_job_file_request.finalized_at IS '文件清单完成不可变冻结的时间';
COMMENT ON TABLE agent_job_file_snapshot_item IS 'Agent Job 冻结文件清单精确版本项';
COMMENT ON COLUMN agent_job_file_snapshot_item.id IS '任务文件工作区域 agent_job_file_snapshot_item 的 id 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.snapshot_id IS '任务文件工作区域 agent_job_file_snapshot_item 的 snapshot_id 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.ordinal IS '任务文件工作区域 agent_job_file_snapshot_item 的 ordinal 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.file_id IS '任务文件工作区域 agent_job_file_snapshot_item 的 file_id 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.version_id IS '任务文件工作区域 agent_job_file_snapshot_item 的 version_id 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.display_name IS '任务文件工作区域 agent_job_file_snapshot_item 的 display_name 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.source_kind IS '任务文件工作区域 agent_job_file_snapshot_item 的 source_kind 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.allowed_actions_json IS '任务文件工作区域 agent_job_file_snapshot_item 的 allowed_actions_json 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.auto_materialize IS '任务文件工作区域 agent_job_file_snapshot_item 的 auto_materialize 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.conflict_candidate IS '任务文件工作区域 agent_job_file_snapshot_item 的 conflict_candidate 字段';
COMMENT ON COLUMN agent_job_file_snapshot_item.created_at IS '任务文件工作区域 agent_job_file_snapshot_item 的 created_at 字段';
COMMENT ON TABLE file_materialization_transfer IS '绑定 Job、Principal 与精确版本的一次性文件物化传输';
COMMENT ON COLUMN file_materialization_transfer.id IS '物化传输内部标识';
COMMENT ON COLUMN file_materialization_transfer.transfer_id IS '对 Runtime 暴露的不透明传输标识';
COMMENT ON COLUMN file_materialization_transfer.job_id IS '传输绑定的 Agent Job';
COMMENT ON COLUMN file_materialization_transfer.workspace_id IS '传输绑定的任务工作区';
COMMENT ON COLUMN file_materialization_transfer.file_id IS '传输绑定的逻辑文件';
COMMENT ON COLUMN file_materialization_transfer.version_id IS '传输绑定的精确文件版本';
COMMENT ON COLUMN file_materialization_transfer.sandbox_entry_handle IS 'Runtime 沙箱登记句柄';
COMMENT ON COLUMN file_materialization_transfer.relative_path IS '受管沙箱相对路径';
COMMENT ON COLUMN file_materialization_transfer.expected_size_bytes IS '预期字节数';
COMMENT ON COLUMN file_materialization_transfer.expected_sha256 IS '预期内容摘要';
COMMENT ON COLUMN file_materialization_transfer.status IS '一次性传输状态';
COMMENT ON COLUMN file_materialization_transfer.expires_at IS '传输意图过期时间';
COMMENT ON COLUMN file_materialization_transfer.created_at IS '传输意图创建时间';
COMMENT ON COLUMN file_materialization_transfer.consumed_at IS '传输开始消费时间';
COMMENT ON TABLE file_commit_intent IS '受治理文件提交意图和幂等结果';
COMMENT ON COLUMN file_commit_intent.id IS '任务文件工作区域 file_commit_intent 的 id 字段';
COMMENT ON COLUMN file_commit_intent.commit_id IS '任务文件工作区域 file_commit_intent 的 commit_id 字段';
COMMENT ON COLUMN file_commit_intent.job_id IS '任务文件工作区域 file_commit_intent 的 job_id 字段';
COMMENT ON COLUMN file_commit_intent.workspace_id IS '任务文件工作区域 file_commit_intent 的 workspace_id 字段';
COMMENT ON COLUMN file_commit_intent.target_file_id IS '任务文件工作区域 file_commit_intent 的 target_file_id 字段';
COMMENT ON COLUMN file_commit_intent.base_version_id IS '任务文件工作区域 file_commit_intent 的 base_version_id 字段';
COMMENT ON COLUMN file_commit_intent.sandbox_entry_handle IS '任务文件工作区域 file_commit_intent 的 sandbox_entry_handle 字段';
COMMENT ON COLUMN file_commit_intent.display_name IS '任务文件工作区域 file_commit_intent 的 display_name 字段';
COMMENT ON COLUMN file_commit_intent.user_intent IS '任务文件工作区域 file_commit_intent 的 user_intent 字段';
COMMENT ON COLUMN file_commit_intent.delivery_mode IS '任务文件工作区域 file_commit_intent 的 delivery_mode 字段';
COMMENT ON COLUMN file_commit_intent.metadata_hash IS '任务文件工作区域 file_commit_intent 的 metadata_hash 字段';
COMMENT ON COLUMN file_commit_intent.content_sha256 IS '任务文件工作区域 file_commit_intent 的 content_sha256 字段';
COMMENT ON COLUMN file_commit_intent.size_bytes IS '任务文件工作区域 file_commit_intent 的 size_bytes 字段';
COMMENT ON COLUMN file_commit_intent.status IS '任务文件工作区域 file_commit_intent 的 status 字段';
COMMENT ON COLUMN file_commit_intent.result_version_id IS '任务文件工作区域 file_commit_intent 的 result_version_id 字段';
COMMENT ON COLUMN file_commit_intent.conflict_candidate_version_id IS '任务文件工作区域 file_commit_intent 的 conflict_candidate_version_id 字段';
COMMENT ON COLUMN file_commit_intent.failure_code IS '任务文件工作区域 file_commit_intent 的 failure_code 字段';
COMMENT ON COLUMN file_commit_intent.expires_at IS '任务文件工作区域 file_commit_intent 的 expires_at 字段';
COMMENT ON COLUMN file_commit_intent.created_at IS '任务文件工作区域 file_commit_intent 的 created_at 字段';
COMMENT ON COLUMN file_commit_intent.updated_at IS '任务文件工作区域 file_commit_intent 的 updated_at 字段';
COMMENT ON COLUMN file_commit_intent.finished_at IS '任务文件工作区域 file_commit_intent 的 finished_at 字段';
COMMENT ON TABLE file_object_staging IS '文件流式上传暂存对象状态';
COMMENT ON COLUMN file_object_staging.id IS '任务文件工作区域 file_object_staging 的 id 字段';
COMMENT ON COLUMN file_object_staging.commit_intent_id IS '任务文件工作区域 file_object_staging 的 commit_intent_id 字段';
COMMENT ON COLUMN file_object_staging.object_key IS '任务文件工作区域 file_object_staging 的 object_key 字段';
COMMENT ON COLUMN file_object_staging.status IS '任务文件工作区域 file_object_staging 的 status 字段';
COMMENT ON COLUMN file_object_staging.size_bytes IS '任务文件工作区域 file_object_staging 的 size_bytes 字段';
COMMENT ON COLUMN file_object_staging.content_sha256 IS '任务文件工作区域 file_object_staging 的 content_sha256 字段';
COMMENT ON COLUMN file_object_staging.retry_count IS '任务文件工作区域 file_object_staging 的 retry_count 字段';
COMMENT ON COLUMN file_object_staging.failure_code IS '任务文件工作区域 file_object_staging 的 failure_code 字段';
COMMENT ON COLUMN file_object_staging.created_at IS '任务文件工作区域 file_object_staging 的 created_at 字段';
COMMENT ON COLUMN file_object_staging.updated_at IS '任务文件工作区域 file_object_staging 的 updated_at 字段';
COMMENT ON COLUMN file_object_staging.completed_at IS '任务文件工作区域 file_object_staging 的 completed_at 字段';
COMMENT ON COLUMN file_object_staging.deleted_at IS '任务文件工作区域 file_object_staging 的 deleted_at 字段';
COMMENT ON TABLE file_conflict_candidate IS '并发提交产生的待显式处理冲突候选';
COMMENT ON COLUMN file_conflict_candidate.id IS '任务文件工作区域 file_conflict_candidate 的 id 字段';
COMMENT ON COLUMN file_conflict_candidate.commit_intent_id IS '任务文件工作区域 file_conflict_candidate 的 commit_intent_id 字段';
COMMENT ON COLUMN file_conflict_candidate.file_id IS '任务文件工作区域 file_conflict_candidate 的 file_id 字段';
COMMENT ON COLUMN file_conflict_candidate.base_version_id IS '任务文件工作区域 file_conflict_candidate 的 base_version_id 字段';
COMMENT ON COLUMN file_conflict_candidate.current_version_id IS '任务文件工作区域 file_conflict_candidate 的 current_version_id 字段';
COMMENT ON COLUMN file_conflict_candidate.candidate_version_id IS '任务文件工作区域 file_conflict_candidate 的 candidate_version_id 字段';
COMMENT ON COLUMN file_conflict_candidate.status IS '任务文件工作区域 file_conflict_candidate 的 status 字段';
COMMENT ON COLUMN file_conflict_candidate.created_at IS '任务文件工作区域 file_conflict_candidate 的 created_at 字段';
COMMENT ON COLUMN file_conflict_candidate.resolved_at IS '任务文件工作区域 file_conflict_candidate 的 resolved_at 字段';
COMMENT ON TABLE file_retention_fact IS '精确文件版本的独立保留事实';
COMMENT ON COLUMN file_retention_fact.id IS '任务文件工作区域 file_retention_fact 的 id 字段';
COMMENT ON COLUMN file_retention_fact.version_id IS '任务文件工作区域 file_retention_fact 的 version_id 字段';
COMMENT ON COLUMN file_retention_fact.reason IS '任务文件工作区域 file_retention_fact 的 reason 字段';
COMMENT ON COLUMN file_retention_fact.source_id IS '任务文件工作区域 file_retention_fact 的 source_id 字段';
COMMENT ON COLUMN file_retention_fact.retention_days IS '任务文件工作区域 file_retention_fact 的 retention_days 字段';
COMMENT ON COLUMN file_retention_fact.starts_at IS '任务文件工作区域 file_retention_fact 的 starts_at 字段';
COMMENT ON COLUMN file_retention_fact.expires_at IS '任务文件工作区域 file_retention_fact 的 expires_at 字段';
COMMENT ON COLUMN file_retention_fact.created_at IS '任务文件工作区域 file_retention_fact 的 created_at 字段';
COMMENT ON TABLE file_cleanup_fact IS '文件和工作区内容的可重试清理事实';
COMMENT ON COLUMN file_cleanup_fact.id IS '任务文件工作区域 file_cleanup_fact 的 id 字段';
COMMENT ON COLUMN file_cleanup_fact.resource_type IS '任务文件工作区域 file_cleanup_fact 的 resource_type 字段';
COMMENT ON COLUMN file_cleanup_fact.resource_id IS '任务文件工作区域 file_cleanup_fact 的 resource_id 字段';
COMMENT ON COLUMN file_cleanup_fact.reason IS '任务文件工作区域 file_cleanup_fact 的 reason 字段';
COMMENT ON COLUMN file_cleanup_fact.status IS '任务文件工作区域 file_cleanup_fact 的 status 字段';
COMMENT ON COLUMN file_cleanup_fact.due_at IS '任务文件工作区域 file_cleanup_fact 的 due_at 字段';
COMMENT ON COLUMN file_cleanup_fact.attempt_count IS '任务文件工作区域 file_cleanup_fact 的 attempt_count 字段';
COMMENT ON COLUMN file_cleanup_fact.next_attempt_at IS '任务文件工作区域 file_cleanup_fact 的 next_attempt_at 字段';
COMMENT ON COLUMN file_cleanup_fact.claimed_by IS '任务文件工作区域 file_cleanup_fact 的 claimed_by 字段';
COMMENT ON COLUMN file_cleanup_fact.claimed_at IS '任务文件工作区域 file_cleanup_fact 的 claimed_at 字段';
COMMENT ON COLUMN file_cleanup_fact.failure_code IS '任务文件工作区域 file_cleanup_fact 的 failure_code 字段';
COMMENT ON COLUMN file_cleanup_fact.created_at IS '任务文件工作区域 file_cleanup_fact 的 created_at 字段';
COMMENT ON COLUMN file_cleanup_fact.updated_at IS '任务文件工作区域 file_cleanup_fact 的 updated_at 字段';
COMMENT ON COLUMN file_cleanup_fact.completed_at IS '任务文件工作区域 file_cleanup_fact 的 completed_at 字段';
COMMENT ON TABLE file_domain_outbox IS '文件版本事务提交与异步发布之间的受控 Outbox';
COMMENT ON COLUMN file_domain_outbox.id IS 'File Outbox 内部标识';
COMMENT ON COLUMN file_domain_outbox.event_type IS '固定文件领域事件类型';
COMMENT ON COLUMN file_domain_outbox.aggregate_type IS '领域聚合类型';
COMMENT ON COLUMN file_domain_outbox.aggregate_id IS '领域聚合标识';
COMMENT ON COLUMN file_domain_outbox.payload_json IS '仅含逻辑标识和内容摘要的安全事件载荷';
COMMENT ON COLUMN file_domain_outbox.status IS 'Outbox 发布状态';
COMMENT ON COLUMN file_domain_outbox.attempt_count IS '发布尝试次数';
COMMENT ON COLUMN file_domain_outbox.created_at IS 'Outbox 创建时间';
COMMENT ON COLUMN file_domain_outbox.updated_at IS 'Outbox 更新时间';
COMMENT ON COLUMN file_domain_outbox.published_at IS 'Outbox 发布完成时间';
COMMENT ON COLUMN file_domain_outbox.failure_code IS '安全失败码';
COMMENT ON TABLE message_attachment_file_binding IS '聊天附件到内部文件精确版本的兼容关联';
COMMENT ON COLUMN message_attachment_file_binding.attachment_id IS '任务文件工作区域 message_attachment_file_binding 的 attachment_id 字段';
COMMENT ON COLUMN message_attachment_file_binding.file_id IS '任务文件工作区域 message_attachment_file_binding 的 file_id 字段';
COMMENT ON COLUMN message_attachment_file_binding.version_id IS '任务文件工作区域 message_attachment_file_binding 的 version_id 字段';
COMMENT ON COLUMN message_attachment_file_binding.retention_expires_at IS '任务文件工作区域 message_attachment_file_binding 的 retention_expires_at 字段';
COMMENT ON COLUMN message_attachment_file_binding.created_at IS '任务文件工作区域 message_attachment_file_binding 的 created_at 字段';
COMMENT ON COLUMN business_application_revision.task_workspace_retention_period IS '任务文件工作区扩展字段 task_workspace_retention_period';
COMMENT ON COLUMN business_application_publication.task_workspace_retention_period IS '任务文件工作区扩展字段 task_workspace_retention_period';
COMMENT ON COLUMN business_application_revision.task_file_features_json IS '发布修订冻结的任务文件功能开关';
COMMENT ON COLUMN business_application_publication.task_file_features_json IS '发布快照冻结的任务文件功能开关';
COMMENT ON COLUMN agent_job.task_workspace_id IS '任务文件工作区扩展字段 task_workspace_id';
COMMENT ON COLUMN message_attachment.retention_days IS '任务文件工作区扩展字段 retention_days';
COMMENT ON COLUMN message_attachment.managed_file_id IS '任务文件工作区扩展字段 managed_file_id';
COMMENT ON COLUMN message_attachment.managed_file_version_id IS '任务文件工作区扩展字段 managed_file_version_id';
COMMENT ON COLUMN message_attachment.content_deleted_at IS '任务文件工作区扩展字段 content_deleted_at';
COMMENT ON COLUMN delivery_outbox.delivery_kind IS '结果、失败通知或精确文件版本交付类型';
COMMENT ON COLUMN delivery_outbox.file_id IS '文件交付冻结的逻辑文件标识';
COMMENT ON COLUMN delivery_outbox.file_version_id IS '文件交付冻结的精确版本标识';
COMMENT ON COLUMN delivery_outbox.file_content_sha256 IS '文件交付冻结的内容摘要';
COMMENT ON COLUMN delivery_outbox.principal_user_id IS '文件交付冻结的实际操作人';
COMMENT ON COLUMN delivery_outbox.session_id IS '文件交付冻结的会话';
COMMENT ON COLUMN delivery_outbox.agent_publication_id IS '文件交付冻结的 Agent Publication';
COMMENT ON COLUMN delivery_attempt.file_id IS '本次交付尝试的逻辑文件';
COMMENT ON COLUMN delivery_attempt.file_version_id IS '本次交付尝试的精确文件版本';
