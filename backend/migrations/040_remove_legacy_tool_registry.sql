-- Retire the last database-owned Tool registry and Handler binding facts.
--
-- Tool identity and schema are now code-released by MCP_TOOL_MANIFEST. This
-- migration fails closed if an active legacy publication was not converted by
-- migration 037. Operators must keep the verified logical backup made before
-- migration 038 until this migration is accepted.

CREATE TEMP TABLE legacy_tool_registry_guard (
  ok INTEGER NOT NULL CHECK (ok = 1)
);

INSERT INTO legacy_tool_registry_guard(ok)
SELECT 0
 WHERE EXISTS (
   SELECT 1
     FROM agent_tool_binding legacy
     JOIN agent_publication publication
       ON publication.id = legacy.publication_id
     LEFT JOIN agent_publication_mcp_tool current
       ON current.agent_publication_id = legacy.publication_id
      AND current.tool_identifier = legacy.tool_name
    WHERE publication.status = 'active'
      AND current.tool_identifier IS NULL
 );

-- The seeded Internal API connector was never a channel. Refuse deletion if a
-- deployment nevertheless points a channel binding at it.
INSERT INTO legacy_tool_registry_guard(ok)
SELECT 0
 WHERE EXISTS (
   SELECT 1
     FROM agent_channel_binding binding
     JOIN integration_connector connector
       ON connector.id = binding.connector_id
    WHERE connector.connector_type = 'internal_api'
       OR connector.id = 'connector-internal-api'
 );

DROP TABLE IF EXISTS datasource_registry;
DROP TABLE IF EXISTS agent_job_execution_binding;
DROP TABLE IF EXISTS agent_tool_binding;
DROP TABLE IF EXISTS tool_definition;

DELETE FROM rbac_role_admin_capability
 WHERE capability_code LIKE 'builtin_tools.%';

DELETE FROM permission_policy
 WHERE resource_type = 'builtin_tool';

DELETE FROM integration_connector
 WHERE connector_type = 'internal_api'
    OR id = 'connector-internal-api';

DROP TABLE legacy_tool_registry_guard;
