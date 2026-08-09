-- migration: sqlite-foreign-keys-off
-- Irreversible by decision: no backup, export, transform, compatibility view,
-- or data migration is created for the retired platform.

-- postgres-only
DROP TABLE IF EXISTS
  agent_job_builtin_tool_binding,
  agent_job_builtin_tool_snapshot,
  agent_job_execution_binding,
  agent_job_execution_scope,
  agent_publication_api_capability,
  agent_publication_builtin_tool,
  agent_tool_binding,
  agent_tool_call,
  agent_tool_call_api_provenance,
  agent_tool_call_builtin_tool_fact,
  agent_tool_call_http_attempt,
  api_authentication_profile,
  api_authentication_profile_draft,
  api_authentication_profile_revision,
  api_capability,
  api_capability_draft,
  api_capability_release,
  api_capability_revision,
  api_capability_verification,
  api_compiled_mapping_plan,
  api_connection,
  api_connection_draft,
  api_connection_revision,
  api_connection_verification,
  api_handler,
  api_handler_revision,
  builtin_tool_installation,
  builtin_tool_legacy_migration,
  builtin_tool_legacy_removal_acceptance,
  builtin_tool_legacy_removal_gate,
  builtin_tool_legacy_removal_observation,
  builtin_tool_legacy_write_audit,
  builtin_tool_lifecycle_audit,
  builtin_tool_manifest_projection,
  builtin_tool_release,
  builtin_tool_verification,
  business_application_publication_api_capability,
  business_application_publication_builtin_tool,
  business_application_publication_builtin_tool_resolution,
  business_application_publication_builtin_tool_resolution_set,
  business_application_publication_builtin_tool_resource,
  business_application_publication_handler,
  business_application_publication_resource,
  business_application_publication_target,
  business_application_resource_binding,
  business_application_runtime_state,
  business_application_revision_builtin_tool,
  business_application_revision_builtin_tool_resource,
  business_application_revision_capability,
  business_application_revision_target,
  datasource_registry,
  external_api_credential,
  external_api_verification_challenge,
  handler_installation,
  handler_publication,
  loki_resource_draft_test_session,
  loki_scope_policy,
  loki_scope_policy_draft,
  loki_scope_policy_draft_condition,
  loki_scope_policy_health_observation,
  loki_scope_policy_revision,
  loki_scope_policy_revision_condition,
  loki_scope_policy_verification,
  platform_access_grant,
  platform_base,
  platform_environment,
  platform_resource,
  platform_resource_activation,
  platform_resource_binding,
  platform_resource_draft,
  platform_resource_revision,
  platform_resource_verification,
  platform_secret_reference,
  platform_workshop,
  rbac_role_application_scope,
  resource_reset_operation,
  resource_reset_target,
  runtime_snapshot_generation,
  tool_definition,
  tool_resource_runtime_state,
  workshop_partition_policy,
  workshop_partition_policy_draft,
  workshop_partition_policy_draft_redis_prefix,
  workshop_partition_policy_revision,
  workshop_partition_policy_revision_redis_prefix,
  workshop_partition_policy_verification
CASCADE;

-- sqlite-only
DROP TABLE IF EXISTS agent_job_builtin_tool_binding;
-- sqlite-only
DROP TABLE IF EXISTS agent_job_builtin_tool_snapshot;
-- sqlite-only
DROP TABLE IF EXISTS agent_job_execution_binding;
-- sqlite-only
DROP TABLE IF EXISTS agent_job_execution_scope;
-- sqlite-only
DROP TABLE IF EXISTS agent_publication_api_capability;
-- sqlite-only
DROP TABLE IF EXISTS agent_publication_builtin_tool;
-- sqlite-only
DROP TABLE IF EXISTS agent_tool_binding;
-- sqlite-only
DROP TABLE IF EXISTS agent_tool_call;
-- sqlite-only
DROP TABLE IF EXISTS agent_tool_call_api_provenance;
-- sqlite-only
DROP TABLE IF EXISTS agent_tool_call_builtin_tool_fact;
-- sqlite-only
DROP TABLE IF EXISTS agent_tool_call_http_attempt;
-- sqlite-only
DROP TABLE IF EXISTS api_authentication_profile;
-- sqlite-only
DROP TABLE IF EXISTS api_authentication_profile_draft;
-- sqlite-only
DROP TABLE IF EXISTS api_authentication_profile_revision;
-- sqlite-only
DROP TABLE IF EXISTS api_capability;
-- sqlite-only
DROP TABLE IF EXISTS api_capability_draft;
-- sqlite-only
DROP TABLE IF EXISTS api_capability_release;
-- sqlite-only
DROP TABLE IF EXISTS api_capability_revision;
-- sqlite-only
DROP TABLE IF EXISTS api_capability_verification;
-- sqlite-only
DROP TABLE IF EXISTS api_compiled_mapping_plan;
-- sqlite-only
DROP TABLE IF EXISTS api_connection;
-- sqlite-only
DROP TABLE IF EXISTS api_connection_draft;
-- sqlite-only
DROP TABLE IF EXISTS api_connection_revision;
-- sqlite-only
DROP TABLE IF EXISTS api_connection_verification;
-- sqlite-only
DROP TABLE IF EXISTS api_handler;
-- sqlite-only
DROP TABLE IF EXISTS api_handler_revision;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_installation;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_legacy_migration;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_legacy_removal_acceptance;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_legacy_removal_gate;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_legacy_removal_observation;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_legacy_write_audit;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_lifecycle_audit;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_manifest_projection;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_release;
-- sqlite-only
DROP TABLE IF EXISTS builtin_tool_verification;
-- sqlite-only
DROP TABLE IF EXISTS business_application_publication_api_capability;
-- sqlite-only
DROP TABLE IF EXISTS business_application_publication_builtin_tool;
-- sqlite-only
DROP TABLE IF EXISTS business_application_publication_builtin_tool_resolution;
-- sqlite-only
DROP TABLE IF EXISTS business_application_publication_builtin_tool_resolution_set;
-- sqlite-only
DROP TABLE IF EXISTS business_application_publication_builtin_tool_resource;
-- sqlite-only
DROP TABLE IF EXISTS business_application_publication_handler;
-- sqlite-only
DROP TABLE IF EXISTS business_application_publication_resource;
-- sqlite-only
DROP TABLE IF EXISTS business_application_publication_target;
-- sqlite-only
DROP TABLE IF EXISTS business_application_resource_binding;
-- sqlite-only
DROP TABLE IF EXISTS business_application_runtime_state;
-- sqlite-only
DROP TABLE IF EXISTS business_application_revision_builtin_tool;
-- sqlite-only
DROP TABLE IF EXISTS business_application_revision_builtin_tool_resource;
-- sqlite-only
DROP TABLE IF EXISTS business_application_revision_capability;
-- sqlite-only
DROP TABLE IF EXISTS business_application_revision_target;
-- sqlite-only
DROP TABLE IF EXISTS datasource_registry;
-- sqlite-only
DROP TABLE IF EXISTS external_api_credential;
-- sqlite-only
DROP TABLE IF EXISTS external_api_verification_challenge;
-- sqlite-only
DROP TABLE IF EXISTS handler_installation;
-- sqlite-only
DROP TABLE IF EXISTS handler_publication;
-- sqlite-only
DROP TABLE IF EXISTS loki_resource_draft_test_session;
-- sqlite-only
DROP TABLE IF EXISTS loki_scope_policy;
-- sqlite-only
DROP TABLE IF EXISTS loki_scope_policy_draft;
-- sqlite-only
DROP TABLE IF EXISTS loki_scope_policy_draft_condition;
-- sqlite-only
DROP TABLE IF EXISTS loki_scope_policy_health_observation;
-- sqlite-only
DROP TABLE IF EXISTS loki_scope_policy_revision;
-- sqlite-only
DROP TABLE IF EXISTS loki_scope_policy_revision_condition;
-- sqlite-only
DROP TABLE IF EXISTS loki_scope_policy_verification;
-- sqlite-only
DROP TABLE IF EXISTS platform_access_grant;
-- sqlite-only
DROP TABLE IF EXISTS platform_base;
-- sqlite-only
DROP TABLE IF EXISTS platform_environment;
-- sqlite-only
DROP TABLE IF EXISTS platform_resource;
-- sqlite-only
DROP TABLE IF EXISTS platform_resource_activation;
-- sqlite-only
DROP TABLE IF EXISTS platform_resource_binding;
-- sqlite-only
DROP TABLE IF EXISTS platform_resource_draft;
-- sqlite-only
DROP TABLE IF EXISTS platform_resource_revision;
-- sqlite-only
DROP TABLE IF EXISTS platform_resource_verification;
-- sqlite-only
DROP TABLE IF EXISTS platform_secret_reference;
-- sqlite-only
DROP TABLE IF EXISTS platform_workshop;
-- sqlite-only
DROP TABLE IF EXISTS rbac_role_application_scope;
-- sqlite-only
DROP TABLE IF EXISTS resource_reset_operation;
-- sqlite-only
DROP TABLE IF EXISTS resource_reset_target;
-- sqlite-only
DROP TABLE IF EXISTS runtime_snapshot_generation;
-- sqlite-only
DROP TABLE IF EXISTS tool_definition;
-- sqlite-only
DROP TABLE IF EXISTS tool_resource_runtime_state;
-- sqlite-only
DROP TABLE IF EXISTS workshop_partition_policy;
-- sqlite-only
DROP TABLE IF EXISTS workshop_partition_policy_draft;
-- sqlite-only
DROP TABLE IF EXISTS workshop_partition_policy_draft_redis_prefix;
-- sqlite-only
DROP TABLE IF EXISTS workshop_partition_policy_revision;
-- sqlite-only
DROP TABLE IF EXISTS workshop_partition_policy_revision_redis_prefix;
-- sqlite-only
DROP TABLE IF EXISTS workshop_partition_policy_verification;
