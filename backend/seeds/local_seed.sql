-- Additive local bootstrap only.
-- Existing rows are managed by the control plane and must never be rewritten
-- when a runtime service restarts with seeding enabled.

INSERT INTO integration_connector
  (id, connector_type, name, base_url, enabled, metadata, allow_ingress, allow_delivery,
   secret_ref, endpoint_ref, host_allowlist, created_at, updated_at)
VALUES
  ('connector-debug-api', 'debug_api', 'debug-api', '', 1, '{}', 1, 0, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-dingtalk-stream-default', 'dingtalk_enterprise_stream', 'dingtalk-stream-default', '', 1,
   '{"client_id_ref":"secret://platform/dingtalk_client_id","tenant_code":"default"}',
   1, 0, 'secret://platform/dingtalk_client_secret', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-dingtalk-enterprise-default', 'dingtalk_enterprise_robot', 'dingtalk-enterprise-default', '', 1,
   '{"client_id_ref":"secret://platform/dingtalk_client_id","default_open_conversation_id":"test-open-conversation","default_robot_code":"test-robot-code"}',
   0, 1, 'secret://platform/dingtalk_client_secret', '', 'api.dingtalk.com,oapi.dingtalk.com', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-dingtalk-webhook-default', 'dingtalk_webhook_robot', 'dingtalk-webhook-default', '', 1, '{}',
   0, 1, 'secret://platform/dingtalk_webhook_robot_secret', 'secret://platform/dingtalk_webhook_robot_url', 'oapi.dingtalk.com,api.dingtalk.com', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-grafana-default', 'grafana_alert', 'grafana-default', '', 1, '{}', 1, 0, 'secret://platform/grafana_webhook_token', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-email-default', 'email', 'email-default', '', 1, '{}', 0, 1, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-webhook-default', 'webhook', 'webhook-default', '', 1, '{}', 0, 1, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('connector-none', 'none', 'none', '', 1, '{}', 0, 1, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO app_user
  (id, username, display_name, email, status, revision, created_at, updated_at)
VALUES
  ('user_local_admin', 'admin', 'Administrator', '', 'enabled', 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO user_password_credential
  (user_id, password_hash, revision, password_changed_at, created_at, updated_at)
VALUES
  ('user_local_admin',
   '$argon2id$v=19$m=65536,t=3,p=4$/fmkNNFzNaJI1FbRRoayJA$HnOPXmib+4StGdpj0RzHkez6N1m0oeeeaMXhswCQCB0',
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
  (id, code, name, description, status, revision, origin, protected,
   purpose_tags_json, metadata_revision, admin_revision, business_revision,
   membership_revision, created_at, updated_at)
VALUES
  ('role_platform_admin', 'platform-admin', '平台管理员',
   'Manage users, roles, platform configuration and Agent publications',
   'enabled', 1, 'system', 1, '["平台管理"]', 1, 1, 1, 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
  ('policy-role-admin-typescript-agent-use', 'role', 'platform-admin', 'agent',
   'typescript-diagnostic-agent', 'allow', 'use', 'enabled', 10, 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
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
  ('policy-role-admin-channel-restart', 'role', 'platform-admin', 'channel_connector', '*',
   'allow', 'restart', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-channel-delete', 'role', 'platform-admin', 'channel_connector', '*',
   'allow', 'delete', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-queue-read', 'role', 'platform-admin', 'queue_status', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-job-read', 'role', 'platform-admin', 'agent_job', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-conversation-read', 'role', 'platform-admin', 'conversation', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-attachment-read', 'role', 'platform-admin', 'attachment', '*',
   'allow', 'read', 'enabled', 10, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-business-application-read', 'role', 'platform-admin',
   'business_application', '*', 'allow', 'read', 'enabled', 10, 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-business-application-create', 'role', 'platform-admin',
   'business_application', '*', 'allow', 'create', 'enabled', 10, 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-business-application-edit', 'role', 'platform-admin',
   'business_application', '*', 'allow', 'edit', 'enabled', 10, 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-business-application-publish', 'role', 'platform-admin',
   'business_application', '*', 'allow', 'publish', 'enabled', 10, 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-role-admin-business-application-activate', 'role', 'platform-admin',
   'business_application', '*', 'allow', 'activate', 'enabled', 10, 1,
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_definition
  (id, code, name, description, project_code, status, current_publication_id,
   classification, runtime_kind, revision, created_by, created_at, updated_at)
VALUES
  ('agent_default_diagnostic', 'default-diagnostic-agent', '默认诊断 Agent',
   'Enterprise internal read-only diagnostic Agent', 'default', 'enabled',
   'agent_publication_default_v1', 'internal_diagnostic', 'python-v1', 1,
   'user_local_admin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
   runtime_kind, status, published_by, published_at)
VALUES
  ('agent_publication_default_v1', 'agent_default_diagnostic',
   'agent_revision_default_v1', 1, 1,
   '{"business_role":"Enterprise internal read-only diagnostic Agent","business_instructions":"Use evidence from approved internal tools and state uncertainty when evidence is incomplete.","model_policy":{"model":"claude-sonnet-4-20250514"},"execution":{"max_turns":12,"timeout_seconds":300},"tools":["get_er_context","get_business_flow_context","get_schema_directory","diagnose_loki_labels","diagnose_loki_label_values","diagnose_loki_probe","query_loki","query_database","query_redis_get","query_redis_scan"],"skills":[],"routing":{"project_code":"default"},"channels":{"ingress":["connector-dingtalk-stream-default"],"delivery":["connector-dingtalk-enterprise-default"]}}',
   'acee515709597912f04ba4e181575c14314121f084dbe561e9e04599179df1b9',
   'python-v1', 'active', 'user_local_admin', CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_definition
  (id, code, name, description, project_code, status, current_publication_id,
   classification, runtime_kind, revision, created_by, created_at, updated_at)
VALUES
  ('agent_typescript_diagnostic', 'typescript-diagnostic-agent',
   'TypeScript 诊断 Agent',
   'Enterprise internal read-only diagnostic Agent using TypeScript Runtime',
   'default', 'enabled', 'agent_publication_typescript_v1',
   'internal_diagnostic', 'typescript-v1', 1, 'user_local_admin',
   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_revision
  (id, agent_id, revision, status, config_json, config_hash, validation_json,
   created_by, created_at, updated_at)
VALUES
  ('agent_revision_typescript_v1', 'agent_typescript_diagnostic', 1, 'published',
   '{"business_instructions":"Use evidence from approved MCP tools and state uncertainty when evidence is incomplete.","business_role":"Enterprise internal read-only diagnostic Agent (TypeScript)","channels":{"delivery":[],"ingress":[]},"execution":{"max_turns":12,"timeout_seconds":300},"mcp_tool_ids":["diagnose_loki_label_values","diagnose_loki_labels","diagnose_loki_probe","get_business_flow_context","get_er_context","get_schema_directory","query_database","query_loki","query_redis_get","query_redis_scan"],"model_policy":{"model":"claude-sonnet-4-20250514"},"routing":{"project_code":"default"},"skills":[]}',
   '70e476bdf1f18af56af4dee2214c8bb48e9d946333aee7dea1e05c38aca61d62',
   '{"valid":true,"errors":[]}', 'user_local_admin', CURRENT_TIMESTAMP,
   CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_publication
  (id, agent_id, revision_id, revision, schema_version, snapshot_json, config_hash,
   runtime_kind, status, published_by, published_at)
VALUES
  ('agent_publication_typescript_v1', 'agent_typescript_diagnostic',
   'agent_revision_typescript_v1', 1, 2,
   '{"business_instructions":"Use evidence from approved MCP tools and state uncertainty when evidence is incomplete.","business_role":"Enterprise internal read-only diagnostic Agent (TypeScript)","channels":{"delivery":[],"ingress":[]},"execution":{"max_turns":12,"timeout_seconds":300},"mcp_tool_envelope":[{"schema_hash":"dbdd1fb7009090387f2479f3e71ab691b67be3ea7fe76345e76c2468610b2796","server_code":"tool-mcp","tool_identifier":"diagnose_loki_label_values"},{"schema_hash":"3fdb9c6cd548513b660a2995cbc5273878e896843aec6c9c6e9b6c1f40d71a27","server_code":"tool-mcp","tool_identifier":"diagnose_loki_labels"},{"schema_hash":"f4f6881d4884b3111e905525c05dbc7f5fd0fb209f7dd3c5163a5d88b999bce1","server_code":"tool-mcp","tool_identifier":"diagnose_loki_probe"},{"schema_hash":"10798ac8d2df2a3150d204e10be2e4fb12cc89650fb68e3a6d3b4b38e1914e26","server_code":"tool-mcp","tool_identifier":"get_business_flow_context"},{"schema_hash":"10798ac8d2df2a3150d204e10be2e4fb12cc89650fb68e3a6d3b4b38e1914e26","server_code":"tool-mcp","tool_identifier":"get_er_context"},{"schema_hash":"7502f1b28fc46291047e9c9d5bc6ba910363596af55aed85a163ea3dc105a1ca","server_code":"tool-mcp","tool_identifier":"get_schema_directory"},{"schema_hash":"9b2fdee7c913e746f58b8149305990f5601044ad7c30b08bc7d4b017d53f6113","server_code":"tool-mcp","tool_identifier":"query_database"},{"schema_hash":"ccec059febb575082e7addfd5b8cc87d5e4e442794b0239e98a73d2897f57108","server_code":"tool-mcp","tool_identifier":"query_loki"},{"schema_hash":"e29e540aeb8e2c982ed7181963deea60f1af7b82f1434a9fd6e1dfdab77c8e50","server_code":"tool-mcp","tool_identifier":"query_redis_get"},{"schema_hash":"f617799ffcb621770965e8bf02042e71ebfc80ba814c05a2b94a4ad0e15d0770","server_code":"tool-mcp","tool_identifier":"query_redis_scan"}],"model_policy":{"model":"claude-sonnet-4-20250514"},"routing":{"project_code":"default"},"runtime_kind":"typescript-v1","skills":[]}',
   '6b589c94249d813ae5821bb6bfbc4367fde0424631a9a7b6354f82889cadb7dc',
   'typescript-v1', 'active', 'user_local_admin', CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO agent_publication_mcp_tool
  (agent_publication_id, server_code, tool_identifier, schema_hash,
   model_description, selection_order, created_at)
VALUES
  ('agent_publication_default_v1', 'tool-mcp', 'diagnose_loki_label_values', 'dbdd1fb7009090387f2479f3e71ab691b67be3ea7fe76345e76c2468610b2796', '', 0, CURRENT_TIMESTAMP),
  ('agent_publication_default_v1', 'tool-mcp', 'diagnose_loki_labels', '3fdb9c6cd548513b660a2995cbc5273878e896843aec6c9c6e9b6c1f40d71a27', '', 1, CURRENT_TIMESTAMP),
  ('agent_publication_default_v1', 'tool-mcp', 'diagnose_loki_probe', 'f4f6881d4884b3111e905525c05dbc7f5fd0fb209f7dd3c5163a5d88b999bce1', '', 2, CURRENT_TIMESTAMP),
  ('agent_publication_default_v1', 'tool-mcp', 'get_business_flow_context', '10798ac8d2df2a3150d204e10be2e4fb12cc89650fb68e3a6d3b4b38e1914e26', '', 3, CURRENT_TIMESTAMP),
  ('agent_publication_default_v1', 'tool-mcp', 'get_er_context', '10798ac8d2df2a3150d204e10be2e4fb12cc89650fb68e3a6d3b4b38e1914e26', '', 4, CURRENT_TIMESTAMP),
  ('agent_publication_default_v1', 'tool-mcp', 'get_schema_directory', '7502f1b28fc46291047e9c9d5bc6ba910363596af55aed85a163ea3dc105a1ca', '', 5, CURRENT_TIMESTAMP),
  ('agent_publication_default_v1', 'tool-mcp', 'query_database', '9b2fdee7c913e746f58b8149305990f5601044ad7c30b08bc7d4b017d53f6113', '', 6, CURRENT_TIMESTAMP),
  ('agent_publication_default_v1', 'tool-mcp', 'query_loki', 'ccec059febb575082e7addfd5b8cc87d5e4e442794b0239e98a73d2897f57108', '', 7, CURRENT_TIMESTAMP),
  ('agent_publication_default_v1', 'tool-mcp', 'query_redis_get', 'e29e540aeb8e2c982ed7181963deea60f1af7b82f1434a9fd6e1dfdab77c8e50', '', 8, CURRENT_TIMESTAMP),
  ('agent_publication_default_v1', 'tool-mcp', 'query_redis_scan', 'f617799ffcb621770965e8bf02042e71ebfc80ba814c05a2b94a4ad0e15d0770', '', 9, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'diagnose_loki_label_values', 'dbdd1fb7009090387f2479f3e71ab691b67be3ea7fe76345e76c2468610b2796', '', 0, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'diagnose_loki_labels', '3fdb9c6cd548513b660a2995cbc5273878e896843aec6c9c6e9b6c1f40d71a27', '', 1, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'diagnose_loki_probe', 'f4f6881d4884b3111e905525c05dbc7f5fd0fb209f7dd3c5163a5d88b999bce1', '', 2, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'get_business_flow_context', '10798ac8d2df2a3150d204e10be2e4fb12cc89650fb68e3a6d3b4b38e1914e26', '', 3, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'get_er_context', '10798ac8d2df2a3150d204e10be2e4fb12cc89650fb68e3a6d3b4b38e1914e26', '', 4, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'get_schema_directory', '7502f1b28fc46291047e9c9d5bc6ba910363596af55aed85a163ea3dc105a1ca', '', 5, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'query_database', '9b2fdee7c913e746f58b8149305990f5601044ad7c30b08bc7d4b017d53f6113', '', 6, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'query_loki', 'ccec059febb575082e7addfd5b8cc87d5e4e442794b0239e98a73d2897f57108', '', 7, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'query_redis_get', 'e29e540aeb8e2c982ed7181963deea60f1af7b82f1434a9fd6e1dfdab77c8e50', '', 8, CURRENT_TIMESTAMP),
  ('agent_publication_typescript_v1', 'tool-mcp', 'query_redis_scan', 'f617799ffcb621770965e8bf02042e71ebfc80ba814c05a2b94a4ad0e15d0770', '', 9, CURRENT_TIMESTAMP)
ON CONFLICT(agent_publication_id, tool_identifier) DO NOTHING;

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
   '{"adapter":"grafana_alertmanager_v1","agent":{"code":"default-diagnostic-agent","publication_id":"agent_publication_default_v1"},"authentication":{"nonce_header":"x-webhook-nonce","secret_ref":"secret://platform/grafana_webhook_token","signature_header":"x-webhook-signature","timestamp_header":"x-webhook-timestamp","type":"bearer_v1","window_seconds":300},"delivery":{"connector_id":"connector-dingtalk-webhook-default","options":{},"target":{"webhook_id":"grafana-alert"},"type":"dingtalk_webhook_robot"},"idempotency":{"cooldown_seconds":300},"limits":{"max_alerts":20,"max_in_flight":10,"requests_per_minute":60},"mapping":{"event_id_pointer":"","filters":[],"message_template":"Diagnose this firing alert: {summary}","status_pointer":"","variables":{"summary":"/commonAnnotations/summary"}},"routing":{"base":{"allowed_values":["guanlan","longhua","songshan"],"mode":"extract","pointer":"/commonLabels/ea_base","value":""},"environment":{"allowed_values":["prod","test"],"mode":"extract","pointer":"/commonLabels/ea_environment","value":""},"project_code":{"allowed_values":["default"],"mode":"extract","pointer":"/commonLabels/ea_project_code","value":""},"service":{"allowed_values":["mes-service","order-service"],"mode":"extract","pointer":"/commonLabels/ea_service","value":""},"workshop":{"allowed_values":["GL001","assembly","packing","smt"],"mode":"extract","pointer":"/commonLabels/ea_workshop","value":""}},"schema_version":1}',
   'fc5f064e955301b104fe7577f1a1c52c9656890e622de40514fa5fdc3d6313de',
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
   '{"adapter":"grafana_alertmanager_v1","agent":{"code":"default-diagnostic-agent","publication_id":"agent_publication_default_v1","revision":1,"config_hash":"acee515709597912f04ba4e181575c14314121f084dbe561e9e04599179df1b9","read_only_tools":["diagnose_loki_label_values","diagnose_loki_labels","diagnose_loki_probe","get_business_flow_context","get_er_context","get_schema_directory","query_database","query_loki","query_redis_get","query_redis_scan"]},"authentication":{"nonce_header":"x-webhook-nonce","secret_ref":"secret://platform/grafana_webhook_token","signature_header":"x-webhook-signature","timestamp_header":"x-webhook-timestamp","type":"bearer_v1","window_seconds":300},"delivery":{"connector_id":"connector-dingtalk-webhook-default","options":{},"target":{"webhook_id":"grafana-alert"},"type":"dingtalk_webhook_robot"},"idempotency":{"cooldown_seconds":300},"limits":{"max_alerts":20,"max_in_flight":10,"requests_per_minute":60},"mapping":{"event_id_pointer":"","filters":[],"message_template":"Diagnose this firing alert: {summary}","status_pointer":"","variables":{"summary":"/commonAnnotations/summary"}},"routing":{"base":{"allowed_values":["guanlan","longhua","songshan"],"mode":"extract","pointer":"/commonLabels/ea_base","value":""},"environment":{"allowed_values":["prod","test"],"mode":"extract","pointer":"/commonLabels/ea_environment","value":""},"project_code":{"allowed_values":["default"],"mode":"extract","pointer":"/commonLabels/ea_project_code","value":""},"service":{"allowed_values":["mes-service","order-service"],"mode":"extract","pointer":"/commonLabels/ea_service","value":""},"workshop":{"allowed_values":["GL001","assembly","packing","smt"],"mode":"extract","pointer":"/commonLabels/ea_workshop","value":""}},"schema_version":1,"service_account_id":"user_webhook_grafana_default","source_connector_id":"connector-grafana-default"}',
   'fc5f064e955301b104fe7577f1a1c52c9656890e622de40514fa5fdc3d6313de',
   'agent_publication_default_v1', 1,
   'acee515709597912f04ba4e181575c14314121f084dbe561e9e04599179df1b9',
   'active', 'user_local_admin', CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO permission_policy
  (id, subject_type, subject_code, resource_type, resource_code, action,
   effect, created_at, updated_at)
VALUES
  ('policy-user-local', 'user', 'admin', 'project', 'default', 'use',
   'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-tool-local', 'user', 'admin', 'tool', '*', 'use',
   'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-platform-config-local', 'user', 'admin', 'platform_config', '*',
   '*', 'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-secret-local', 'user', 'admin', 'secret', '*', '*',
   'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-user-grafana', 'user', 'grafana', 'project', 'default', 'use',
   'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  ('policy-tool-grafana', 'user', 'grafana', 'tool', '*', 'use',
   'allow', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;

INSERT INTO platform_secret_reference
  (id, code, provider, ref, purpose, status, metadata_json, revision, created_at, updated_at)
VALUES
  ('secret-example-order-db-password', 'secret_example_order_db_password', 'secret', 'secret://platform/example_order_db_password', 'example database password reference', 'disabled', '{}', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;
