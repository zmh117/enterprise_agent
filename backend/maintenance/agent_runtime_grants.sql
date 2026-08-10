-- PostgreSQL-only, post-migration privileges for the TypeScript Agent Runtime.
-- The Runtime cannot read or write Job, RBAC, audit, Delivery, Publication or
-- general platform tables. The sole write boundary is its TTL terminal ledger.

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM agent_runtime_reader;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM agent_runtime_reader;
REVOKE CREATE ON SCHEMA public FROM agent_runtime_reader;
GRANT USAGE ON SCHEMA public TO agent_runtime_reader;

GRANT SELECT (id, protocol, status)
  ON model_connection TO agent_runtime_reader;
GRANT SELECT (
  id, connection_id, status, config_json, config_hash, api_key_secret_id
) ON model_connection_revision TO agent_runtime_reader;
GRANT SELECT (id, provider, status, active_version)
  ON platform_secret TO agent_runtime_reader;
GRANT SELECT (secret_id, version, ciphertext, nonce, key_id, algorithm, status)
  ON platform_secret_version TO agent_runtime_reader;

GRANT SELECT, INSERT, DELETE ON agent_runtime_terminal_ledger
  TO agent_runtime_reader;
