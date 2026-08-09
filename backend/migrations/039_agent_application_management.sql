CREATE TABLE IF NOT EXISTS business_application_revision_mcp_tool (
  application_revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  tool_publication_id TEXT NOT NULL REFERENCES mcp_tool_publication(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  PRIMARY KEY(application_revision_id, tool_publication_id),
  UNIQUE(application_revision_id, binding_order)
);

CREATE INDEX IF NOT EXISTS idx_application_revision_mcp_tool
  ON business_application_revision_mcp_tool(tool_publication_id, application_revision_id);

CREATE TABLE IF NOT EXISTS management_operation_idempotency (
  idempotency_key TEXT PRIMARY KEY,
  operation TEXT NOT NULL,
  actor_id TEXT NOT NULL REFERENCES app_user(id),
  request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

INSERT INTO permission_policy
  (id, subject_type, subject_code, resource_type, resource_code, effect,
   action, status, priority, revision, created_at, updated_at)
VALUES
  ('policy-role-admin-agent-read', 'role', 'platform-admin', 'agent', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

COMMENT ON TABLE business_application_revision_mcp_tool IS
  'Mutable Application Draft selection constrained to its Agent Publication MCP maximum set';
COMMENT ON TABLE management_operation_idempotency IS
  'Bounded replay ledger for authenticated control-plane writes without credentials';
