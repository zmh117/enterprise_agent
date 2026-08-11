-- Direct MCP Tool runtime foundation.
--
-- Before applying the later destructive retirement migration, operators MUST
-- create a logical database backup.  This additive migration deliberately
-- preserves every legacy table so code can be switched before deletion.

ALTER TABLE platform_resource
  ADD COLUMN placement TEXT CHECK (placement IN ('cloud', 'edge'));

CREATE INDEX IF NOT EXISTS idx_platform_resource_direct_resolution
  ON platform_resource(
    resource_kind,
    status,
    environment_id,
    base_id,
    workshop_id,
    placement
  );

CREATE TABLE IF NOT EXISTS agent_publication_mcp_tool (
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL DEFAULT 'tool-mcp'
    CHECK (server_code = 'tool-mcp'),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  model_description TEXT NOT NULL DEFAULT '',
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(agent_publication_id, tool_identifier),
  UNIQUE(agent_publication_id, selection_order)
);

CREATE INDEX IF NOT EXISTS idx_agent_publication_mcp_tool_identifier
  ON agent_publication_mcp_tool(tool_identifier, agent_publication_id);

CREATE TABLE IF NOT EXISTS business_application_revision_mcp_tool (
  application_revision_id TEXT NOT NULL
    REFERENCES business_application_revision(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL DEFAULT 'tool-mcp'
    CHECK (server_code = 'tool-mcp'),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_revision_id, tool_identifier),
  UNIQUE(application_revision_id, selection_order),
  FOREIGN KEY(agent_publication_id, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id,
      tool_identifier
    )
);

CREATE TABLE IF NOT EXISTS business_application_publication_mcp_tool (
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL DEFAULT 'tool-mcp'
    CHECK (server_code = 'tool-mcp'),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_publication_id, tool_identifier),
  UNIQUE(application_publication_id, selection_order),
  FOREIGN KEY(agent_publication_id, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id,
      tool_identifier
    )
);

CREATE INDEX IF NOT EXISTS idx_application_publication_mcp_tool_identifier
  ON business_application_publication_mcp_tool(
    tool_identifier,
    application_publication_id
  );

CREATE TABLE IF NOT EXISTS agent_job_mcp_tool_snapshot (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id),
  application_publication_id TEXT
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  schema_version INTEGER NOT NULL CHECK (schema_version = 1),
  snapshot_json TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
  authorization_hash TEXT NOT NULL CHECK (length(authorization_hash) = 64),
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_mcp_tool_snapshot_publication
  ON agent_job_mcp_tool_snapshot(application_publication_id, created_at);

-- Backfill every publication whose previous exact release envelope can be
-- converted without guessing.  Schema hashes are copied, never recomputed.
INSERT INTO agent_publication_mcp_tool
  (agent_publication_id, server_code, tool_identifier, schema_hash,
   model_description, selection_order, created_at)
SELECT legacy.agent_publication_id,
       'tool-mcp',
       legacy.tool_identifier,
       legacy.public_schema_hash,
       legacy.model_description,
       ROW_NUMBER() OVER (
         PARTITION BY legacy.agent_publication_id
         ORDER BY legacy.tool_identifier
       ) - 1,
       legacy.created_at
  FROM agent_publication_builtin_tool legacy
 WHERE NOT EXISTS (
       SELECT 1
         FROM agent_publication_mcp_tool current
        WHERE current.agent_publication_id = legacy.agent_publication_id
          AND current.tool_identifier = legacy.tool_identifier
 );

INSERT INTO business_application_revision_mcp_tool
  (application_revision_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT legacy.application_revision_id,
       legacy.agent_publication_id,
       'tool-mcp',
       legacy.tool_identifier,
       legacy.public_schema_hash,
       legacy.selection_order,
       legacy.created_at
  FROM business_application_revision_builtin_tool legacy
 WHERE NOT EXISTS (
       SELECT 1
         FROM business_application_revision_mcp_tool current
        WHERE current.application_revision_id = legacy.application_revision_id
          AND current.tool_identifier = legacy.tool_identifier
 );

INSERT INTO business_application_publication_mcp_tool
  (application_publication_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT legacy.application_publication_id,
       legacy.agent_publication_id,
       'tool-mcp',
       legacy.tool_identifier,
       legacy.public_schema_hash,
       ROW_NUMBER() OVER (
         PARTITION BY legacy.application_publication_id
         ORDER BY legacy.tool_identifier
       ) - 1,
       legacy.created_at
  FROM business_application_publication_builtin_tool legacy
 WHERE NOT EXISTS (
       SELECT 1
         FROM business_application_publication_mcp_tool current
        WHERE current.application_publication_id = legacy.application_publication_id
          AND current.tool_identifier = legacy.tool_identifier
 );
