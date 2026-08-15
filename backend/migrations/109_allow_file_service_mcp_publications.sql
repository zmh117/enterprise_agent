-- Allow immutable Agent and Business Application publications to freeze the
-- deployment-fixed File MCP server. Existing rows and publication hashes are
-- unchanged. This only expands the closed server-code domain.
-- migration: sqlite-foreign-keys-off

-- sqlite-only
ALTER TABLE agent_publication_mcp_tool
  RENAME TO agent_publication_mcp_tool_before_file_service;

-- sqlite-only
CREATE TABLE agent_publication_mcp_tool (
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  model_description TEXT NOT NULL DEFAULT '',
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(agent_publication_id, tool_identifier),
  UNIQUE(agent_publication_id, selection_order),
  UNIQUE(agent_publication_id, server_code, tool_identifier)
);

-- sqlite-only
INSERT INTO agent_publication_mcp_tool
  (agent_publication_id, server_code, tool_identifier, schema_hash,
   model_description, selection_order, created_at)
SELECT agent_publication_id, server_code, tool_identifier, schema_hash,
       model_description, selection_order, created_at
  FROM agent_publication_mcp_tool_before_file_service;

-- sqlite-only
ALTER TABLE business_application_revision_mcp_tool
  RENAME TO business_application_revision_mcp_tool_before_file_service;

-- sqlite-only
CREATE TABLE business_application_revision_mcp_tool (
  application_revision_id TEXT NOT NULL
    REFERENCES business_application_revision(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_revision_id, tool_identifier),
  UNIQUE(application_revision_id, selection_order),
  FOREIGN KEY(agent_publication_id, server_code, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id,
      server_code,
      tool_identifier
    )
);

-- sqlite-only
INSERT INTO business_application_revision_mcp_tool
  (application_revision_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT application_revision_id, agent_publication_id, server_code,
       tool_identifier, schema_hash, selection_order, created_at
  FROM business_application_revision_mcp_tool_before_file_service;

-- sqlite-only
ALTER TABLE business_application_publication_mcp_tool
  RENAME TO business_application_publication_mcp_tool_before_file_service;

-- sqlite-only
CREATE TABLE business_application_publication_mcp_tool (
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_publication_id, tool_identifier),
  UNIQUE(application_publication_id, selection_order),
  FOREIGN KEY(agent_publication_id, server_code, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id,
      server_code,
      tool_identifier
    )
);

-- sqlite-only
INSERT INTO business_application_publication_mcp_tool
  (application_publication_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT application_publication_id, agent_publication_id, server_code,
       tool_identifier, schema_hash, selection_order, created_at
  FROM business_application_publication_mcp_tool_before_file_service;

-- sqlite-only
DROP TABLE business_application_revision_mcp_tool_before_file_service;

-- sqlite-only
DROP TABLE business_application_publication_mcp_tool_before_file_service;

-- sqlite-only
DROP TABLE agent_publication_mcp_tool_before_file_service;

-- postgres-only
ALTER TABLE agent_publication_mcp_tool
  DROP CONSTRAINT agent_publication_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE agent_publication_mcp_tool
  ADD CONSTRAINT agent_publication_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service'));

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  DROP CONSTRAINT business_application_revision_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  ADD CONSTRAINT business_application_revision_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service'));

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  DROP CONSTRAINT business_application_publication_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  ADD CONSTRAINT business_application_publication_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service'));
