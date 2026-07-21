CREATE INDEX IF NOT EXISTS idx_agent_job_created_status
  ON agent_job(created_at, status);
CREATE INDEX IF NOT EXISTS idx_agent_job_project_created
  ON agent_job(project_code, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_job_session_created
  ON agent_job(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_job_source_created
  ON agent_job(source_channel, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_session_updated
  ON agent_session(updated_at, id);
CREATE INDEX IF NOT EXISTS idx_agent_session_requester_updated
  ON agent_session(requester_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_agent_message_session_created
  ON agent_message(session_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_message_attachment_created
  ON message_attachment(created_at, id);
CREATE INDEX IF NOT EXISTS idx_delivery_attempt_created_status
  ON delivery_attempt(created_at, status);

ALTER TABLE integration_connector ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_integration_connector_type_enabled
  ON integration_connector(connector_type, enabled);

COMMENT ON INDEX idx_agent_job_created_status IS 'Admin job status and bounded time-window query';
COMMENT ON INDEX idx_agent_session_updated IS 'Admin conversation stable pagination';
COMMENT ON INDEX idx_message_attachment_created IS 'Admin attachment stable pagination';
