-- migration: sqlite-foreign-keys-off
-- Direct Agent Jobs freeze resource-free exact Tool Envelopes without an
-- Application Publication. Resource-backed Tools still require an Application.

-- sqlite-only
PRAGMA legacy_alter_table = ON;

-- sqlite-only
ALTER TABLE agent_job_builtin_tool_snapshot
  RENAME TO agent_job_builtin_tool_snapshot_pre_direct_agent;

-- sqlite-only
CREATE TABLE agent_job_builtin_tool_snapshot (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id),
  application_publication_id TEXT
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  schema_version INTEGER NOT NULL CHECK (schema_version = 3),
  snapshot_json TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL UNIQUE CHECK (length(snapshot_hash) = 64),
  authorization_hash TEXT NOT NULL CHECK (length(authorization_hash) = 64),
  created_at TEXT NOT NULL
);

-- sqlite-only
INSERT INTO agent_job_builtin_tool_snapshot
  (id, job_id, application_publication_id, agent_publication_id,
   schema_version, snapshot_json, snapshot_hash, authorization_hash,
   created_at)
SELECT id, job_id, application_publication_id, agent_publication_id,
       schema_version, snapshot_json, snapshot_hash, authorization_hash,
       created_at
  FROM agent_job_builtin_tool_snapshot_pre_direct_agent;

-- sqlite-only
DROP TABLE agent_job_builtin_tool_snapshot_pre_direct_agent;

-- sqlite-only
CREATE INDEX idx_job_builtin_tool_snapshot_publication
  ON agent_job_builtin_tool_snapshot(application_publication_id, created_at);

-- sqlite-only
PRAGMA legacy_alter_table = OFF;

-- postgres-only
ALTER TABLE agent_job_builtin_tool_snapshot
  ALTER COLUMN application_publication_id DROP NOT NULL;
