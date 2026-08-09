-- Run as a PostgreSQL owner during deployment. Login credentials are created
-- outside this repository and granted membership in this NOLOGIN role.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_runtime_reader') THEN
    CREATE ROLE agent_runtime_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END
$$;

REVOKE ALL ON TABLE model_connection FROM agent_runtime_reader;
REVOKE ALL ON TABLE model_connection_revision FROM agent_runtime_reader;
REVOKE ALL ON TABLE platform_secret FROM agent_runtime_reader;
REVOKE ALL ON TABLE platform_secret_version FROM agent_runtime_reader;
REVOKE ALL ON TABLE agent_runtime_terminal_ledger FROM agent_runtime_reader;

GRANT USAGE ON SCHEMA public TO agent_runtime_reader;
GRANT SELECT (id, protocol, status) ON model_connection TO agent_runtime_reader;
GRANT SELECT (
  id,
  connection_id,
  status,
  config_json,
  config_hash,
  api_key_secret_id
) ON model_connection_revision TO agent_runtime_reader;
GRANT SELECT (
  id,
  provider,
  status,
  active_version
) ON platform_secret TO agent_runtime_reader;
GRANT SELECT (
  secret_id,
  version,
  ciphertext,
  nonce,
  key_id,
  algorithm,
  status
) ON platform_secret_version TO agent_runtime_reader;
GRANT SELECT, INSERT, DELETE ON agent_runtime_terminal_ledger TO agent_runtime_reader;
