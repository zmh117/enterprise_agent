BEGIN;

-- This script is intentionally irreversible and contains no export, copy,
-- archive, compatibility projection, or data restoration path.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '10min';

UPDATE user_external_identity
   SET status = 'REVERIFICATION_REQUIRED',
       revision = revision + 1,
       binding_revision = binding_revision + 1,
       updated_at = CURRENT_TIMESTAMP
 WHERE provider = 'ones';

TRUNCATE TABLE provider_credential CASCADE;
TRUNCATE TABLE provider_verification_challenge CASCADE;
TRUNCATE TABLE agent_session CASCADE;
TRUNCATE TABLE mcp_resource CASCADE;
TRUNCATE TABLE mcp_operation_idempotency;

DROP TABLE IF EXISTS agent_job_builtin_tool_binding CASCADE;
DROP TABLE IF EXISTS agent_job_builtin_tool_snapshot CASCADE;
DROP TABLE IF EXISTS agent_job_execution_binding CASCADE;
DROP TABLE IF EXISTS agent_job_execution_scope CASCADE;
DROP TABLE IF EXISTS agent_publication_api_capability CASCADE;
DROP TABLE IF EXISTS agent_publication_builtin_tool CASCADE;
DROP TABLE IF EXISTS agent_tool_binding CASCADE;
DROP TABLE IF EXISTS agent_tool_call CASCADE;
DROP TABLE IF EXISTS agent_tool_call_api_provenance CASCADE;
DROP TABLE IF EXISTS agent_tool_call_builtin_tool_fact CASCADE;
DROP TABLE IF EXISTS agent_tool_call_http_attempt CASCADE;
DROP TABLE IF EXISTS api_authentication_profile CASCADE;
DROP TABLE IF EXISTS api_authentication_profile_draft CASCADE;
DROP TABLE IF EXISTS api_authentication_profile_revision CASCADE;
DROP TABLE IF EXISTS api_capability CASCADE;
DROP TABLE IF EXISTS api_capability_draft CASCADE;
DROP TABLE IF EXISTS api_capability_release CASCADE;
DROP TABLE IF EXISTS api_capability_revision CASCADE;
DROP TABLE IF EXISTS api_capability_verification CASCADE;
DROP TABLE IF EXISTS api_compiled_mapping_plan CASCADE;
DROP TABLE IF EXISTS api_connection CASCADE;
DROP TABLE IF EXISTS api_connection_draft CASCADE;
DROP TABLE IF EXISTS api_connection_revision CASCADE;
DROP TABLE IF EXISTS api_connection_verification CASCADE;
DROP TABLE IF EXISTS api_handler CASCADE;
DROP TABLE IF EXISTS api_handler_revision CASCADE;
DROP TABLE IF EXISTS builtin_tool_installation CASCADE;
DROP TABLE IF EXISTS builtin_tool_legacy_migration CASCADE;
DROP TABLE IF EXISTS builtin_tool_legacy_removal_acceptance CASCADE;
DROP TABLE IF EXISTS builtin_tool_legacy_removal_gate CASCADE;
DROP TABLE IF EXISTS builtin_tool_legacy_removal_observation CASCADE;
DROP TABLE IF EXISTS builtin_tool_legacy_write_audit CASCADE;
DROP TABLE IF EXISTS builtin_tool_lifecycle_audit CASCADE;
DROP TABLE IF EXISTS builtin_tool_manifest_projection CASCADE;
DROP TABLE IF EXISTS builtin_tool_release CASCADE;
DROP TABLE IF EXISTS builtin_tool_verification CASCADE;
DROP TABLE IF EXISTS business_application_publication_api_capability CASCADE;
DROP TABLE IF EXISTS business_application_publication_builtin_tool CASCADE;
DROP TABLE IF EXISTS business_application_publication_builtin_tool_resolution CASCADE;
DROP TABLE IF EXISTS business_application_publication_builtin_tool_resolution_set CASCADE;
DROP TABLE IF EXISTS business_application_publication_builtin_tool_resource CASCADE;
DROP TABLE IF EXISTS business_application_publication_handler CASCADE;
DROP TABLE IF EXISTS business_application_publication_resource CASCADE;
DROP TABLE IF EXISTS business_application_publication_target CASCADE;
DROP TABLE IF EXISTS business_application_resource_binding CASCADE;
DROP TABLE IF EXISTS business_application_runtime_state CASCADE;
DROP TABLE IF EXISTS business_application_revision_builtin_tool CASCADE;
DROP TABLE IF EXISTS business_application_revision_builtin_tool_resource CASCADE;
DROP TABLE IF EXISTS business_application_revision_capability CASCADE;
DROP TABLE IF EXISTS business_application_revision_target CASCADE;
DROP TABLE IF EXISTS datasource_registry CASCADE;
DROP TABLE IF EXISTS external_api_credential CASCADE;
DROP TABLE IF EXISTS external_api_verification_challenge CASCADE;
DROP TABLE IF EXISTS handler_installation CASCADE;
DROP TABLE IF EXISTS handler_publication CASCADE;
DROP TABLE IF EXISTS loki_resource_draft_test_session CASCADE;
DROP TABLE IF EXISTS loki_scope_policy CASCADE;
DROP TABLE IF EXISTS loki_scope_policy_draft CASCADE;
DROP TABLE IF EXISTS loki_scope_policy_draft_condition CASCADE;
DROP TABLE IF EXISTS loki_scope_policy_health_observation CASCADE;
DROP TABLE IF EXISTS loki_scope_policy_revision CASCADE;
DROP TABLE IF EXISTS loki_scope_policy_revision_condition CASCADE;
DROP TABLE IF EXISTS loki_scope_policy_verification CASCADE;
DROP TABLE IF EXISTS platform_base CASCADE;
DROP TABLE IF EXISTS platform_environment CASCADE;
DROP TABLE IF EXISTS platform_access_grant CASCADE;
DROP TABLE IF EXISTS platform_resource CASCADE;
DROP TABLE IF EXISTS platform_resource_activation CASCADE;
DROP TABLE IF EXISTS platform_resource_binding CASCADE;
DROP TABLE IF EXISTS platform_resource_draft CASCADE;
DROP TABLE IF EXISTS platform_resource_revision CASCADE;
DROP TABLE IF EXISTS platform_resource_verification CASCADE;
DROP TABLE IF EXISTS platform_secret_reference CASCADE;
DROP TABLE IF EXISTS platform_workshop CASCADE;
DROP TABLE IF EXISTS rbac_role_application_scope CASCADE;
DROP TABLE IF EXISTS resource_reset_operation CASCADE;
DROP TABLE IF EXISTS resource_reset_target CASCADE;
DROP TABLE IF EXISTS runtime_snapshot_generation CASCADE;
DROP TABLE IF EXISTS tool_definition CASCADE;
DROP TABLE IF EXISTS tool_resource_runtime_state CASCADE;
DROP TABLE IF EXISTS workshop_partition_policy CASCADE;
DROP TABLE IF EXISTS workshop_partition_policy_draft CASCADE;
DROP TABLE IF EXISTS workshop_partition_policy_draft_redis_prefix CASCADE;
DROP TABLE IF EXISTS workshop_partition_policy_revision CASCADE;
DROP TABLE IF EXISTS workshop_partition_policy_revision_redis_prefix CASCADE;
DROP TABLE IF EXISTS workshop_partition_policy_verification CASCADE;

ALTER TABLE agent_definition
  DROP COLUMN IF EXISTS classification;
ALTER TABLE agent_job
  DROP COLUMN IF EXISTS execution_scope_id;
ALTER TABLE agent_job
  DROP COLUMN IF EXISTS execution_scope_hash;
ALTER TABLE business_application_revision
  DROP COLUMN IF EXISTS api_capability_release_ids_json;

COMMIT;
