-- Expand governed task workspaces with immutable catalog revisions, bounded Job
-- working sets, transactional quota reservations, and Manifest v5 audit facts.
-- This migration changes relational facts only. It never reads or writes object
-- storage and never rewrites historical Manifest payloads or hashes.
-- migration: sqlite-foreign-keys-off

ALTER TABLE platform_runtime_config_definition
  ADD COLUMN tenant_compatible INTEGER NOT NULL DEFAULT 0
  CHECK (tenant_compatible IN (0, 1));

ALTER TABLE task_workspace
  ADD COLUMN catalog_revision BIGINT NOT NULL DEFAULT 0
  CHECK (catalog_revision >= 0);

CREATE TABLE task_workspace_catalog_revision (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id) ON DELETE CASCADE,
  revision BIGINT NOT NULL CHECK (revision >= 0),
  created_at TEXT NOT NULL,
  UNIQUE(workspace_id, revision),
  UNIQUE(id, workspace_id)
);

CREATE INDEX idx_task_workspace_catalog_revision_workspace
  ON task_workspace_catalog_revision(workspace_id, revision);

CREATE TABLE task_workspace_catalog_member (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id) ON DELETE CASCADE,
  file_id TEXT NOT NULL REFERENCES managed_file(id),
  version_id TEXT NOT NULL REFERENCES managed_file_version(id),
  logical_name TEXT NOT NULL CHECK (length(logical_name) BETWEEN 1 AND 255),
  format_code TEXT NOT NULL CHECK (format_code IN (
    'TXT', 'LOG', 'MARKDOWN', 'PDF', 'DOCX', 'PPTX', 'XLSX',
    'PNG', 'JPEG', 'WEBP'
  )),
  size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
  source_received_at TEXT,
  version_created_at TEXT NOT NULL,
  readability_status TEXT NOT NULL CHECK (readability_status IN (
    'DIRECT_TEXT', 'PROCESSING', 'AVAILABLE', 'PARTIAL', 'NO_TEXT',
    'FAILED', 'CONTENT_UNAVAILABLE'
  )),
  valid_from_revision BIGINT NOT NULL CHECK (valid_from_revision >= 0),
  valid_to_revision BIGINT CHECK (
    valid_to_revision IS NULL OR valid_to_revision > valid_from_revision
  ),
  created_at TEXT NOT NULL,
  closed_at TEXT,
  FOREIGN KEY (workspace_id, valid_from_revision)
    REFERENCES task_workspace_catalog_revision(workspace_id, revision),
  UNIQUE(workspace_id, file_id, valid_from_revision),
  CHECK (
    (valid_to_revision IS NULL AND closed_at IS NULL)
    OR (valid_to_revision IS NOT NULL AND closed_at IS NOT NULL)
  )
);

CREATE INDEX idx_task_workspace_catalog_member_revision_name
  ON task_workspace_catalog_member(
    workspace_id, valid_from_revision, valid_to_revision, logical_name, file_id
  );

CREATE INDEX idx_task_workspace_catalog_member_source_time
  ON task_workspace_catalog_member(
    workspace_id, source_received_at, logical_name, file_id
  );

CREATE INDEX idx_task_workspace_catalog_member_format
  ON task_workspace_catalog_member(
    workspace_id, format_code, readability_status, logical_name, file_id
  );

INSERT INTO task_workspace_catalog_revision (id, workspace_id, revision, created_at)
SELECT 'workspace_catalog_' || id || '_r0', id, 0, created_at
  FROM task_workspace;

INSERT INTO task_workspace_catalog_member (
  id, workspace_id, file_id, version_id, logical_name, format_code,
  size_bytes, source_received_at, version_created_at, readability_status,
  valid_from_revision, valid_to_revision, created_at, closed_at
)
SELECT
  'workspace_catalog_member_' || wf.id || '_r0',
  wf.workspace_id,
  wf.file_id,
  wf.selected_version_id,
  wf.logical_name,
  version.format_code,
  version.size_bytes,
  (
    SELECT min(attachment.created_at)
      FROM message_attachment attachment
     WHERE attachment.managed_file_version_id = wf.selected_version_id
  ),
  version.created_at,
  CASE
    WHEN version.format_code IN ('TXT', 'LOG', 'MARKDOWN') THEN 'DIRECT_TEXT'
    WHEN EXISTS (
      SELECT 1
        FROM file_representation representation
       WHERE representation.source_version_id = wf.selected_version_id
         AND representation.kind = 'MARKDOWN'
         AND representation.status = 'AVAILABLE'
    ) THEN 'AVAILABLE'
    ELSE 'PROCESSING'
  END,
  0,
  NULL,
  wf.created_at,
  NULL
FROM task_workspace_file wf
JOIN managed_file_version version ON version.id = wf.selected_version_id
WHERE wf.status = 'ACTIVE';

-- SQLite widens the Manifest schema-version check without rebuilding the table.
-- sqlite-only
ALTER TABLE agent_job_file_snapshot
  RENAME COLUMN schema_version TO schema_version_v4;
-- sqlite-only
ALTER TABLE agent_job_file_snapshot
  ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 5
  CHECK (schema_version IN (1, 2, 3, 4, 5));
-- sqlite-only
UPDATE agent_job_file_snapshot SET schema_version = schema_version_v4;
-- sqlite-only
ALTER TABLE agent_job_file_snapshot DROP COLUMN schema_version_v4;

-- PostgreSQL widens the existing named constraint in place.
-- postgres-only
ALTER TABLE agent_job_file_snapshot
  DROP CONSTRAINT agent_job_file_snapshot_schema_version_check;
-- postgres-only
ALTER TABLE agent_job_file_snapshot ALTER COLUMN schema_version SET DEFAULT 5;
-- postgres-only
ALTER TABLE agent_job_file_snapshot
  ADD CONSTRAINT agent_job_file_snapshot_schema_version_check
  CHECK (schema_version IN (1, 2, 3, 4, 5));

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN workspace_catalog_revision_id TEXT
  REFERENCES task_workspace_catalog_revision(id);

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN active_file_limit INTEGER NOT NULL DEFAULT 20
  CHECK (active_file_limit BETWEEN 1 AND 1000);

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN billable_bytes_limit BIGINT NOT NULL DEFAULT 104857600
  CHECK (billable_bytes_limit BETWEEN 1 AND 10737418240);

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN quota_config_revision BIGINT NOT NULL DEFAULT 0
  CHECK (quota_config_revision >= 0);

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN active_file_limit_source TEXT NOT NULL DEFAULT 'legacy-default'
  CHECK (length(active_file_limit_source) BETWEEN 1 AND 128);

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN billable_bytes_limit_source TEXT NOT NULL DEFAULT 'legacy-default'
  CHECK (length(billable_bytes_limit_source) BETWEEN 1 AND 128);

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN job_input_limit INTEGER NOT NULL DEFAULT 40
  CHECK (job_input_limit = 40);

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN sandbox_file_limit INTEGER NOT NULL DEFAULT 64
  CHECK (sandbox_file_limit = 64);

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN sandbox_capacity_bytes BIGINT NOT NULL DEFAULT 234881024
  CHECK (sandbox_capacity_bytes = 234881024);

ALTER TABLE agent_job_file_snapshot
  ADD COLUMN sandbox_limit_version TEXT NOT NULL DEFAULT 'sandbox-v2'
  CHECK (sandbox_limit_version = 'sandbox-v2');

CREATE INDEX idx_agent_job_file_snapshot_catalog_revision
  ON agent_job_file_snapshot(workspace_catalog_revision_id, created_at);

CREATE TABLE agent_job_file_working_set_item (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id) ON DELETE CASCADE,
  snapshot_id TEXT NOT NULL REFERENCES agent_job_file_snapshot(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id),
  workspace_catalog_revision_id TEXT NOT NULL
    REFERENCES task_workspace_catalog_revision(id),
  file_id TEXT NOT NULL REFERENCES managed_file(id),
  version_id TEXT NOT NULL REFERENCES managed_file_version(id),
  representation_id TEXT REFERENCES file_representation(id),
  representation_kind TEXT
    CHECK (representation_kind IS NULL OR representation_kind = 'MARKDOWN'),
  representation_size_bytes BIGINT
    CHECK (representation_size_bytes IS NULL OR representation_size_bytes >= 0),
  representation_sha256 TEXT
    CHECK (representation_sha256 IS NULL OR length(representation_sha256) = 64),
  selection_source TEXT NOT NULL CHECK (selection_source IN (
    'INITIAL_MANIFEST', 'CATALOG_SEARCH'
  )),
  ordinal INTEGER NOT NULL CHECK (ordinal >= 0 AND ordinal < 40),
  created_at TEXT NOT NULL,
  UNIQUE(job_id, file_id, version_id),
  UNIQUE(job_id, ordinal),
  CHECK (
    (representation_id IS NULL
      AND representation_kind IS NULL
      AND representation_size_bytes IS NULL
      AND representation_sha256 IS NULL)
    OR
    (representation_id IS NOT NULL
      AND representation_kind = 'MARKDOWN'
      AND representation_size_bytes IS NOT NULL
      AND representation_sha256 IS NOT NULL)
  )
);

CREATE INDEX idx_agent_job_file_working_set_snapshot
  ON agent_job_file_working_set_item(snapshot_id, ordinal);

CREATE INDEX idx_agent_job_file_working_set_catalog
  ON agent_job_file_working_set_item(
    workspace_catalog_revision_id, file_id, version_id
  );

CREATE TABLE task_workspace_quota_reservation (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 128),
  operation_type TEXT NOT NULL CHECK (operation_type IN (
    'ATTACHMENT_IMPORT', 'FILE_PROCESSING', 'FILE_COMMIT', 'DERIVATIVE_WRITE'
  )),
  operation_id TEXT NOT NULL CHECK (length(operation_id) BETWEEN 1 AND 128),
  logical_file_slots INTEGER NOT NULL DEFAULT 0
    CHECK (logical_file_slots BETWEEN 0 AND 1),
  billable_bytes BIGINT NOT NULL DEFAULT 0 CHECK (billable_bytes >= 0),
  status TEXT NOT NULL DEFAULT 'RESERVED'
    CHECK (status IN ('RESERVED', 'COMMITTED', 'RELEASED', 'EXPIRED')),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finalized_at TEXT,
  UNIQUE(workspace_id, operation_type, operation_id),
  CHECK (
    (status = 'RESERVED' AND finalized_at IS NULL)
    OR (status <> 'RESERVED' AND finalized_at IS NOT NULL)
  )
);

CREATE INDEX idx_task_workspace_quota_reservation_active
  ON task_workspace_quota_reservation(workspace_id, status, expires_at, id);

CREATE INDEX idx_task_workspace_quota_reservation_tenant
  ON task_workspace_quota_reservation(tenant_id, status, expires_at, id);

-- PostgreSQL ownership comments are part of the schema contract.
-- postgres-only
COMMENT ON COLUMN platform_runtime_config_definition.tenant_compatible IS
  '是否允许该代码注册运行配置定义使用tenant作用域';
-- postgres-only
COMMENT ON COLUMN task_workspace.catalog_revision IS
  '工作区当前不可变目录revision序号';
-- postgres-only
COMMENT ON TABLE task_workspace_catalog_revision IS
  '任务工作区不可变目录revision身份';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_revision.id IS '目录revision不透明身份';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_revision.workspace_id IS '目录revision所属任务工作区';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_revision.revision IS '工作区内单调递增目录revision序号';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_revision.created_at IS '目录revision创建时间';
-- postgres-only
COMMENT ON TABLE task_workspace_catalog_member IS
  '按有效revision区间保存的工作区目录成员事实';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.id IS '目录成员事实不透明身份';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.workspace_id IS '目录成员所属任务工作区';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.file_id IS '目录成员精确逻辑文件身份';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.version_id IS '目录成员精确文件版本身份';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.logical_name IS '该revision可见的安全逻辑文件名';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.format_code IS '该revision可见的代码注册文件格式';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.size_bytes IS '精确版本或可发现内容的安全字节数';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.source_received_at IS '原始聊天附件进入平台的UTC时间';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.version_created_at IS '精确文件版本创建UTC时间';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.readability_status IS '目录revision冻结的安全可读状态';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.valid_from_revision IS '成员开始可见的目录revision序号';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.valid_to_revision IS '成员停止可见的目录revision序号';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.created_at IS '目录成员事实创建时间';
-- postgres-only
COMMENT ON COLUMN task_workspace_catalog_member.closed_at IS '目录成员有效区间关闭时间';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.workspace_catalog_revision_id IS
  'Manifest v5冻结的不可变工作区目录revision身份';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.active_file_limit IS 'Job创建时观察到的ACTIVE逻辑文件上限';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.billable_bytes_limit IS 'Job创建时观察到的工作区计费字节上限';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.quota_config_revision IS 'Job创建时观察到的平台运行配置revision';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.active_file_limit_source IS 'ACTIVE文件上限的非敏感配置来源';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.billable_bytes_limit_source IS '计费字节上限的非敏感配置来源';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.job_input_limit IS 'Job输入物化工作集代码上限';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.sandbox_file_limit IS 'Job Sandbox常规文件代码上限';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.sandbox_capacity_bytes IS 'Job Sandbox共享字节代码上限';
-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.sandbox_limit_version IS 'Job Sandbox限制合同版本';
-- postgres-only
COMMENT ON TABLE agent_job_file_working_set_item IS
  'Job初始及运行中追加的精确文件输入工作集事实';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.id IS 'Job文件工作集项不透明身份';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.job_id IS '工作集所属Agent Job';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.snapshot_id IS '工作集所属不可变文件Snapshot';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.workspace_id IS '工作集所属任务工作区';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.workspace_catalog_revision_id IS '选择来源的冻结目录revision';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.file_id IS '工作集精确逻辑文件身份';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.version_id IS '工作集精确文件版本身份';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.representation_id IS '可选精确Markdown表示身份';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.representation_kind IS '可选表示种类且仅允许Markdown';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.representation_size_bytes IS '冻结表示字节数';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.representation_sha256 IS '冻结表示SHA-256';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.selection_source IS '初始Manifest或目录搜索选择来源';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.ordinal IS 'Job内有界且稳定的输入序号';
-- postgres-only
COMMENT ON COLUMN agent_job_file_working_set_item.created_at IS '工作集项追加时间';
-- postgres-only
COMMENT ON TABLE task_workspace_quota_reservation IS
  '工作区文件数与计费字节事务配额预留事实';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.id IS '配额预留不透明身份';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.workspace_id IS '配额预留所属任务工作区';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.tenant_id IS '配额预留所属平台tenant';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.operation_type IS '产生预留的代码注册操作类型';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.operation_id IS '操作内幂等业务身份';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.logical_file_slots IS '预留的ACTIVE逻辑文件名额';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.billable_bytes IS '预留的预计新增计费字节';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.status IS '配额预留生命周期状态';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.expires_at IS '未终结预留到期时间';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.created_at IS '配额预留创建时间';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.updated_at IS '配额预留最近更新时间';
-- postgres-only
COMMENT ON COLUMN task_workspace_quota_reservation.finalized_at IS '配额预留终结时间';
