-- migration: sqlite-foreign-keys-off
-- BREAKING / ONE-WAY MIGRATION
--
-- Operators MUST create and verify a logical database backup before applying
-- this migration. After the legacy tables are dropped, rollback requires that
-- backup because there is intentionally no dual-write compatibility mode.

CREATE TEMP TABLE legacy_retirement_guard (
  ok INTEGER NOT NULL CHECK (ok = 1)
);

-- An in-flight Job that only has the old Built-in Tool snapshot cannot be
-- safely resumed by the direct MCP runtime.
INSERT INTO legacy_retirement_guard(ok)
SELECT 0
 WHERE EXISTS (
   SELECT 1
     FROM agent_job job
     JOIN agent_job_builtin_tool_snapshot legacy ON legacy.job_id = job.id
     LEFT JOIN agent_job_mcp_tool_snapshot current ON current.job_id = job.id
    WHERE job.status IN ('WAITING_INPUT', 'PENDING', 'RUNNING', 'RETRY_WAIT')
      AND current.id IS NULL
 );

-- Active deployments may not retain an API Capability composition because
-- there is no semantics-preserving conversion to a code-owned MCP Tool.
INSERT INTO legacy_retirement_guard(ok)
SELECT 0
 WHERE EXISTS (
   SELECT 1
     FROM business_application_deployment deployment
     JOIN business_application_publication_api_capability legacy
       ON legacy.application_publication_id = deployment.publication_id
    WHERE deployment.active = 1
 );

-- Every active old Built-in Tool selection must have an exact identifier and
-- schema hash in the new publication table before deletion.
INSERT INTO legacy_retirement_guard(ok)
SELECT 0
 WHERE EXISTS (
   SELECT 1
     FROM business_application_deployment deployment
     JOIN business_application_publication_builtin_tool legacy
       ON legacy.application_publication_id = deployment.publication_id
     LEFT JOIN business_application_publication_mcp_tool current
       ON current.application_publication_id = legacy.application_publication_id
      AND current.tool_identifier = legacy.tool_identifier
      AND current.schema_hash = legacy.public_schema_hash
    WHERE deployment.active = 1
      AND current.tool_identifier IS NULL
 );

CREATE TABLE IF NOT EXISTS rbac_role_application_mcp_tool (
  id TEXT PRIMARY KEY,
  application_access_id TEXT NOT NULL
    REFERENCES rbac_role_application_access(id),
  tool_identifier TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(application_access_id, tool_identifier)
);

CREATE INDEX IF NOT EXISTS idx_role_application_mcp_tool_identifier
  ON rbac_role_application_mcp_tool(tool_identifier, application_access_id);

INSERT INTO rbac_role_application_mcp_tool
  (id, application_access_id, tool_identifier, created_at)
SELECT legacy.id,
       legacy.application_access_id,
       legacy.capability_code,
       legacy.created_at
  FROM rbac_role_application_capability legacy
 WHERE EXISTS (
   SELECT 1
     FROM business_application_revision_mcp_tool exact
     JOIN rbac_role_application_access access
       ON access.application_id = (
         SELECT revision.application_id
           FROM business_application_revision revision
          WHERE revision.id = exact.application_revision_id
       )
    WHERE access.id = legacy.application_access_id
      AND exact.tool_identifier = legacy.capability_code
 )
   AND NOT EXISTS (
     SELECT 1
       FROM rbac_role_application_mcp_tool current
      WHERE current.application_access_id = legacy.application_access_id
        AND current.tool_identifier = legacy.capability_code
   );

-- Remove retired management grants while preserving the generic admin
-- capability table used by the rest of the control plane.
DELETE FROM rbac_role_admin_capability
 WHERE capability_code LIKE 'api_connections.%'
    OR capability_code LIKE 'api_capabilities.%'
    OR capability_code LIKE 'external_credentials.%';

DELETE FROM platform_runtime_config_value
 WHERE key IN (
   'INTERNAL_API_BASE_URL',
   'INTERNAL_API_AUTH_TOKEN_FILE',
   'INTERNAL_API_SERVER_AUTH_TOKENS_FILE',
   'INTERNAL_API_CLIENT_AUTH_TOKEN_FILE',
   'FEATURE_REAL_INTERNAL_TOOLS'
 );

DELETE FROM platform_runtime_config_definition
 WHERE key IN (
   'INTERNAL_API_BASE_URL',
   'INTERNAL_API_AUTH_TOKEN_FILE',
   'INTERNAL_API_SERVER_AUTH_TOKENS_FILE',
   'INTERNAL_API_CLIENT_AUTH_TOKEN_FILE',
   'FEATURE_REAL_INTERNAL_TOOLS'
 );

-- Job/runtime mapping facts first.
DROP VIEW IF EXISTS builtin_tool_legacy_reference_report;
DROP TABLE IF EXISTS agent_tool_call_builtin_tool_fact;
DROP TABLE IF EXISTS agent_tool_call_http_attempt;
DROP TABLE IF EXISTS agent_tool_call_api_provenance;
DROP TABLE IF EXISTS agent_job_external_subject;
DROP TABLE IF EXISTS builtin_tool_legacy_removal_gate;
DROP TABLE IF EXISTS builtin_tool_legacy_removal_acceptance;
DROP TABLE IF EXISTS builtin_tool_legacy_removal_observation;
DROP TABLE IF EXISTS agent_job_builtin_tool_binding;
DROP TABLE IF EXISTS agent_job_builtin_tool_snapshot;

-- Application Resource Mapping and old publication composition.
DROP TABLE IF EXISTS business_application_publication_builtin_tool_resolution;
DROP TABLE IF EXISTS business_application_publication_builtin_tool_resource;
DROP TABLE IF EXISTS business_application_publication_builtin_tool_resolution_set;
DROP TABLE IF EXISTS business_application_revision_builtin_tool_resource;
DROP TABLE IF EXISTS business_application_resource_binding;
DROP TABLE IF EXISTS business_application_publication_resource;
DROP TABLE IF EXISTS business_application_publication_handler;
DROP TABLE IF EXISTS business_application_publication_api_capability;
DROP TABLE IF EXISTS business_application_publication_builtin_tool;
DROP TABLE IF EXISTS business_application_revision_capability;
DROP TABLE IF EXISTS business_application_revision_builtin_tool;
DROP TABLE IF EXISTS agent_publication_api_capability;
DROP TABLE IF EXISTS agent_publication_builtin_tool;

-- Runtime generation, activation and old resource policy projections.
DROP TABLE IF EXISTS business_application_runtime_state;
DROP TABLE IF EXISTS tool_resource_runtime_state;
DROP TABLE IF EXISTS platform_resource_activation;
DROP TABLE IF EXISTS runtime_snapshot_generation;

DROP TABLE IF EXISTS loki_scope_policy_health_observation;
DROP TABLE IF EXISTS loki_scope_policy_revision_condition;
DROP TABLE IF EXISTS loki_scope_policy_draft_condition;
DROP TABLE IF EXISTS loki_scope_policy_revision;
DROP TABLE IF EXISTS loki_scope_policy_verification;
DROP TABLE IF EXISTS loki_scope_policy_draft;
DROP TABLE IF EXISTS loki_scope_policy;

DROP TABLE IF EXISTS workshop_partition_policy_revision_redis_prefix;
DROP TABLE IF EXISTS workshop_partition_policy_draft_redis_prefix;
DROP TABLE IF EXISTS workshop_partition_policy_revision;
DROP TABLE IF EXISTS workshop_partition_policy_verification;
DROP TABLE IF EXISTS workshop_partition_policy_draft;
DROP TABLE IF EXISTS workshop_partition_policy;

DROP TABLE IF EXISTS platform_resource_binding;

-- Database-owned Built-in Tool release and Handler lifecycle.
DROP TABLE IF EXISTS builtin_tool_lifecycle_audit;
DROP TABLE IF EXISTS builtin_tool_release;
DROP TABLE IF EXISTS builtin_tool_verification;
DROP TABLE IF EXISTS builtin_tool_installation;
DROP TABLE IF EXISTS builtin_tool_manifest_projection;
DROP TABLE IF EXISTS builtin_tool_legacy_migration;
DROP TABLE IF EXISTS builtin_tool_legacy_removal_gate;
DROP TABLE IF EXISTS builtin_tool_legacy_write_audit;

DROP TABLE IF EXISTS handler_publication;
DROP TABLE IF EXISTS handler_installation;

-- Personal external API credentials and API Capability/Connection control
-- plane. user_external_identity itself is intentionally retained.
DROP TABLE IF EXISTS external_api_verification_challenge;
DROP TABLE IF EXISTS external_api_credential;

DROP TABLE IF EXISTS api_capability_release;
DROP TABLE IF EXISTS api_capability_verification;
DROP TABLE IF EXISTS api_capability_draft;
DROP TABLE IF EXISTS api_capability_revision;
DROP TABLE IF EXISTS api_handler_revision;
DROP TABLE IF EXISTS api_handler;
DROP TABLE IF EXISTS api_connection_revision;
DROP TABLE IF EXISTS api_connection_verification;
DROP TABLE IF EXISTS api_connection_draft;
DROP TABLE IF EXISTS api_authentication_profile_revision;
DROP TABLE IF EXISTS api_authentication_profile_draft;
DROP TABLE IF EXISTS api_authentication_profile;
DROP TABLE IF EXISTS api_connection;
DROP TABLE IF EXISTS api_compiled_mapping_plan;
DROP TABLE IF EXISTS api_capability;

DROP TABLE IF EXISTS rbac_role_application_capability;

ALTER TABLE business_application_revision
  DROP COLUMN api_capability_release_ids_json;

DROP TABLE legacy_retirement_guard;
