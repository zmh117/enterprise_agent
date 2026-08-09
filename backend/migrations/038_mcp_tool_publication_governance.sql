DROP TABLE IF EXISTS mcp_job_tool_binding;
DROP TABLE IF EXISTS mcp_tool_publication;

CREATE TABLE mcp_tool (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  catalog_key TEXT NOT NULL,
  name TEXT NOT NULL,
  lifecycle_status TEXT NOT NULL DEFAULT 'ENABLED'
    CHECK (lifecycle_status IN ('ENABLED', 'DISABLED', 'ARCHIVED')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  current_publication_id TEXT,
  created_by TEXT NOT NULL REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_mcp_tool_lifecycle ON mcp_tool(lifecycle_status, code);

CREATE TABLE mcp_tool_draft (
  id TEXT PRIMARY KEY,
  tool_id TEXT NOT NULL REFERENCES mcp_tool(id),
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  catalog_key TEXT NOT NULL,
  resource_deployment_id TEXT NOT NULL DEFAULT '',
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED', 'DISCARDED')),
  verification_json TEXT NOT NULL DEFAULT '{}',
  expected_tool_revision INTEGER NOT NULL CHECK (expected_tool_revision >= 1),
  created_by TEXT NOT NULL REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(tool_id, draft_revision)
);

CREATE UNIQUE INDEX idx_mcp_tool_one_open_draft
  ON mcp_tool_draft(tool_id) WHERE status IN ('DRAFT', 'VERIFIED');

CREATE TABLE mcp_tool_publication (
  id TEXT PRIMARY KEY,
  tool_id TEXT NOT NULL REFERENCES mcp_tool(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  catalog_key TEXT NOT NULL,
  server_code TEXT NOT NULL CHECK (server_code IN ('ones-mcp', 'data-mcp')),
  server_version TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  required_scope TEXT NOT NULL,
  tool_schema_hash TEXT NOT NULL CHECK (length(tool_schema_hash) = 64),
  resource_kind TEXT NOT NULL DEFAULT ''
    CHECK (resource_kind IN ('', 'DATABASE', 'REDIS', 'LOKI')),
  resource_code TEXT NOT NULL DEFAULT '',
  resource_deployment_id TEXT NOT NULL DEFAULT '',
  resource_revision_id TEXT NOT NULL DEFAULT '',
  config_hash TEXT NOT NULL CHECK (length(config_hash) = 64),
  status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  published_by TEXT NOT NULL REFERENCES app_user(id),
  published_at TEXT NOT NULL,
  UNIQUE(tool_id, revision),
  UNIQUE(tool_id, config_hash)
);

CREATE UNIQUE INDEX idx_mcp_tool_one_active_publication
  ON mcp_tool_publication(tool_id) WHERE status = 'PUBLISHED';
CREATE INDEX idx_mcp_tool_publication_lookup
  ON mcp_tool_publication(server_code, tool_name, status);

CREATE TABLE agent_publication_mcp_tool (
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  tool_publication_id TEXT NOT NULL REFERENCES mcp_tool_publication(id),
  PRIMARY KEY(agent_publication_id, tool_publication_id)
);

CREATE TABLE business_application_publication_mcp_tool (
  application_publication_id TEXT NOT NULL REFERENCES business_application_publication(id),
  tool_publication_id TEXT NOT NULL REFERENCES mcp_tool_publication(id),
  PRIMARY KEY(application_publication_id, tool_publication_id)
);

CREATE TABLE mcp_job_tool_binding (
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

CREATE INDEX idx_mcp_job_tool_eligible
  ON mcp_job_tool_binding(job_id, status, server_code, tool_name);

COMMENT ON TABLE mcp_tool IS
  'Stable governed identity selected only from the code-owned ONES/Data MCP catalog';
COMMENT ON TABLE mcp_tool_publication IS
  'Immutable exact MCP Tool contract and optional Resource Deployment binding';
