CREATE TABLE IF NOT EXISTS mcp_tool_publication (
  id TEXT PRIMARY KEY,
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  application_publication_id TEXT REFERENCES business_application_publication(id),
  server_code TEXT NOT NULL CHECK (server_code IN ('ones-mcp', 'data-mcp')),
  tool_name TEXT NOT NULL,
  required_scope TEXT NOT NULL,
  tool_schema_hash TEXT NOT NULL CHECK (length(tool_schema_hash) = 64),
  resource_code TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'DISABLED')),
  created_at TEXT NOT NULL,
  UNIQUE(agent_publication_id, application_publication_id, server_code, tool_name,
         resource_code)
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_publication_lookup
  ON mcp_tool_publication(agent_publication_id, application_publication_id, status);

CREATE TABLE IF NOT EXISTS mcp_job_subject_snapshot (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id),
  app_user_id TEXT NOT NULL REFERENCES app_user(id),
  external_identity_id TEXT NOT NULL DEFAULT '',
  external_subject TEXT NOT NULL DEFAULT '',
  provider_instance_id TEXT NOT NULL DEFAULT '',
  default_team_id TEXT NOT NULL DEFAULT '',
  binding_revision INTEGER NOT NULL DEFAULT 0 CHECK (binding_revision >= 0),
  snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mcp_job_subject_user
  ON mcp_job_subject_snapshot(app_user_id, created_at);

CREATE TABLE IF NOT EXISTS mcp_job_tool_binding (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  tool_publication_id TEXT NOT NULL REFERENCES mcp_tool_publication(id),
  server_code TEXT NOT NULL CHECK (server_code IN ('ones-mcp', 'data-mcp')),
  tool_name TEXT NOT NULL,
  required_scope TEXT NOT NULL,
  tool_schema_hash TEXT NOT NULL CHECK (length(tool_schema_hash) = 64),
  resource_code TEXT NOT NULL DEFAULT '',
  resource_deployment_id TEXT NOT NULL DEFAULT '',
  resource_revision_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('ELIGIBLE', 'UNAVAILABLE')),
  reason_code TEXT NOT NULL DEFAULT '',
  snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(job_id, server_code, tool_name, resource_code)
);

CREATE INDEX IF NOT EXISTS idx_mcp_job_tool_eligible
  ON mcp_job_tool_binding(job_id, status, server_code, tool_name);

CREATE TABLE IF NOT EXISTS mcp_token_revocation (
  jti TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  reason_code TEXT NOT NULL,
  revoked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mcp_token_revocation_job
  ON mcp_token_revocation(job_id, revoked_at);

CREATE TABLE IF NOT EXISTS mcp_tool_call_provenance (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  app_user_id TEXT NOT NULL REFERENCES app_user(id),
  application_publication_id TEXT NOT NULL DEFAULT '',
  mcp_server_code TEXT NOT NULL CHECK (mcp_server_code IN ('ones-mcp', 'data-mcp')),
  server_version TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  tool_schema_hash TEXT NOT NULL CHECK (length(tool_schema_hash) = 64),
  subject_snapshot_id TEXT NOT NULL DEFAULT '',
  resource_deployment_id TEXT NOT NULL DEFAULT '',
  resource_revision_id TEXT NOT NULL DEFAULT '',
  credential_revision INTEGER NOT NULL DEFAULT 0 CHECK (credential_revision >= 0),
  request_summary_json TEXT NOT NULL DEFAULT '{}',
  result_hash TEXT NOT NULL DEFAULT '',
  result_size INTEGER NOT NULL DEFAULT 0 CHECK (result_size >= 0),
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED', 'DENIED')),
  duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
  correlation_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_call_job_time
  ON mcp_tool_call_provenance(job_id, occurred_at, id);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_call_correlation
  ON mcp_tool_call_provenance(correlation_id);

CREATE TABLE IF NOT EXISTS mcp_tool_call_attempt (
  id TEXT PRIMARY KEY,
  provenance_id TEXT NOT NULL REFERENCES mcp_tool_call_provenance(id),
  attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 3),
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED', 'DENIED')),
  error_code TEXT NOT NULL DEFAULT '',
  duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
  created_at TEXT NOT NULL,
  UNIQUE(provenance_id, attempt)
);

CREATE TABLE IF NOT EXISTS mcp_resource (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('DATABASE', 'REDIS', 'LOKI')),
  name TEXT NOT NULL,
  lifecycle_status TEXT NOT NULL DEFAULT 'ENABLED'
    CHECK (lifecycle_status IN ('ENABLED', 'DISABLED', 'ARCHIVED')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mcp_resource_kind_status
  ON mcp_resource(kind, lifecycle_status, code);

CREATE TABLE IF NOT EXISTS mcp_resource_draft (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES mcp_resource(id),
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  manifest_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED', 'DISCARDED')),
  expected_resource_revision INTEGER NOT NULL CHECK (expected_resource_revision >= 1),
  created_by TEXT NOT NULL REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(resource_id, draft_revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_resource_one_open_draft
  ON mcp_resource_draft(resource_id)
  WHERE status IN ('DRAFT', 'VERIFIED');

CREATE TABLE IF NOT EXISTS mcp_resource_verification (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL UNIQUE REFERENCES mcp_resource_draft(id),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL CHECK (status IN ('PASSED', 'FAILED')),
  safe_summary_json TEXT NOT NULL DEFAULT '{}',
  verified_by TEXT NOT NULL REFERENCES app_user(id),
  verified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_resource_revision (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES mcp_resource(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  kind TEXT NOT NULL CHECK (kind IN ('DATABASE', 'REDIS', 'LOKI')),
  manifest_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  verification_id TEXT NOT NULL REFERENCES mcp_resource_verification(id),
  revision_status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (revision_status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  published_by TEXT NOT NULL REFERENCES app_user(id),
  published_at TEXT NOT NULL,
  UNIQUE(resource_id, revision),
  UNIQUE(resource_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_mcp_resource_revision_status
  ON mcp_resource_revision(resource_id, revision_status, revision);

CREATE TABLE IF NOT EXISTS mcp_resource_deployment (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES mcp_resource(id),
  server_code TEXT NOT NULL DEFAULT 'data-mcp' CHECK (server_code = 'data-mcp'),
  resource_revision_id TEXT NOT NULL REFERENCES mcp_resource_revision(id),
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'DISABLED')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  current_generation_id TEXT NOT NULL DEFAULT '',
  last_known_good_generation_id TEXT NOT NULL DEFAULT '',
  updated_by TEXT NOT NULL REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_resource_one_active_deployment
  ON mcp_resource_deployment(resource_id, server_code)
  WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_mcp_resource_deployment_revision
  ON mcp_resource_deployment(resource_revision_id, status);

CREATE TABLE IF NOT EXISTS mcp_resource_generation (
  id TEXT PRIMARY KEY,
  deployment_id TEXT NOT NULL REFERENCES mcp_resource_deployment(id),
  resource_revision_id TEXT NOT NULL REFERENCES mcp_resource_revision(id),
  generation INTEGER NOT NULL CHECK (generation >= 1),
  secret_versions_hash TEXT NOT NULL CHECK (length(secret_versions_hash) = 64),
  status TEXT NOT NULL CHECK (status IN ('BUILDING', 'VERIFYING', 'ACTIVE', 'FAILED', 'SUPERSEDED')),
  safe_error_code TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  claimed_at TEXT,
  builder_id TEXT NOT NULL DEFAULT '',
  activated_at TEXT,
  UNIQUE(deployment_id, generation)
);

CREATE INDEX IF NOT EXISTS idx_mcp_resource_generation_status
  ON mcp_resource_generation(deployment_id, resource_revision_id, status, generation);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_resource_one_pending_generation
  ON mcp_resource_generation(deployment_id)
  WHERE status IN ('BUILDING', 'VERIFYING');

CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_resource_one_active_generation
  ON mcp_resource_generation(deployment_id)
  WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS mcp_resource_generation_secret_version (
  generation_id TEXT NOT NULL REFERENCES mcp_resource_generation(id),
  secret_id TEXT NOT NULL REFERENCES platform_secret(id),
  secret_version INTEGER NOT NULL CHECK (secret_version >= 1),
  PRIMARY KEY(generation_id, secret_id)
);

CREATE TABLE IF NOT EXISTS mcp_operation_idempotency (
  idempotency_key TEXT PRIMARY KEY,
  operation TEXT NOT NULL,
  actor_id TEXT NOT NULL REFERENCES app_user(id),
  request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_cutover_record (
  id TEXT PRIMARY KEY,
  manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
  script_hash TEXT NOT NULL CHECK (length(script_hash) = 64),
  actor_id TEXT NOT NULL REFERENCES app_user(id),
  status TEXT NOT NULL CHECK (status IN ('COMPLETED')),
  completed_at TEXT NOT NULL
);

COMMENT ON TABLE mcp_job_tool_binding IS
  'Immutable exact per-Job MCP allowlist and resource binding facts';
COMMENT ON TABLE mcp_tool_call_provenance IS
  'Safe bounded MCP call history without headers credentials or raw provider responses';
COMMENT ON TABLE mcp_resource_revision IS
  'Immutable verified resource manifest containing secret references but no plaintext secret';
COMMENT ON TABLE mcp_resource_generation IS
  'Runtime generation pinned to one resource revision and exact active secret versions';
