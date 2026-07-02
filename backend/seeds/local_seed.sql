INSERT INTO tool_definition
  (id, name, risk_level, read_only, enabled, description, created_at, updated_at)
VALUES
  ('tool-get-er-context', 'get_er_context', 'low', 1, 1, 'Search compact ER graph context', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('tool-get-business-flow-context', 'get_business_flow_context', 'low', 1, 1, 'Search compact business flow context', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('tool-get-schema-directory', 'get_schema_directory', 'low', 1, 1, 'Read allowed schema directory', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('tool-diagnose-loki-labels', 'diagnose_loki_labels', 'low', 1, 1, 'List bounded Loki labels', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('tool-diagnose-loki-label-values', 'diagnose_loki_label_values', 'low', 1, 1, 'List bounded Loki label values', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('tool-diagnose-loki-probe', 'diagnose_loki_probe', 'low', 1, 1, 'Probe bounded Loki selector results', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('tool-query-loki', 'query_loki', 'low', 1, 1, 'Query bounded Loki logs', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('tool-query-database', 'query_database', 'medium', 1, 1, 'Run policy-approved read-only SQL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('tool-query-redis-get', 'query_redis_get', 'medium', 1, 1, 'Read approved Redis keys', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('tool-query-redis-scan', 'query_redis_scan', 'medium', 1, 1, 'Scan approved Redis key prefixes', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO integration_connector
  (id, connector_type, name, base_url, enabled, metadata, created_at, updated_at)
VALUES
  ('connector-internal-api', 'internal_api', 'internal-api-platform', 'http://internal-api-platform:9000', 1, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

UPDATE integration_connector
SET allow_ingress = 0,
    allow_delivery = 0,
    updated_at = CURRENT_TIMESTAMP
WHERE id = 'connector-internal-api';

INSERT INTO integration_connector
  (id, connector_type, name, base_url, enabled, metadata, allow_ingress, allow_delivery,
   secret_ref, endpoint_ref, host_allowlist, created_at, updated_at)
VALUES
  ('connector-debug-api', 'debug_api', 'debug-api', '', 1, '{}', 1, 0, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-dingtalk-enterprise-default', 'dingtalk_enterprise_robot', 'dingtalk-enterprise-default', '', 1, '{}', 1, 1, 'test-secret', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-dingtalk-webhook-default', 'dingtalk_webhook_robot', 'dingtalk-webhook-default', '', 1, '{}', 1, 1, 'test-secret', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-grafana-default', 'grafana_alert', 'grafana-default', '', 1, '{}', 1, 0, 'test-grafana-token', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-email-default', 'email', 'email-default', '', 1, '{}', 0, 1, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-webhook-default', 'webhook', 'webhook-default', '', 1, '{}', 0, 1, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-none', 'none', 'none', '', 1, '{}', 0, 1, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO datasource_registry
  (id, source_type, source_code, connector_id, enabled, metadata, created_at, updated_at)
VALUES
  ('datasource-default', 'service', 'default', 'connector-internal-api', 1, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO permission_policy
  (id, subject_type, subject_code, resource_type, resource_code, effect, created_at, updated_at)
VALUES
  ('policy-user-local', 'user', 'local-user', 'project', 'default', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-tool-local', 'user', 'local-user', 'tool', '*', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-user-grafana', 'user', 'grafana', 'project', 'default', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-tool-grafana', 'user', 'grafana', 'tool', '*', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;
