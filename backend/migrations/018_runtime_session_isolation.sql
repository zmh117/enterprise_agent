ALTER TABLE agent_session ADD COLUMN application_publication_id TEXT;
ALTER TABLE agent_session ADD COLUMN execution_scope_hash TEXT;
ALTER TABLE agent_session ADD COLUMN isolation_key_version INTEGER NOT NULL DEFAULT 2;
ALTER TABLE agent_session ADD COLUMN history_read_only INTEGER NOT NULL DEFAULT 0;

UPDATE agent_session
SET isolation_key_version = 1,
    history_read_only = CASE
      WHEN conversation_mode IN ('application', 'actor') THEN 1
      ELSE history_read_only
    END;

CREATE INDEX IF NOT EXISTS idx_agent_session_publication_scope
  ON agent_session(application_publication_id, execution_scope_hash, updated_at);

COMMENT ON COLUMN agent_session.application_publication_id IS 'Session v2 固定的业务应用发布 ID；旧历史可空';
COMMENT ON COLUMN agent_session.execution_scope_hash IS 'Session v2 固定的 canonical Execution Scope SHA-256；旧历史可空';
COMMENT ON COLUMN agent_session.isolation_key_version IS 'Session 隔离键契约版本；新会话为 2';
COMMENT ON COLUMN agent_session.history_read_only IS '旧 application/actor Session 只允许历史读取，不得附着新 Job';
