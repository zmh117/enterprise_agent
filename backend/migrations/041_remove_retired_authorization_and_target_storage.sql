-- migration: sqlite-foreign-keys-off
-- BREAKING / ONE-WAY MIGRATION
--
-- Complete the legacy platform retirement after migrations 038 and 040.
-- Operators MUST create and verify a fresh logical backup before applying this
-- migration to an existing deployment. Rollback requires restoring that backup.

-- Old runtime target snapshots are no longer an authorization source. The
-- current runtime keeps application/tool publication facts and derives each
-- resource target from the individual MCP Tool call. Session isolation remains
-- represented by agent_session.execution_scope_hash.
DROP INDEX IF EXISTS idx_agent_job_execution_scope_id;
ALTER TABLE agent_job DROP COLUMN execution_scope_id;
ALTER TABLE agent_job DROP COLUMN execution_scope_hash;

DROP TABLE IF EXISTS business_application_publication_target;
DROP TABLE IF EXISTS business_application_revision_target;
DROP TABLE IF EXISTS agent_job_execution_scope;

-- Unified RBAC is the only authorization fact source. These tables were
-- already ignored by production authorization before this migration and must
-- not be converted into new grants implicitly.
DROP TABLE IF EXISTS legacy_authorization_cleanup_operation;
DROP TABLE IF EXISTS platform_access_grant;
DROP TABLE IF EXISTS permission_policy;

-- Migration 038 removed the active Internal API settings but older databases
-- can still contain definition-only timeout/size/auth-token rows. Remove the
-- entire retired namespace, including values that may have been added later.
DELETE FROM platform_runtime_config_value
 WHERE key LIKE 'INTERNAL_API_%'
    OR key = 'FEATURE_REAL_INTERNAL_TOOLS';

DELETE FROM platform_runtime_config_definition
 WHERE key LIKE 'INTERNAL_API_%'
    OR key = 'FEATURE_REAL_INTERNAL_TOOLS';
