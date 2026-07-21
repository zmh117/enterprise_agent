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
  ('connector-dingtalk-stream-default', 'dingtalk_enterprise_stream', 'dingtalk-stream-default', '', 1,
   '{"client_id_ref":"env:DINGTALK_CLIENT_ID","tenant_code":"default"}',
   1, 0, 'env:DINGTALK_CLIENT_SECRET', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-dingtalk-enterprise-default', 'dingtalk_enterprise_robot', 'dingtalk-enterprise-default', '', 1,
   '{"client_id_ref":"env:DINGTALK_CLIENT_ID","default_open_conversation_id":"test-open-conversation","default_robot_code":"test-robot-code"}',
   0, 1, 'env:DINGTALK_CLIENT_SECRET', '', 'api.dingtalk.com,oapi.dingtalk.com', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-dingtalk-webhook-default', 'dingtalk_webhook_robot', 'dingtalk-webhook-default', '', 1, '{}',
   0, 1, 'env:DINGTALK_WEBHOOK_ROBOT_SECRET', 'env:DINGTALK_WEBHOOK_ROBOT_URL', 'oapi.dingtalk.com,api.dingtalk.com', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-grafana-default', 'grafana_alert', 'grafana-default', '', 1, '{}', 1, 0, 'env:GRAFANA_WEBHOOK_TOKEN', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-email-default', 'email', 'email-default', '', 1, '{}', 0, 1, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-webhook-default', 'webhook', 'webhook-default', '', 1, '{}', 0, 1, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-none', 'none', 'none', '', 1, '{}', 0, 1, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

UPDATE integration_connector
SET connector_type = 'grafana_alert',
    allow_ingress = 1,
    allow_delivery = 0,
    secret_ref = 'env:GRAFANA_WEBHOOK_TOKEN',
    updated_at = CURRENT_TIMESTAMP
WHERE id = 'connector-grafana-default';

UPDATE integration_connector
SET connector_type = 'dingtalk_enterprise_stream',
    allow_ingress = 1,
    allow_delivery = 0,
    secret_ref = 'env:DINGTALK_CLIENT_SECRET',
    metadata = '{"client_id_ref":"env:DINGTALK_CLIENT_ID","tenant_code":"default"}',
    updated_at = CURRENT_TIMESTAMP
WHERE id = 'connector-dingtalk-stream-default';

UPDATE integration_connector
SET connector_type = 'dingtalk_enterprise_robot',
    allow_ingress = 0,
    allow_delivery = 1,
    secret_ref = 'env:DINGTALK_CLIENT_SECRET',
    updated_at = CURRENT_TIMESTAMP
WHERE id = 'connector-dingtalk-enterprise-default';

UPDATE integration_connector
SET connector_type = 'dingtalk_webhook_robot',
    allow_ingress = 0,
    allow_delivery = 1,
    updated_at = CURRENT_TIMESTAMP
WHERE id = 'connector-dingtalk-webhook-default';

INSERT INTO datasource_registry
  (id, source_type, source_code, connector_id, enabled, metadata, created_at, updated_at)
VALUES
  ('datasource-default', 'service', 'default', 'connector-internal-api', 1, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO app_user
  (id, username, display_name, email, status, revision, created_at, updated_at)
VALUES
  ('user_local_admin', 'local-user', 'Local Administrator', '', 'enabled', 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO user_password_credential
  (user_id, password_hash, revision, password_changed_at, created_at, updated_at)
VALUES
  ('user_local_admin',
   '$argon2id$v=19$m=65536,t=3,p=4$1tYap6oiM9gZNM+L+eV7EQ$TRvntO4ZwHDzf/JtP+kJq7NL0io0CDiGpVUOeySk9ys',
   1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(user_id) DO NOTHING;

INSERT INTO user_external_identity
  (id, user_id, provider, tenant_code, external_subject_id, connector_id,
   display_name, status, verified_at, last_seen_at, metadata_json, revision,
   created_at, updated_at)
VALUES
  ('identity_local_dingtalk', 'user_local_admin', 'dingtalk', 'default', 'local-user',
   'connector-dingtalk-stream-default', 'Local Administrator', 'enabled',
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '{}', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO rbac_role
  (id, code, name, description, status, revision, created_at, updated_at)
VALUES
  ('role_platform_admin', 'platform-admin', '平台管理员',
   'Manage users, roles, platform configuration and Agent publications',
   'enabled', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO rbac_user_role
  (id, user_id, role_id, status, revision, created_at, updated_at)
VALUES
  ('membership_local_admin', 'user_local_admin', 'role_platform_admin',
   'enabled', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO permission_policy
  (id, subject_type, subject_code, resource_type, resource_code, effect,
   action, status, priority, revision, created_at, updated_at)
VALUES
  ('policy-role-admin-users', 'role', 'platform-admin', 'user', '*', 'allow',
   'manage', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-roles', 'role', 'platform-admin', 'role', '*', 'allow',
   'manage', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-identities', 'role', 'platform-admin', 'identity', '*', 'allow',
   'manage', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-agent-edit', 'role', 'platform-admin', 'agent', '*', 'allow',
   'edit', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-agent-publish', 'role', 'platform-admin', 'agent', '*', 'allow',
   'publish', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-platform', 'role', 'platform-admin', 'platform_config', '*', 'allow',
   'manage', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-secrets', 'role', 'platform-admin', 'secret', '*', 'allow',
   'manage', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-secrets-read', 'role', 'platform-admin', 'secret', '*', 'allow',
   'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-platform-read', 'role', 'platform-admin', 'platform_config', '*', 'allow',
   'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-audit', 'role', 'platform-admin', 'audit', '*', 'allow',
   'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-project', 'role', 'platform-admin', 'project', 'default', 'allow',
   'use', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-tools', 'role', 'platform-admin', 'tool', '*', 'allow',
   'use', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-agent-use', 'role', 'platform-admin', 'agent', 'default-diagnostic-agent',
   'allow', 'use', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-webhook-read', 'role', 'platform-admin', 'webhook_trigger', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-webhook-edit', 'role', 'platform-admin', 'webhook_trigger', '*',
   'allow', 'edit', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-webhook-publish', 'role', 'platform-admin', 'webhook_trigger', '*',
   'allow', 'publish', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-webhook-rotate', 'role', 'platform-admin', 'webhook_trigger', '*',
   'allow', 'rotate', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-webhook-service-account', 'role', 'platform-admin', 'webhook_trigger', '*',
   'allow', 'manage_service_account', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-dashboard-read', 'role', 'platform-admin', 'admin_dashboard', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-skill-read', 'role', 'platform-admin', 'skill_catalog', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-tool-resource-read', 'role', 'platform-admin', 'tool_resource', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-tool-resource-manage', 'role', 'platform-admin', 'tool_resource', '*',
   'allow', 'manage', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-tool-resource-test', 'role', 'platform-admin', 'tool_resource', '*',
   'allow', 'test', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-channel-read', 'role', 'platform-admin', 'channel_connector', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-channel-manage', 'role', 'platform-admin', 'channel_connector', '*',
   'allow', 'manage', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-queue-read', 'role', 'platform-admin', 'queue_status', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-job-read', 'role', 'platform-admin', 'agent_job', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-conversation-read', 'role', 'platform-admin', 'conversation', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-attachment-read', 'role', 'platform-admin', 'attachment', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_definition
  (id, code, name, description, project_code, status, current_publication_id,
   revision, created_by, created_at, updated_at)
VALUES
  ('agent_default_diagnostic', 'default-diagnostic-agent', '默认诊断 Agent',
   'Enterprise internal read-only diagnostic Agent', 'default', 'enabled',
   'agent_publication_default_v1', 1, 'user_local_admin', CURRENT_TIMESTAMP,
   CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_revision
  (id, agent_id, revision, status, config_json, config_hash, validation_json,
   created_by, created_at, updated_at)
VALUES
  ('agent_revision_default_v1', 'agent_default_diagnostic', 1, 'published',
   '{"business_role":"Enterprise internal read-only diagnostic Agent","business_instructions":"Use evidence from approved internal tools and state uncertainty when evidence is incomplete.","model_policy":{"model":"claude-sonnet-4-20250514"},"execution":{"max_turns":12,"timeout_seconds":300},"tools":["get_er_context","get_business_flow_context","get_schema_directory","diagnose_loki_labels","diagnose_loki_label_values","diagnose_loki_probe","query_loki","query_database","query_redis_get","query_redis_scan"],"skills":[],"routing":{"project_code":"default"},"channels":{"ingress":["connector-dingtalk-stream-default"],"delivery":["connector-dingtalk-enterprise-default"]}}',
   'acee515709597912f04ba4e181575c14314121f084dbe561e9e04599179df1b9',
   '{"valid":true,"errors":[]}', 'user_local_admin', CURRENT_TIMESTAMP,
   CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_publication
  (id, agent_id, revision_id, revision, schema_version, snapshot_json, config_hash,
   status, published_by, published_at)
VALUES
  ('agent_publication_default_v1', 'agent_default_diagnostic',
   'agent_revision_default_v1', 1, 1,
   '{"business_role":"Enterprise internal read-only diagnostic Agent","business_instructions":"Use evidence from approved internal tools and state uncertainty when evidence is incomplete.","model_policy":{"model":"claude-sonnet-4-20250514"},"execution":{"max_turns":12,"timeout_seconds":300},"tools":["get_er_context","get_business_flow_context","get_schema_directory","diagnose_loki_labels","diagnose_loki_label_values","diagnose_loki_probe","query_loki","query_database","query_redis_get","query_redis_scan"],"skills":[],"routing":{"project_code":"default"},"channels":{"ingress":["connector-dingtalk-stream-default"],"delivery":["connector-dingtalk-enterprise-default"]}}',
   'acee515709597912f04ba4e181575c14314121f084dbe561e9e04599179df1b9',
   'active', 'user_local_admin', CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_tool_binding (id, publication_id, tool_name, created_at)
SELECT 'binding_default_' || name, 'agent_publication_default_v1', name, CURRENT_TIMESTAMP
FROM tool_definition
WHERE enabled = 1 AND read_only = 1
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_channel_binding
  (id, publication_id, direction, connector_id, config_json, created_at)
VALUES
  ('binding_default_ingress_dingtalk', 'agent_publication_default_v1', 'ingress',
   'connector-dingtalk-stream-default', '{}', CURRENT_TIMESTAMP),
  ('binding_default_delivery_dingtalk', 'agent_publication_default_v1', 'delivery',
   'connector-dingtalk-enterprise-default', '{}', CURRENT_TIMESTAMP),
  ('binding_default_ingress_grafana', 'agent_publication_default_v1', 'ingress',
   'connector-grafana-default', '{}', CURRENT_TIMESTAMP),
  ('binding_default_delivery_dingtalk_webhook', 'agent_publication_default_v1', 'delivery',
   'connector-dingtalk-webhook-default', '{}', CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO app_user
  (id, username, display_name, email, status, account_type, revision, created_at, updated_at)
VALUES
  ('user_webhook_grafana_default', 'svc-webhook-grafana-default',
   'Webhook: 默认 Grafana 告警', '', 'enabled', 'service', 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO permission_policy
  (id, subject_type, subject_code, resource_type, resource_code, effect,
   action, status, priority, revision, created_at, updated_at)
VALUES
  ('policy-webhook-grafana-agent', 'user', 'user_webhook_grafana_default', 'agent',
   'default-diagnostic-agent', 'allow', 'use', 'enabled', 20, 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-webhook-grafana-project', 'user', 'user_webhook_grafana_default', 'project',
   'default', 'allow', 'use', 'enabled', 20, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-webhook-grafana-tools', 'user', 'user_webhook_grafana_default', 'tool',
   '*', 'allow', 'use', 'enabled', 20, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO webhook_trigger_definition
  (id, code, name, trigger_type, public_id, connector_id, service_account_id,
   status, current_publication_id, revision, created_by, created_at, updated_at)
VALUES
  ('webhook_trigger_grafana_default', 'grafana-default', '默认 Grafana 告警',
   'grafana', 'wh_local_grafana_default_00000000000000000001',
   'connector-grafana-default', 'user_webhook_grafana_default', 'enabled',
   'webhook_trigger_publication_grafana_v1', 1, 'user_local_admin',
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO webhook_trigger_revision
  (id, trigger_id, revision, status, schema_version, config_json, config_hash,
   validation_json, created_by, created_at, updated_at)
VALUES
  ('webhook_trigger_revision_grafana_v1', 'webhook_trigger_grafana_default', 1,
   'published', 1,
   '{"adapter":"grafana_alertmanager_v1","agent":{"code":"default-diagnostic-agent","publication_id":"agent_publication_default_v1"},"authentication":{"nonce_header":"x-webhook-nonce","secret_ref":"secret://connector/connector-grafana-default","signature_header":"x-webhook-signature","timestamp_header":"x-webhook-timestamp","type":"bearer_v1","window_seconds":300},"delivery":{"connector_id":"connector-dingtalk-webhook-default","options":{},"target":{"webhook_id":"grafana-alert"},"type":"dingtalk_webhook_robot"},"idempotency":{"cooldown_seconds":300},"limits":{"max_alerts":20,"max_in_flight":10,"requests_per_minute":60},"mapping":{"event_id_pointer":"","filters":[],"message_template":"Diagnose this firing alert: {summary}","status_pointer":"","variables":{"summary":"/commonAnnotations/summary"}},"routing":{"base":{"allowed_values":["guanlan","longhua","songshan"],"mode":"extract","pointer":"/commonLabels/ea_base","value":""},"environment":{"allowed_values":["prod","test"],"mode":"extract","pointer":"/commonLabels/ea_environment","value":""},"project_code":{"allowed_values":["default"],"mode":"extract","pointer":"/commonLabels/ea_project_code","value":""},"service":{"allowed_values":["mes-service","order-service"],"mode":"extract","pointer":"/commonLabels/ea_service","value":""},"workshop":{"allowed_values":["GL001","assembly","packing","smt"],"mode":"extract","pointer":"/commonLabels/ea_workshop","value":""}},"schema_version":1}',
   'fda47d53486bb616baa4089590c5496461211a5e335dbe7eba5d5dbea69cb9bd',
   '{"valid":true,"errors":[]}', 'user_local_admin', CURRENT_TIMESTAMP,
   CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO webhook_trigger_publication
  (id, trigger_id, revision_id, revision, schema_version, snapshot_json,
   config_hash, agent_publication_id, agent_revision, agent_config_hash,
   status, published_by, published_at)
VALUES
  ('webhook_trigger_publication_grafana_v1', 'webhook_trigger_grafana_default',
   'webhook_trigger_revision_grafana_v1', 1, 1,
   '{"adapter":"grafana_alertmanager_v1","agent":{"code":"default-diagnostic-agent","publication_id":"agent_publication_default_v1","revision":1,"config_hash":"acee515709597912f04ba4e181575c14314121f084dbe561e9e04599179df1b9","read_only_tools":["diagnose_loki_label_values","diagnose_loki_labels","diagnose_loki_probe","get_business_flow_context","get_er_context","get_schema_directory","query_database","query_loki","query_redis_get","query_redis_scan"]},"authentication":{"nonce_header":"x-webhook-nonce","secret_ref":"secret://connector/connector-grafana-default","signature_header":"x-webhook-signature","timestamp_header":"x-webhook-timestamp","type":"bearer_v1","window_seconds":300},"delivery":{"connector_id":"connector-dingtalk-webhook-default","options":{},"target":{"webhook_id":"grafana-alert"},"type":"dingtalk_webhook_robot"},"idempotency":{"cooldown_seconds":300},"limits":{"max_alerts":20,"max_in_flight":10,"requests_per_minute":60},"mapping":{"event_id_pointer":"","filters":[],"message_template":"Diagnose this firing alert: {summary}","status_pointer":"","variables":{"summary":"/commonAnnotations/summary"}},"routing":{"base":{"allowed_values":["guanlan","longhua","songshan"],"mode":"extract","pointer":"/commonLabels/ea_base","value":""},"environment":{"allowed_values":["prod","test"],"mode":"extract","pointer":"/commonLabels/ea_environment","value":""},"project_code":{"allowed_values":["default"],"mode":"extract","pointer":"/commonLabels/ea_project_code","value":""},"service":{"allowed_values":["mes-service","order-service"],"mode":"extract","pointer":"/commonLabels/ea_service","value":""},"workshop":{"allowed_values":["GL001","assembly","packing","smt"],"mode":"extract","pointer":"/commonLabels/ea_workshop","value":""}},"schema_version":1,"service_account_id":"user_webhook_grafana_default","source_connector_id":"connector-grafana-default"}',
   'fda47d53486bb616baa4089590c5496461211a5e335dbe7eba5d5dbea69cb9bd',
   'agent_publication_default_v1', 1,
   'acee515709597912f04ba4e181575c14314121f084dbe561e9e04599179df1b9',
   'active', 'user_local_admin', CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO permission_policy
  (id, subject_type, subject_code, resource_type, resource_code, effect, created_at, updated_at)
VALUES
  ('policy-user-local', 'user', 'local-user', 'project', 'default', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-tool-local', 'user', 'local-user', 'tool', '*', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-platform-config-local', 'user', 'local-user', 'platform_config', '*', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-secret-local', 'user', 'local-user', 'secret', '*', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-user-grafana', 'user', 'grafana', 'project', 'default', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-tool-grafana', 'user', 'grafana', 'tool', '*', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO platform_secret_reference
  (id, code, provider, ref, purpose, status, metadata_json, revision, created_at, updated_at)
VALUES
  ('secret-example-order-db-password', 'secret_example_order_db_password', 'env', 'env:ORDER_DB_PASSWORD', 'example database password reference', 'disabled', '{}', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;
