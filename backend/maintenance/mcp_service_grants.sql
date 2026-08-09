-- PostgreSQL-only, post-migration grants for fixed first-party service roles.
-- Role passwords are supplied to app.cli.apply_service_grants and never appear here.

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
  FROM enterprise_agent_api, enterprise_agent_worker, ones_mcp_reader, data_mcp_runtime,
       agent_runtime_reader;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
  FROM enterprise_agent_api, enterprise_agent_worker, ones_mcp_reader, data_mcp_runtime,
       agent_runtime_reader;
REVOKE CREATE ON SCHEMA public
  FROM enterprise_agent_api, enterprise_agent_worker, ones_mcp_reader, data_mcp_runtime,
       agent_runtime_reader;
GRANT USAGE ON SCHEMA public
  TO enterprise_agent_api, enterprise_agent_worker, ones_mcp_reader, data_mcp_runtime,
     agent_runtime_reader;

-- The API owns the retained control plane and self-service identity writes. It
-- receives no privilege on retired API Capability/Internal Platform tables.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
  app_user, user_password_credential, user_session, user_external_identity,
  provider_instance, provider_credential, provider_verification_challenge,
  dingtalk_identity_binding_challenge, dingtalk_enterprise,
  dingtalk_identity_application_observation, dingtalk_identity_nickname_audit,
  permission_policy, rbac_role, rbac_user_role,
  rbac_role_admin_capability, rbac_role_application_access,
  rbac_role_application_capability,
  audit_event, model_connection, model_connection_revision,
  agent_definition, agent_revision, agent_publication, agent_skill_binding,
  agent_workflow_template, agent_workflow_node, agent_workflow_edge,
  agent_workflow_publication, business_application,
  business_application_revision, business_application_revision_delivery,
  business_application_revision_trigger, business_application_revision_mcp_tool,
  business_application_publication,
  business_application_deployment, business_application_active_route,
  agent_channel_binding,
  integration_connector, channel_connector_runtime, channel_runtime_lease,
  channel_ingress_event, channel_ingress_outbox,
  webhook_trigger_definition, webhook_trigger_revision,
  webhook_trigger_publication, webhook_event, webhook_outbox,
  webhook_replay_nonce, agent_job, agent_session, agent_message, agent_step,
  agent_artifact, attachment_content, message_attachment,
  job_dispatch_outbox, delivery_outbox, delivery_attempt, delivery_chunk,
  platform_secret, platform_secret_version, platform_secret_change_event,
  platform_runtime_config_definition, platform_runtime_config_value,
  platform_config_audit, mcp_tool, mcp_tool_draft, mcp_tool_publication,
  agent_publication_mcp_tool, business_application_publication_mcp_tool,
  mcp_job_subject_snapshot,
  mcp_job_tool_binding, mcp_token_revocation, mcp_tool_call_provenance,
  mcp_tool_call_attempt, mcp_resource, mcp_resource_draft,
  mcp_resource_verification, mcp_resource_revision,
  mcp_resource_deployment, mcp_resource_generation,
  mcp_resource_generation_secret_version, mcp_operation_idempotency,
  platform_cutover_record, agent_runtime_event
  TO enterprise_agent_api;
GRANT SELECT ON TABLE schema_migration TO enterprise_agent_api;
GRANT SELECT, INSERT ON TABLE management_operation_idempotency
  TO enterprise_agent_api;

-- Workers can read immutable control facts and mutate only runtime/outbox facts.
GRANT SELECT ON TABLE
  schema_migration, app_user, user_external_identity, provider_instance,
  dingtalk_enterprise,
  permission_policy, rbac_role, rbac_user_role,
  rbac_role_application_access,
  agent_definition, agent_revision, agent_publication, agent_skill_binding,
  agent_workflow_template, agent_workflow_node, agent_workflow_edge,
  agent_workflow_publication, business_application,
  business_application_revision, business_application_revision_delivery,
  business_application_revision_trigger,
  business_application_publication,
  business_application_deployment, business_application_active_route,
  agent_channel_binding,
  model_connection, model_connection_revision, integration_connector,
  channel_connector_runtime, webhook_trigger_definition,
  webhook_trigger_revision, webhook_trigger_publication,
  mcp_tool, mcp_tool_publication, agent_publication_mcp_tool,
  business_application_publication_mcp_tool, mcp_resource, mcp_resource_revision,
  mcp_resource_deployment
  TO enterprise_agent_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
  audit_event, agent_job, agent_session, agent_message, agent_step,
  agent_artifact, attachment_content, message_attachment,
  job_dispatch_outbox, delivery_outbox, delivery_attempt, delivery_chunk,
  channel_ingress_event, channel_ingress_outbox, channel_runtime_lease,
  dingtalk_identity_candidate, dingtalk_identity_candidate_message,
  webhook_event, webhook_outbox, webhook_replay_nonce,
  mcp_job_subject_snapshot, mcp_job_tool_binding, mcp_token_revocation,
  mcp_tool_call_provenance, mcp_tool_call_attempt, agent_runtime_event
  TO enterprise_agent_worker;

-- DingTalk channel dispatch records only bounded message-observation facts on
-- an already-bound identity. It cannot create, bind, disable, or unbind an
-- external identity.
GRANT UPDATE (
  last_seen_at, display_name, display_name_observed_at,
  display_name_event_id, display_name_source_connector_id, revision, updated_at
) ON TABLE user_external_identity TO enterprise_agent_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE
  dingtalk_identity_application_observation
  TO enterprise_agent_worker;
GRANT INSERT ON TABLE dingtalk_identity_nickname_audit
  TO enterprise_agent_worker;

-- ONES MCP can resolve one exact user credential and write only bounded call facts.
GRANT SELECT ON TABLE
  schema_migration, app_user, agent_job, user_external_identity,
  provider_instance, provider_credential, mcp_tool_publication,
  mcp_job_subject_snapshot, mcp_job_tool_binding, mcp_token_revocation
  TO ones_mcp_reader;
GRANT UPDATE ON TABLE provider_credential TO ones_mcp_reader;
GRANT SELECT, INSERT ON TABLE mcp_tool_call_provenance, mcp_tool_call_attempt
  TO ones_mcp_reader;

-- Data MCP resolves only published resource generations and active Secret versions.
GRANT SELECT ON TABLE
  schema_migration, app_user, agent_job, mcp_tool_publication,
  mcp_job_subject_snapshot, mcp_job_tool_binding, mcp_token_revocation,
  mcp_resource, mcp_resource_revision, mcp_resource_deployment,
  mcp_resource_generation, mcp_resource_generation_secret_version,
  platform_secret, platform_secret_version, platform_secret_change_event
  TO data_mcp_runtime;
GRANT INSERT ON TABLE
  mcp_resource_generation, mcp_resource_generation_secret_version
  TO data_mcp_runtime;
GRANT UPDATE ON TABLE
  mcp_resource_deployment, mcp_resource_generation, platform_secret_change_event
  TO data_mcp_runtime;
GRANT SELECT, INSERT ON TABLE mcp_tool_call_provenance, mcp_tool_call_attempt
  TO data_mcp_runtime;

-- TypeScript Runtime can read only one frozen model binding and active Secret
-- material. Its writes are isolated to the bounded terminal recovery ledger.
GRANT SELECT (id, protocol, status) ON model_connection TO agent_runtime_reader;
GRANT SELECT (
  id, connection_id, status, config_json, config_hash, api_key_secret_id
) ON model_connection_revision TO agent_runtime_reader;
GRANT SELECT (id, provider, status, active_version)
  ON platform_secret TO agent_runtime_reader;
GRANT SELECT (secret_id, version, ciphertext, nonce, key_id, algorithm, status)
  ON platform_secret_version TO agent_runtime_reader;
GRANT SELECT, INSERT, DELETE ON agent_runtime_terminal_ledger
  TO agent_runtime_reader;
