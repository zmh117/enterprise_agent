-- Give task files an explicit, stable source-receipt time without overloading
-- generic created_at fields. Existing attachment-backed files are backfilled
-- from database provenance only and never reads object storage.
-- migration: sqlite-foreign-keys-off

-- SQLite cannot replace the schema-version CHECK constraint in place. Rebuild
-- only the immutable manifest header while preserving existing version 1 rows.
-- sqlite-only
CREATE TABLE agent_job_file_snapshot_schema_v2 (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id),
  tenant_id TEXT NOT NULL,
  principal_user_id TEXT NOT NULL,
  business_application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  retention_period TEXT NOT NULL
    CHECK (retention_period IN ('DAY', 'WEEK', 'MONTH')),
  schema_version INTEGER NOT NULL DEFAULT 2 CHECK (schema_version IN (1, 2)),
  manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
  created_at TEXT NOT NULL
);

-- sqlite-only
INSERT INTO agent_job_file_snapshot_schema_v2 (
  id, job_id, workspace_id, tenant_id, principal_user_id,
  business_application_publication_id, retention_period, schema_version,
  manifest_hash, created_at
)
SELECT
  id, job_id, workspace_id, tenant_id, principal_user_id,
  business_application_publication_id, retention_period, schema_version,
  manifest_hash, created_at
FROM agent_job_file_snapshot;

-- sqlite-only
DROP TABLE agent_job_file_snapshot;

-- sqlite-only
ALTER TABLE agent_job_file_snapshot_schema_v2 RENAME TO agent_job_file_snapshot;

-- sqlite-only
CREATE INDEX idx_agent_job_file_snapshot_workspace
  ON agent_job_file_snapshot(workspace_id, created_at);

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  DROP CONSTRAINT agent_job_file_snapshot_schema_version_check;

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  ALTER COLUMN schema_version SET DEFAULT 2;

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  ADD CONSTRAINT agent_job_file_snapshot_schema_version_check
  CHECK (schema_version IN (1, 2));

ALTER TABLE managed_file
  ADD COLUMN source_received_at TEXT;

ALTER TABLE agent_job_file_snapshot_item
  ADD COLUMN source_received_at TEXT;

ALTER TABLE agent_job_file_snapshot_item
  ADD COLUMN version_created_at TEXT NOT NULL DEFAULT '';

UPDATE managed_file
   SET source_received_at = (
         SELECT min(a.created_at)
           FROM message_attachment_file_binding b
           JOIN message_attachment a ON a.id = b.attachment_id
          WHERE b.file_id = managed_file.id
       )
 WHERE source_received_at IS NULL
   AND EXISTS (
         SELECT 1
           FROM message_attachment_file_binding b
           JOIN message_attachment a ON a.id = b.attachment_id
          WHERE b.file_id = managed_file.id
       );

-- Existing immutable Job manifests intentionally remain schema version 1 and
-- keep empty snapshot time columns so their stored manifest hashes do not
-- drift. Newly created schema version 2 manifests freeze both time facts.

-- postgres-only
COMMENT ON COLUMN managed_file.source_received_at IS
  '平台创建原始聊天附件记录的UTC接收时间；无聊天附件来源时为空，后续版本不改变';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot_item.source_received_at IS
  'Job Manifest冻结的原始聊天附件UTC接收时间；无附件来源时为空';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot_item.version_created_at IS
  'Job Manifest冻结的精确文件版本UTC创建时间';
