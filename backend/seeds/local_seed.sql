INSERT OR IGNORE INTO tool_definition
  (id, name, risk_level, read_only, enabled, description, created_at, updated_at)
VALUES
  ('tool-get-er-context', 'get_er_context', 'low', 1, 1, 'Search compact ER graph context', datetime('now'), datetime('now')),
  ('tool-get-business-flow-context', 'get_business_flow_context', 'low', 1, 1, 'Search compact business flow context', datetime('now'), datetime('now')),
  ('tool-query-loki', 'query_loki', 'low', 1, 1, 'Query bounded Loki logs', datetime('now'), datetime('now')),
  ('tool-query-database', 'query_database', 'medium', 1, 1, 'Run policy-approved read-only SQL', datetime('now'), datetime('now')),
  ('tool-query-redis-get', 'query_redis_get', 'medium', 1, 1, 'Read approved Redis keys', datetime('now'), datetime('now')),
  ('tool-query-redis-scan', 'query_redis_scan', 'medium', 1, 1, 'Scan approved Redis key prefixes', datetime('now'), datetime('now'));

INSERT OR IGNORE INTO integration_connector
  (id, connector_type, name, base_url, enabled, metadata, created_at, updated_at)
VALUES
  ('connector-internal-api', 'internal_api', 'local-internal-api', 'http://internal-api-platform.local', 1, '{}', datetime('now'), datetime('now'));

INSERT OR IGNORE INTO datasource_registry
  (id, source_type, source_code, connector_id, enabled, metadata, created_at, updated_at)
VALUES
  ('datasource-default', 'service', 'default', 'connector-internal-api', 1, '{}', datetime('now'), datetime('now'));

INSERT OR IGNORE INTO permission_policy
  (id, subject_type, subject_code, resource_type, resource_code, effect, created_at, updated_at)
VALUES
  ('policy-user-local', 'user', 'local-user', 'project', 'default', 'allow', datetime('now'), datetime('now')),
  ('policy-tool-local', 'user', 'local-user', 'tool', '*', 'allow', datetime('now'), datetime('now'));

